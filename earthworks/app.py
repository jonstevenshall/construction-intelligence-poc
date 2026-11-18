"""Small local/Coolify review app. No framework, API key or paid calls required."""
import argparse
import hmac
import html
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .agent import ReviewAgent
from .budget import Budget, BudgetError, SpendLimitError, ProviderRequestError, explain_with_model
from .corpus import ROOT, generate
from .config import load_local_env
from .conversation import ConversationAgent
from .data_workbench import DataWorkbench
from .store import Store, INDEX_VERSION


def main():
    load_local_env()
    parser=argparse.ArgumentParser()
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    public_demo=os.getenv("PUBLIC_DEMO","false").lower()=="true"
    access_token=os.getenv("DEMO_ACCESS_TOKEN","")
    if not public_demo and args.host not in ["127.0.0.1","localhost","::1"] and len(access_token)<24:
        parser.error("A DEMO_ACCESS_TOKEN of at least 24 characters is required for a non-loopback bind")
    if not public_demo and os.getenv("LLM_ENABLED","false").lower()=="true" and len(access_token)<24:
        parser.error("Enabling paid model calls also requires a DEMO_ACCESS_TOKEN of at least 24 characters")
    if not (ROOT/"data"/"manifest.json").exists():
        generate()
    store=Store()
    store.datasets.allow_private=not public_demo
    if not store.records("projects"):
        print(json.dumps(store.ingest()),flush=True)
    print(json.dumps(store.ingest_public_context()),flush=True)
    for directory in sorted((ROOT/"data"/"datasets").glob("*/manifest.json")):
        print(json.dumps(store.datasets.import_directory(directory.parent)),flush=True)
    agent=ReviewAgent(store)
    budget=Budget.public_demo() if public_demo else Budget()
    conversation=ConversationAgent(agent,budget)
    workbench=DataWorkbench(store)
    manifest=json.loads((ROOT/"data"/"manifest.json").read_text())
    sources=json.loads((ROOT/"docs"/"public-sources.json").read_text())

    class Handler(BaseHTTPRequestHandler):
        def send(self,status,body,content_type="application/json; charset=utf-8"):
            raw=json.dumps(body,ensure_ascii=False).encode() if content_type.startswith("application/json") else body.encode() if isinstance(body,str) else body
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            if public_demo:
                return True
            if not access_token:
                return True
            supplied=self.headers.get("Authorization","").removeprefix("Bearer ")
            return hmac.compare_digest(supplied,access_token)

        def valid_host(self):
            if public_demo or access_token:
                return True
            try:
                return urlparse("http://"+self.headers.get("Host","")).hostname in ["127.0.0.1","localhost","::1"]
            except ValueError:
                return False

        def do_GET(self):
            if not self.valid_host():
                return self.send(403,{"error":"Unrecognised local host"})
            url=urlparse(self.path)
            path=url.path
            params=parse_qs(url.query)
            if path in ["/","/app.js","/style.css"]:
                filename={"/":"index.html","/app.js":"app.js","/style.css":"style.css"}[path]
                mime={"/":"text/html; charset=utf-8","/app.js":"text/javascript; charset=utf-8","/style.css":"text/css; charset=utf-8"}[path]
                return self.send(200,(ROOT/"web"/filename).read_bytes(),mime)
            if path=="/health":
                return self.send(200,{"status":"ok","synthetic":True})
            if not self.allowed():
                return self.send(401,{"error":"Access token required"})
            try:
                if path=="/api/status":
                    enabled=os.getenv("LLM_ENABLED","false").lower()=="true"
                    usage=budget.status()
                    return self.send(200,{"manifest":manifest,"counts":store.counts(),"public_context_counts":store.public_counts(),"public_context":agent.context.status(),"backend":store.backend,"embedding":INDEX_VERSION,"llm_enabled":enabled,"llm_ready":enabled and bool(os.getenv("OPENAI_API_KEY")) and os.getenv("OPENAI_MODEL","gpt-6-luna") in usage["allowed_models"] and not usage["exhausted"],"budget":usage,"public_demo":public_demo,"imports_allowed":not public_demo})
                if path=="/api/projects":
                    return self.send(200,[{key:p[key] for key in ["id","name","suburb","tender_date","site_area_acres"]} for p in agent.projects.values()])
                if path.startswith("/api/project/"):
                    return self.send(200,agent.package(path.split("/")[-1]))
                if path.startswith("/api/quote/"):
                    qid=path.split("/")[-1]
                    if not re.fullmatch(r"Q\d{4}",qid):
                        raise ValueError("Invalid quote ID")
                    quote=next((q for q in agent.quotes if q["id"]==qid),None)
                    if quote is None:
                        return self.send(404,{"error":"Unknown quote"})
                    package=agent.package(quote["project_id"])
                    return self.send(200,next(q for q in package["quotes"] if q["id"]==qid))
                if path=="/api/sources":
                    return self.send(200,sources)
                if path=="/api/datasets":
                    return self.send(200,store.datasets.discover(params.get("as_of",["9999-12-31"])[0]))
                if path=="/api/data":
                    return self.send(200,workbench.overview())
                if path=="/api/data/graph":
                    return self.send(200,workbench.graph(params.get("entity",[""])[0]))
                if path.startswith("/api/data/source/"):
                    parts=path.split("/")
                    if len(parts)!=6:raise ValueError("Choose a dataset and version")
                    return self.send(200,workbench.source(*parts[-2:]))
                if path.startswith("/api/evidence/"):
                    parts=path.split("/")
                    if len(parts)!=6:
                        raise ValueError("Choose a dataset, version and record")
                    return self.send(200,store.datasets.get(*parts[-3:]))
                if path=="/api/vendors":
                    return self.send(200,agent.vendors)
                if path=="/api/graph":
                    entity=params.get("id",[""])[0]
                    if not re.fullmatch(r"(?:P\d{3}|V\d{3}|Q\d{4}(?:-[A-Z]{2}\d{2})?)",entity):
                        raise ValueError("Choose a known project, supplier, quote or quote line ID")
                    return self.send(200,store.graph(entity))
                if path.startswith("/api/document/"):
                    qid=path.split("/")[-1]
                    if not re.fullmatch(r"Q\d{4}",qid):
                        raise ValueError("Invalid document ID")
                    document=ROOT/"data"/"documents"/(qid+".md")
                    if not document.exists():
                        return self.send(404,{"error":"Unknown document"})
                    return self.send(200,{"id":qid,"lines":document.read_text().splitlines()})
                return self.send(404,{"error":"Not found"})
            except (ValueError,KeyError) as exc:
                return self.send(400,{"error":str(exc)})

        def do_POST(self):
            # Same-origin only; no cross-origin API access or model-supplied URLs/SQL.
            if not self.valid_host():
                return self.send(403,{"error":"Unrecognised local host"})
            origin=self.headers.get("Origin")
            if origin and urlparse(origin).netloc!=self.headers.get("Host"):
                return self.send(403,{"error":"Cross-origin request rejected"})
            if not self.allowed():
                return self.send(401,{"error":"Access token required"})
            if public_demo and self.path=="/api/data/import":
                return self.send(403,{"error":"Stored datasets are read-only in the public demo. Run a private instance to import evidence.","code":"READ_ONLY_DEMO"})
            try:
                size=int(self.headers.get("Content-Length","0"))
                limit=4300000 if self.path in ["/api/data/inspect","/api/data/preview","/api/data/import"] else 60000
                if size<1 or size>limit:
                    raise ValueError("Request exceeds the allowed byte limit")
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):
                    raise ValueError("Expected an object")
                if self.path=="/api/data/inspect":
                    return self.send(200,workbench.inspect(payload))
                if self.path=="/api/data/preview":
                    return self.send(200,workbench.preview(payload))
                if self.path=="/api/data/import":
                    return self.send(200,workbench.commit(payload))
                if self.path=="/api/chat":
                    question=payload.get("question","")
                    if not isinstance(question,str) or len(question)>2000:
                        raise ValueError("Question must be text, at most 2000 characters")
                    result=agent.ask(question,payload.get("project_id"))
                    if os.getenv("LLM_ENABLED","false").lower()=="true":
                        result["ai_explanation"]=explain_with_model({"question":question,"answer":result["answer"],"followup_questions":result["followup_questions"],"evidence":[{**e,"text":e["text"][:1800]} for e in result["evidence"]]},budget)
                    return self.send(200,result)
                if self.path=="/api/converse":
                    return self.send(200,conversation.turn(payload))
                if self.path=="/api/estimate":
                    return self.send(200,agent.estimate(payload))
                if self.path=="/api/plan":
                    return self.send(200,agent.plan_questions(payload))
                if self.path=="/api/search":
                    question=payload.get("query","")
                    if not isinstance(question,str):
                        raise ValueError("Search must be text")
                    return self.send(200,store.search(question,payload.get("project_id"),payload.get("as_of"),5))
                if self.path=="/api/context":
                    return self.send(200,agent.context.scenario(payload))
                return self.send(404,{"error":"Not found"})
            except (ValueError,KeyError,TypeError,BudgetError) as exc:
                code="DEMO_SPEND_LIMIT" if isinstance(exc,SpendLimitError) else "PROVIDER_RATE_LIMIT" if isinstance(exc,ProviderRequestError) and exc.status==429 else "MODEL_UNAVAILABLE" if isinstance(exc,ProviderRequestError) and exc.status in [401,403] else "REQUEST_FAILED"
                return self.send(400,{"error":str(exc),"code":code})
            except Exception:
                # Do not expose credentials, provider payloads or connection details.
                return self.send(502,{"error":"Request failed. No automatic retry was attempted. Check the local service logs."})

        def log_message(self,format,*values):
            # Request paths only; no tokens, chat content or provider responses.
            print(format % values,flush=True)

    server=ThreadingHTTPServer((args.host,args.port),Handler)
    mode="live conversational agent enabled" if os.getenv("LLM_ENABLED","false").lower()=="true" else "scripted mode; paid API disabled"
    print(f"Earthworks Lab: http://{args.host}:{args.port} | {store.backend} | {mode}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__=="__main__":
    main()
