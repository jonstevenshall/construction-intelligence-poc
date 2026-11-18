import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from earthworks.agent import ReviewAgent, scope_findings
from earthworks.budget import Budget, BudgetError, explain_with_model
from earthworks.corpus import ROOT, calendar_context, cents, generate, gst, load
from earthworks.evaluate import evaluate, expected
from earthworks.store import Store, embed
from datetime import date


class LabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/"data"/"manifest.json").exists():
            generate()
        cls.data=load()
        cls.temp=tempfile.TemporaryDirectory()
        cls.store=Store(Path(cls.temp.name)/"test.sqlite",database_url="")
        cls.store.ingest()
        cls.agent=ReviewAgent(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.temp.cleanup()

    def test_exact_scale_and_year_coverage(self):
        self.assertEqual([len(self.data[k]) for k in ["projects","quotes","vendors"]],[300,1000,50])
        self.assertEqual({p["tender_date"][:7] for p in self.data["projects"]},{f"2025-{m:02}" for m in range(1,13)})
        counts=[sum(q["project_id"]==p["id"] for q in self.data["quotes"]) for p in self.data["projects"]]
        self.assertEqual(counts.count(4),100)
        self.assertEqual(counts.count(3),200)
        self.assertEqual(len({q["vendor_id"] for q in self.data["quotes"]}),50)

    def test_all_money_and_inclusion_invariants(self):
        for q in self.data["quotes"]:
            submitted=sum(l["amount_cents"] for l in q["lines"] if l["status"] in ["priced","provisional"])
            options=sum(l["amount_cents"] for l in q["lines"] if l["status"]=="optional")
            self.assertEqual(q["contract_ex_gst_cents"],submitted,q["id"])
            self.assertEqual(q["optional_ex_gst_cents"],options)
            self.assertEqual(q["gst_cents"],gst(submitted))
            self.assertEqual(q["deposit_cents"],cents(q["deposit_percent"]/100,q["contract_inc_gst_cents"]))
            self.assertEqual(q["submitted_total_cents"],q["contract_inc_gst_cents"] if q["display_tax_basis"]=="inclusive" else submitted)
            for line in q["lines"]:
                if line["status"] in ["priced","provisional","optional"]:
                    self.assertEqual(line["amount_cents"],cents(line["quantity"],line["rate_cents"]))
                else:
                    self.assertEqual(line["amount_cents"],0)
                if line["status"]=="included_elsewhere":
                    self.assertIsNone(line["rate_cents"])
                    self.assertTrue(line["included_in_line_id"])
                if line["status"]=="rate_only":
                    self.assertIsNone(line["quantity"])

    def test_document_hashes_and_line_references(self):
        for q in self.data["quotes"]:
            path=ROOT/"data"/q["document_path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),q["document_sha256"])
            lines=path.read_text().splitlines()
            for line in q["lines"]:
                self.assertTrue(lines[line["evidence"]["line"]-1].startswith(line["scope_item_id"]+" |"))
            for term,ref in zip(q["terms"],q["terms_evidence"]):
                self.assertEqual(lines[ref["line"]-1],"- "+term)

    def test_all_deliberate_variations_exist(self):
        patterns={q["scenario_pattern"] for q in self.data["quotes"]}
        self.assertEqual(len(patterns),10)
        self.assertTrue(any(q["deposit_percent"]==50 for q in self.data["quotes"]))
        self.assertTrue(any(q["year_end_offer"] for q in self.data["quotes"]))
        self.assertTrue(any(q["supplier_shutdown"] for q in self.data["quotes"]))
        self.assertTrue(any(min(self.agent.package(p["id"])["quotes"],key=lambda q:q["contract_ex_gst_cents"])["findings"] for p in self.data["projects"][:20]))

    def test_date_context_and_no_fabricated_public_weather(self):
        self.assertEqual(calendar_context(date(2025,6,30))["days_to_financial_year_end"],0)
        self.assertEqual(calendar_context(date(2025,7,1))["days_to_financial_year_end"],364)
        self.assertEqual(calendar_context(date(2025,12,31))["days_to_calendar_year_end"],0)
        for p in self.data["projects"]:
            self.assertIsNone(p["weather_context"]["work_period_observations"])
            self.assertTrue(all(value is None for value in p["public_context"].values()))
            self.assertFalse(p["spoil_haul"]["observed"])

    def test_database_relations_and_vector_filters(self):
        counts=self.store.counts()
        self.assertEqual(counts["quote_lines"],21000)
        self.assertEqual(counts["context_edges"],45000)
        results=self.store.search("dewatering and wet weather",project_id="P001")
        self.assertTrue(results)
        allowed={q["id"] for q in self.data["quotes"] if q["project_id"]=="P001"}
        self.assertTrue(all(r["quote_id"] in allowed for r in results))
        self.assertFalse(self.store.search("deposit",as_of="2024-12-31"))
        self.assertTrue(all(edge["src"]=="P001" for edge in self.store.graph("P001")))

    def test_estimate_never_uses_future_quotes(self):
        inputs={"disturbed_area_m2":20000,"depth_m":.3,"rock_fraction":.1,"spoil_haul_km":30,"fill_haul_km":20,"mobilisation_km":20,"as_of":"2025-06-01"}
        result=self.agent.estimate(inputs)
        self.assertTrue(all(c["date"]<inputs["as_of"] for c in result["comparables"]))
        for field in ["low_cents","central_cents","high_cents"]:
            self.assertEqual(result["totals_ex_gst"][field],sum(line[field] for line in result["breakdown"]))
        self.assertLessEqual(result["totals_ex_gst"]["low_cents"],result["totals_ex_gst"]["central_cents"])
        self.assertLessEqual(result["totals_ex_gst"]["central_cents"],result["totals_ex_gst"]["high_cents"])
        inputs["as_of"]="2024-12-31"
        self.assertEqual(self.agent.estimate(inputs)["mode"],"insufficient evidence")

    def test_invalid_estimate_and_missing_inputs(self):
        self.assertEqual(self.agent.estimate({})["mode"],"scripted clarification")
        with self.assertRaises(ValueError):
            self.agent.estimate({"disturbed_area_m2":float("nan"),"depth_m":.3,"rock_fraction":.1,"spoil_haul_km":30,"fill_haul_km":20,"mobilisation_km":20,"as_of":"2026-01-01"})

    def test_question_selection_and_answer_narrows_envelope(self):
        inputs={"disturbed_area_m2":20000,"as_of":"2026-01-01"}
        plan=self.agent.plan_questions(inputs)
        self.assertEqual(plan["scenario_count"],8)
        scores=[q["illustrative_range_reduction_cents"] for q in plan["questions"]]
        self.assertEqual(scores,sorted(scores,reverse=True))
        best=plan["questions"][0]
        inputs[best["field"]]=best["alternatives"][0]["value"]
        updated=self.agent.plan_questions(inputs)
        self.assertLess(updated["width_cents"],plan["width_cents"])
        self.assertEqual(len(updated["questions"]),2)

    def test_evaluation_counts_material_omissions(self):
        quote=next(q for q in self.data["quotes"] if q["scenario_pattern"]=="drainage_excluded")
        observed=expected(quote)
        report=evaluate([observed],self.data["quotes"])
        self.assertEqual(report["numeric_fields_correct"],4)
        observed["flags"]=[]
        report=evaluate([observed],self.data["quotes"])
        self.assertGreater(report["material_false_negatives"],0)
        with self.assertRaises(ValueError):
            evaluate([observed,observed],self.data["quotes"])

    def test_budget_is_persistent_atomic_and_fail_closed(self):
        path=Path(self.temp.name)/"budget.sqlite"
        budget=Budget(path,lifetime_usd=.001,daily_usd=.001)
        def reserve():
            try:
                budget.reserve("gpt-6-luna",1000,1000)
                return True
            except BudgetError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            accepted=list(pool.map(lambda _:reserve(),range(4)))
        self.assertEqual(sum(accepted),1)
        self.assertEqual(Budget(path,lifetime_usd=.001,daily_usd=.001).status()["calls"],1)
        with self.assertRaises(BudgetError):
            budget.reserve("gpt-6-astra",1,1)
        with patch.dict(os.environ,{"LLM_ENABLED":"false"}), patch("urllib.request.urlopen") as request:
            self.assertIsNone(explain_with_model({},budget))
            request.assert_not_called()


if __name__=="__main__":
    unittest.main()
