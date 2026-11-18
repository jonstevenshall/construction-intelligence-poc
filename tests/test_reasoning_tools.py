import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from earthworks.budget import Budget,BudgetError,model_response
from earthworks.corpus import cents,load
from earthworks.reasoning_tools import arithmetic,calculate_quantities,estimate_costs,lookup_public_information


def priced_line(**changes):
    row={"description":"Indicative excavation","unit":"m³","quantity_low":3500,"quantity_high":7000,
        "rate_low_cents":2000,"rate_high_cents":3000,"low_rate_source":None,"high_rate_source":None,
        "assumption":"Working geometric scenarios; provisional model rate allowance"}
    return {**row,**changes}


class ReasoningToolTests(unittest.TestCase):
    def test_general_geometry_and_alternative_assumptions(self):
        self.assertEqual(arithmetic("100*20"),2000)
        self.assertEqual(arithmetic("200*10"),2000)
        self.assertEqual(arithmetic("100*20*(2+5)/4"),3500)
        self.assertEqual(arithmetic("100*20*(2+5)/2"),7000)
        self.assertEqual(arithmetic("sqrt(81)+abs(-3)"),12)
        result=calculate_quantities({"calculations":[{"label":"Provisional wedge cut","expression":"100*20*(2+5)/4","unit":"m³","assumption":"Linear slope, cutting to an assumed common low-edge plane"}]})
        self.assertEqual(result["calculations"][0]["value"],3500)
        self.assertIn("assumed",result["calculations"][0]["assumption"])

    def test_calculator_cannot_execute_code_or_unbounded_powers(self):
        for expression in ["__import__('os').getcwd()","(1).__class__","2**999999","1/0","[1,2,3]","open('test')","1+"]:
            with self.subTest(expression=expression),self.assertRaises(ValueError):
                arithmetic(expression)

    def test_component_range_and_signed_adjustment_reconcile(self):
        args={"title":"Groundworks allowance","lines":[priced_line(),priced_line(description="Credit",quantity_low=10,quantity_high=20,rate_low_cents=-200,rate_high_cents=-100)],
            "confidence":"low","confidence_reason":"Geometry and rates are provisional","unpriced_items":["Tree clearing"]}
        estimate,sources=estimate_costs(args,[],"2026-11-16")
        self.assertEqual(estimate["low_cents"],3500*2000-4000)
        self.assertEqual(estimate["high_cents"],7000*3000-1000)
        self.assertEqual(estimate["low_cents"],sum(l["low_cents"] for l in estimate["lines"]))
        self.assertEqual(estimate["high_cents"],sum(l["high_cents"] for l in estimate["lines"]))
        self.assertEqual(estimate["lines"][0]["low_basis"],"assumption")
        self.assertEqual(sources,{})

    def test_specific_source_rate_is_not_replaced_by_model_evaluation(self):
        quote=next(q for q in load()["quotes"] if q["scenario_pattern"]=="complete")
        line=next(l for l in quote["lines"] if l["scope_item_id"]=="MB02")
        ref=quote["id"]+":MB02"
        args={"title":"Referenced source","lines":[priced_line(quantity_low=10,quantity_high=20,rate_low_cents=1,rate_high_cents=2,low_rate_source=ref,high_rate_source=ref)],
            "confidence":"moderate","confidence_reason":"Known rate; quantities provisional","unpriced_items":[]}
        estimate,sources=estimate_costs(args,[quote],"2026-11-16")
        self.assertEqual(estimate["lines"][0]["rate_low_cents"],line["rate_cents"])
        self.assertEqual(estimate["lines"][0]["rate_high_cents"],line["rate_cents"])
        self.assertEqual(estimate["low_cents"],cents(10,line["rate_cents"]))
        self.assertEqual(len(estimate["source_conflicts"]),2)
        self.assertEqual(sources[ref]["line"],line["evidence"]["line"])
        self.assertEqual(line["rate_cents"],next(l for l in quote["lines"] if l["scope_item_id"]=="MB02")["rate_cents"])

    def test_live_lookup_preserves_returned_facts_instead_of_static_answers(self):
        calls=[]
        def provider(payload,budget):
            calls.append(payload)
            return {"output":[{"type":"web_search_call"},{"type":"message","content":[{"type":"output_text","text":"A changed date supplied by the source fixture.","annotations":[{"type":"url_citation","url":"https://example.test/published-record","title":"Original published record"}]}]}]}
        result,sources=lookup_public_information({"query":"Find the currently published dates for this event"},provider,None)
        self.assertEqual(calls[0]["tools"][0]["type"],"web_search")
        self.assertEqual(calls[0]["max_tool_calls"],1)
        self.assertEqual(result["answer"],"A changed date supplied by the source fixture.")
        self.assertEqual(len(sources),1)
        self.assertEqual(next(iter(sources.values()))["url"],"https://example.test/published-record")

    def test_web_search_fee_and_content_are_inside_the_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=Budget(Path(directory)/"search.sqlite",lifetime_usd=.005,daily_usd=.005)
            with patch.dict(os.environ,{"LLM_ENABLED":"true","OPENAI_MODEL":"gpt-6-luna","OPENAI_API_KEY":"offline-unit-test"}),patch("urllib.request.urlopen") as request:
                with self.assertRaises(BudgetError):
                    model_response({"input":"Lookup","tools":[{"type":"web_search"}],"max_tool_calls":1},budget)
                request.assert_not_called()
            self.assertEqual(budget.status()["calls"],0)
            budget=Budget(Path(directory)/"fee.sqlite",lifetime_usd=1,daily_usd=1)
            identity=budget.reserve("gpt-6-luna",128000,1800,web_calls_upper=1)
            self.assertGreaterEqual(budget.status()["charged_or_reserved_usd"],.01+.0128)
            budget.settle(identity,100,50,web_calls=1)
            self.assertEqual(budget.status()["charged_or_reserved_usd"],.010035)
