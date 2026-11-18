import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from earthworks.context import PublicContext
from earthworks.corpus import ROOT, cents
from earthworks.store import Store


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=PublicContext()

    def test_snapshot_coverage_units_and_source_references(self):
        weather=self.context.data["weather"]
        self.assertEqual(len(weather["locations"]),10)
        self.assertEqual(len(weather["cells"]),5)
        for cell in weather["cells"]:
            self.assertEqual(len(cell["time"]),2192)
            self.assertEqual((cell["time"][0],cell["time"][-1]),("2020-01-01","2025-12-31"))
            self.assertTrue(all(value is not None and value>=0 for value in cell["precipitation_mm"]))
        self.assertEqual(self.context.diesel("2026-01-01")["status"],"not imported")
        self.assertEqual(self.context.soil("Brendale")["status"],"not imported")

    def test_weather_union_weekends_recovery_and_missing_coverage(self):
        start=date(2025,1,6) # Monday
        series={str(start+timedelta(days=i)):0 for i in range(-2,8)}
        series["2025-01-05"]=15 # Sunday affects Monday recovery
        series["2025-01-06"]=12 # Monday rain must not also count as recovery
        exposure=self.context.exposure(series,start,5,10,1,4,8)
        self.assertEqual(exposure["rain_threshold_weekdays"],1)
        self.assertEqual(exposure["additional_recovery_weekdays"],1)
        self.assertEqual(exposure["affected_dates"],["2025-01-06","2025-01-07"])
        self.assertEqual(exposure["modelled_lost_day_equivalents"],1)
        self.assertIsNone(exposure["actual_lost_workdays"])
        zero=self.context.exposure(series,start,5,10,1,0,8)
        self.assertEqual(zero["potentially_affected_weekdays"],2)
        self.assertEqual(zero["modelled_lost_day_equivalents"],0)
        series["2025-01-07"]=None
        missing=self.context.exposure(series,start,5,10,1,4,8)
        self.assertFalse(missing["complete"])
        self.assertIn("2025-01-07",missing["missing_dates"])

    def test_analogue_windows_respect_time_and_do_not_claim_observed_loss(self):
        weather=self.context.weather("Brendale","2025-07-01","2025-06-01")
        self.assertTrue(weather["historical_windows"])
        self.assertTrue(all(w["end"]<"2025-06-01" and w["start"][:4]<"2025" for w in weather["historical_windows"]))
        self.assertIsNone(weather["actual_lost_workdays"])
        self.assertIsNone(weather["price_adjustment_cents"])
        self.assertTrue(weather["snapshot_retrieved_after_estimate_date"])
        with self.assertRaises(ValueError):
            self.context.weather("Brendale","2026-01-01","2026-01-01",lost_hours=9)
        with self.assertRaises(ValueError):
            self.context.weather("Brendale","2026-01-01","2026-01-01",working_days=2.5)

    def test_diesel_prior_observation_gst_and_separate_cost_scenarios(self):
        # Invented test observations exercise the optional adapter without
        # redistributing a third-party fuel-price extract.
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        directory=Path(temporary.name)
        pack={"source_id":"TEST-DIESEL","provider":"Synthetic test fixture","source_url":"https://example.test/fuel","retrieved_at":"2026-01-01","publication_date":"2026-01-01","source_sha256":"0"*64,"units":"cents/litre including GST","limitations":["Synthetic fixture"],"records":[{"date":"2025-01-01","cents_per_litre_inc_gst":165,"source_cell":"fixture:A1"},{"date":"2025-06-06","cents_per_litre_inc_gst":176,"source_cell":"fixture:A2"}]}
        (directory/"diesel.json").write_text(json.dumps(pack))
        context=PublicContext(directory);context.data["weather"]=self.context.data["weather"];context.weather_cells=self.context.weather_cells
        diesel=context.diesel("2025-06-08","2025-01-01")
        current=diesel["current"]
        self.assertLessEqual(current["date"],"2025-06-08")
        self.assertAlmostEqual(current["aud_per_litre_ex_gst"],current["cents_per_litre_inc_gst"]/110,places=4)
        self.assertTrue(diesel["snapshot_published_after_requested_date"])
        self.assertIsNone(context.diesel("2019-01-01")["current"])
        values={"as_of":"2026-01-01","suburb":"Brendale","planned_start_date":"2026-02-01","fuel_litres":1000,"reference_date":"2025-01-01","standby_cost_per_day_ex_gst":1800,"lost_hours":.5}
        result=context.scenario(values)
        costs=result["cost_scenarios"]
        delta=(Decimal(str(result["diesel"]["current"]["cents_per_litre_inc_gst"]))-Decimal(str(result["diesel"]["reference"]["cents_per_litre_inc_gst"])))/Decimal("1.1")
        self.assertEqual(costs["diesel_change_cents"],cents(1000,delta))
        amounts=[cents(Decimal(w["potentially_affected_weekdays"])/16,180000) for w in result["weather"]["historical_windows"]]
        self.assertEqual(costs["weather_cost_cents"]["low"],min(amounts))
        self.assertEqual(costs["weather_cost_cents"]["high"],max(amounts))
        self.assertFalse(costs["included_in_estimate"])

    def test_normalised_public_tables_edges_and_idempotent_indexing(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/"context.sqlite",database_url="")
            try:
                store.ingest()
                result=store.ingest_public_context()
                self.assertEqual(result["weather_days"],10960)
                self.assertEqual(result["diesel_prices"],0)
                self.assertEqual(result["soil_screenings"],0)
                self.assertEqual(result["public_context_edges"],300)
                public=[e for e in store.graph("P001") if e.get("source_kind")=="public"]
                self.assertEqual(len(public),1)
                self.assertTrue(all(e["source_url"].startswith("https://") for e in public))
                self.assertEqual(store.ingest_public_context()["status"],"current snapshot already indexed")
            finally:
                store.close()
