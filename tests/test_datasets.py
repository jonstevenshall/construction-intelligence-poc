import json
import tempfile
import unittest
from pathlib import Path

from earthworks.agent import ReviewAgent
from earthworks.budget import Budget
from earthworks.conversation import ConversationAgent,INSTRUCTIONS,PROPERTIES
from earthworks.store import Store


def write_dataset(directory,version="v1",available="2025-01-01",value=17):
    manifest={"id":"unanticipated-source","version":version,"name":"Unanticipated evidence","description":"Unknown fields exercise the shared contract","data_kind":"synthetic","available_date":available,"records_file":"evidence.jsonl"}
    row={"id":"R1","text":"Groundwater monitoring: a fictional observation for project P001.","facts":{"sensor_zeta":{"reading":value,"unit":"invented-unit"},"unplanned_attribute":False},"entities":["P001"],"available_date":available,"effective_date":available,"source":{"uri":"synthetic:sensor-evidence","locator":"Observation R1"}}
    (directory/"manifest.json").write_text(json.dumps(manifest))
    (directory/"evidence.jsonl").write_text(json.dumps(row)+"\n")
    return row


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.store=Store(self.directory/"store.sqlite",database_url="")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_unknown_fields_discovered_retrieved_and_cited_without_prompt_or_schema_change(self):
        schema_before=self.store.conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        prompt_before=INSTRUCTIONS
        original=write_dataset(self.directory)
        self.store.datasets.import_directory(self.directory)
        self.assertEqual(schema_before,self.store.conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall())
        self.assertEqual(INSTRUCTIONS,prompt_before)
        found=self.store.datasets.search("groundwater sensor_zeta","2025-02-01",entity_id="P001")
        self.assertIn("sensor_zeta",found["datasets"][0]["fact_fields"])
        record=found["matches"][0]["record"]
        self.assertEqual(record["facts"],original["facts"])
        self.assertEqual(record["source"],original["source"])
        self.assertEqual(record["import_provenance"]["line"],1)
        self.assertEqual(len(record["import_provenance"]["sha256"]),64)
        self.assertFalse(self.store.datasets.search("groundwater","2025-02-01",entity_id="P002")["matches"])
        self.assertFalse(self.store.datasets.search("groundwater","2024-12-31")["matches"])
        # The same generic tool can discover the new source and cite its actual value.
        review=ReviewAgent(self.store)
        brief={key:None for key in PROPERTIES};brief["scope_note"]="Synthetic P001 sensor evidence"
        calls=[]
        def provider(payload,budget):
            calls.append(payload)
            if len(calls)==1:
                return {"output":[{"type":"function_call","name":"search_datasets","call_id":"new-source","arguments":json.dumps({"query":"groundwater","dataset_id":None,"entity_id":"P001"})}]}
            evidence=json.loads(payload["input"][-1]["output"])
            self.assertEqual(evidence["matches"][0]["record"]["facts"]["sensor_zeta"]["reading"],17)
            return {"output":[{"type":"message","content":[{"type":"output_text","text":json.dumps({"brief":brief,"explanation":"The fictional source reports a reading of 17 invented-unit.","questions":[],"citations":[evidence["matches"][0]["citation_id"]],"provenance":["Read the original sensor record; no price adjustment."]})}]}]}
        result=ConversationAgent(review,Budget(self.directory/"budget.sqlite"),provider).turn({"message":"What does the new source say?","as_of":"2025-02-01"})
        self.assertEqual(result["citations"][0]["kind"],"dataset")
        self.assertEqual(result["citations"][0]["record_id"],"R1")
        def followup(payload,budget):
            return {"output":[{"type":"message","content":[{"type":"output_text","text":json.dumps({"brief":brief,"explanation":"The earlier source is still the basis for that reading.","questions":[],"citations":[result["citations"][0]["id"]],"provenance":[]})}]}]}
        agent=ConversationAgent(review,Budget(self.directory/"followup.sqlite"),followup)
        second=agent.turn({"message":"Which source was that?","brief":brief,"source_memory":result["source_memory"],"as_of":"2025-02-01"})
        self.assertIsNone(second["recovery"])
        self.assertEqual(second["citations"],result["citations"])
        self.assertEqual(agent.remembered_sources(result["source_memory"],"2024-12-31"),{})

    def test_versions_are_immutable_and_as_of_search_uses_eligible_revision(self):
        write_dataset(self.directory)
        self.store.datasets.import_directory(self.directory)
        self.assertEqual(self.store.datasets.import_directory(self.directory)["status"],"already imported")
        write_dataset(self.directory,value=99)
        with self.assertRaisesRegex(ValueError,"immutable"):
            self.store.datasets.import_directory(self.directory)
        write_dataset(self.directory,version="v2",available="2025-06-01",value=99)
        self.store.datasets.import_directory(self.directory)
        earlier=self.store.datasets.search("groundwater","2025-05-01")["matches"][0]
        later=self.store.datasets.search("groundwater","2025-07-01")["matches"][0]
        self.assertEqual(earlier["version"],"v1")
        self.assertEqual(earlier["record"]["facts"]["sensor_zeta"]["reading"],17)
        self.assertEqual(later["version"],"v2")
        self.assertEqual(later["record"]["facts"]["sensor_zeta"]["reading"],99)
        # Rebuilding the generated quote corpus must not erase separately ingested sources.
        self.store.ingest()
        self.assertEqual(self.store.datasets.get("unanticipated-source","v1","R1")["facts"]["sensor_zeta"]["reading"],17)


if __name__=="__main__":
    unittest.main()
