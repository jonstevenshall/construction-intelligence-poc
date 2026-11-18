"""Real PostgreSQL/pgvector check, run by CI."""
import os
import unittest

from earthworks.agent import ReviewAgent
from earthworks.store import Store
from earthworks.corpus import ROOT
from earthworks.data_workbench import DataWorkbench


@unittest.skipUnless(os.getenv("LAB_TEST_DATABASE_URL"),"PostgreSQL integration URL not configured; SQLite checks run separately")
class PostgresTests(unittest.TestCase):
    def test_real_pgvector_ingestion_filtering_and_calculation(self):
        store=Store(database_url=os.environ["LAB_TEST_DATABASE_URL"])
        try:
            result=store.ingest()
            self.assertEqual(result["backend"],"postgres-pgvector")
            self.assertEqual(store.counts(),{"projects":300,"vendors":50,"quotes":1000,"quote_lines":21000,"chunks":7000,"context_edges":45000})
            hits=store.search("deposit payable before mobilisation",project_id="P001")
            self.assertTrue(hits)
            quote_ids={q["id"] for q in store.records("quotes") if q["project_id"]=="P001"}
            self.assertTrue(all(hit["quote_id"] in quote_ids for hit in hits))
            self.assertFalse(store.search("deposit",as_of="2024-12-31"))
            self.assertEqual(len(store.graph("P001")),4)
            agent=ReviewAgent(store)
            review=agent.ask("deposits upfront cash","P001")
            self.assertEqual(len(review["facts"]),4)
            plan=agent.plan_questions({"disturbed_area_m2":20000,"as_of":"2026-01-01"})
            self.assertEqual(plan["scenario_count"],8)
            self.assertGreater(plan["width_cents"],0)
            public=store.ingest_public_context()
            self.assertEqual(public["weather_days"],10960)
            self.assertEqual(public["diesel_prices"],0)
            self.assertEqual(public["soil_screenings"],0)
            self.assertEqual(public["public_context_edges"],300)
            self.assertEqual(len(store.graph("P001")),5)
            added=store.datasets.import_directory(ROOT/"data"/"datasets"/"site-access-demo")
            self.assertEqual(added["records"],2)
            found=store.datasets.search("gate access","2026-01-01",entity_id="P001")
            self.assertEqual(len(found["matches"]),1)
            self.assertEqual(found["matches"][0]["record"]["facts"]["gate_width_m"],2.8)
            self.assertFalse(store.datasets.search("gate access","2024-12-31")["matches"])
            workbench=DataWorkbench(store)
            payload={"filename":"pg-observation.jsonl","content":'{"id":"PG1","note":"Restricted delivery window","entity":"P001","hours":4}\n',
                "metadata":{"id":"pg-ingestion-check","version":"v1","name":"PostgreSQL ingestion check","record_type":"Access observation","objective":"Check imported delivery evidence","data_kind":"synthetic","available_date":"2025-01-01"},
                "mapping":{"id":"id","text":"note","entities":"entity"}}
            preview=workbench.preview(payload)
            imported=workbench.commit({**payload,"preview_digest":preview["preview_digest"]})
            self.assertEqual(imported["records"],1)
            self.assertEqual(workbench.source("pg-ingestion-check","v1")["content"],payload["content"])
            self.assertTrue(any(e["src"]=="DATA:pg-ingestion-check:v1:PG1" for e in store.graph("P001")))
            self.assertEqual(store.datasets.search("delivery window","2026-01-01",dataset_id="pg-ingestion-check")["matches"][0]["record"]["facts"]["hours"],4)
        finally:
            store.close()


if __name__=="__main__":
    unittest.main()
