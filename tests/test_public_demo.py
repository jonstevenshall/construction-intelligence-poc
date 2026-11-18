"""Public access and spend controls; provider calls are never used here."""
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from earthworks.budget import Budget, SpendLimitError
from earthworks.corpus import ROOT


class PublicBudgetTests(unittest.TestCase):
    def test_public_cap_is_global_persistent_and_cannot_be_raised_by_private_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"LLM_LIFETIME_BUDGET_USD":"100","LLM_DAILY_BUDGET_USD":"100"}):
            path=Path(directory)/"public.sqlite"
            budget=Budget.public_demo(path)
            def reserve(_):
                try:budget.reserve("gpt-6-luna",0,2000000);return True
                except SpendLimitError:return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                accepted=list(pool.map(reserve,range(8)))
            self.assertEqual(sum(accepted),3)
            status=Budget.public_demo(path).status()
            self.assertEqual(status["lifetime_cap_usd"],3)
            self.assertEqual(status["charged_or_reserved_usd"],3)
            self.assertTrue(status["exhausted"])
            with self.assertRaises(SpendLimitError):Budget.public_demo(path).reserve("gpt-6-luna",1,1)


class PublicHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        cls.base="http://127.0.0.1:"+str(port)
        directory=repr(cls.temp.name)
        script=f'''import sys,time
from pathlib import Path
from earthworks import app
from earthworks.store import Store
from earthworks.budget import Budget
directory=Path({directory})
app.load_local_env=lambda:None
app.Store=lambda:Store(directory/"data.sqlite",database_url="")
factory=Budget.public_demo
app.Budget.public_demo=lambda:factory(directory/"usage.sqlite")
class FixtureConversation:
    def __init__(self,*args):pass
    def turn(self,payload):time.sleep(.4);return {{"fixture":True}}
app.ConversationAgent=FixtureConversation
sys.argv=["public-http-check","--port","{port}"]
app.main()
'''
        env={**os.environ,"PUBLIC_DEMO":"true","LLM_ENABLED":"false","OPENAI_API_KEY":"","DEMO_ACCESS_TOKEN":""}
        cls.process=subprocess.Popen([sys.executable,"-c",script],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if cls.process.poll() is not None:raise RuntimeError(cls.process.stderr.read().decode())
            try:
                with urllib.request.urlopen(cls.base+"/health",timeout=1):return
            except OSError:time.sleep(.1)
        cls.process.terminate();raise RuntimeError("Public HTTP test did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=5);cls.process.stderr.close();cls.temp.cleanup()

    def request(self,path,payload=None,headers=None):
        headers=headers or {}
        raw=json.dumps(payload).encode() if payload is not None else None
        if raw:headers={**headers,"Content-Type":"application/json"}
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base+path,data=raw,headers=headers),timeout=5) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:return exc.code,json.load(exc)

    def test_anonymous_read_access_has_no_token_requirement(self):
        status,data=self.request("/api/status")
        self.assertEqual(status,200);self.assertTrue(data["public_demo"])
        self.assertFalse(data["imports_allowed"]);self.assertEqual(data["budget"]["lifetime_cap_usd"],3)
        self.assertEqual(self.request("/api/projects")[0],200)
        self.assertEqual(self.request("/api/data")[0],200)

    def test_anonymous_import_cannot_mutate_evidence(self):
        status,data=self.request("/api/data/import",{})
        self.assertEqual(status,403);self.assertEqual(data["code"],"READ_ONLY_DEMO")

    def test_multiple_visitors_can_use_the_demo_without_a_single_user_gate(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.request("/api/converse",{"message":"test"}),range(2)))
        self.assertEqual([status for status,_ in responses],[200,200])
        self.assertTrue(all(data["fixture"] for _,data in responses))

    def test_cross_origin_post_is_rejected(self):
        self.assertEqual(self.request("/api/converse",{},headers={"Origin":"https://example.test"})[0],403)
