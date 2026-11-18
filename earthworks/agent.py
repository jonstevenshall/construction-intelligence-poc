"""Deterministic review/clarification baseline, with optional budgeted AI explanation."""
import math
from itertools import product
from datetime import date
from statistics import median

from .corpus import SCOPE, cents, gst, rounded
from .context import PublicContext

QUANTITY_RULES = {
    "MB01":"Disturbed area × 50%", "MB02":"Disturbed area × excavation depth × 50%",
    "MB03":"Square root of disturbed area × 1.5", "MB04":"Disturbed area × 50% × 0.12 m base thickness",
    "MB05":"Disturbed area × 50%", "MB06":"Smaller of 1,200 m² and disturbed area × 8%",
    "IL01":"Disturbed area × 25%", "IL02":"Disturbed area × excavation depth × 25%",
    "IL03":"Disturbed area × 25% × 0.12 m base thickness", "IL04":"Square root of disturbed area",
    "IL05":"Disturbed area × 25%", "CP01":"Disturbed area × 25%",
    "CP02":"Disturbed area × 25% × 0.18 m base thickness", "CP03":"Disturbed area × excavation depth × 12%",
    "CP04":"Square root of disturbed area × 1.2", "EX01":"Disturbed area × excavation depth × 35% export assumption",
    "EX02":"Disturbed area × excavation depth × 15% import assumption", "EX03":"Disturbed area × excavation depth × rock fraction",
    "EX04":"Entire disturbed area", "EX05":"Excavation volume ÷ 1,500 m³/day, rounded up; at least 3 days",
    "MO01":"One mobilisation and demobilisation item"
}


def money(value):
    return f"AUD {value/100:,.2f}"


def scope_findings(quote):
    flags=[]
    for line in quote["lines"]:
        if line["status"] in ["excluded","optional","rate_only","provisional"]:
            flags.append({"kind":line["status"],"item":line["description"],"scope_item_id":line["scope_item_id"],"evidence":line["evidence"]})
        if line["quantity"] is not None and line["status"] not in ["excluded","rate_only"] and line["unit"]!="item" and line["quantity"]!=line["required_quantity"]:
            flags.append({"kind":"quantity_departure","item":line["description"],"scope_item_id":line["scope_item_id"],"evidence":line["evidence"]})
    if quote["scenario_pattern"]=="wet_weather_excluded":
        index=next(i for i,t in enumerate(quote["terms"]) if "wet-weather standby" in t)
        flags.append({"kind":"wet_weather_excluded","item":quote["terms"][index],"evidence":quote["terms_evidence"][index]})
    if not quote["unit_price_allocation_available"]:
        flags.append({"kind":"unallocated_lump_sum","item":"Included lines are not zero-cost; the supplier did not allocate individual rates.","evidence":quote["lines"][0]["evidence"]})
    return flags


class ReviewAgent:
    def __init__(self,store):
        self.store=store
        self.projects={p["id"]:p for p in store.records("projects")}
        self.quotes=store.records("quotes")
        self.vendors=store.records("vendors")
        self.context=PublicContext()

    def package(self,project_id):
        if project_id not in self.projects:
            raise ValueError("Unknown project")
        return {"project":self.projects[project_id],"quotes":[{**q,"findings":scope_findings(q)} for q in self.quotes if q["project_id"]==project_id],
                "public_context":self.context.for_project(self.projects[project_id])}

    def ask(self,question,project_id):
        package=self.package(project_id)
        quotes=package["quotes"]
        question=question.strip()[:2000]
        if not question:
            raise ValueError("Ask a question")
        text=question.lower()
        evidence=self.store.search(question,project_id,limit=3)
        facts=[]
        followups=[]
        if any(w in text for w in ["deposit","upfront","cash","advance"]):
            for q in quotes:
                facts.append({"quote_id":q["id"],"vendor":q["vendor_name"],"deposit_percent":q["deposit_percent"],"deposit_cents":q["deposit_cents"],
                    "contract_inc_gst_cents":q["contract_inc_gst_cents"],"basis":q["deposit_basis"],"source":q["terms_evidence"][0]})
            spread=max(q["deposit_cents"] for q in quotes)-min(q["deposit_cents"] for q in quotes)
            answer=f"Upfront cash ranges from {money(min(q['deposit_cents'] for q in quotes))} to {money(max(q['deposit_cents'] for q in quotes))}: a spread of {money(spread)}. Each deposit is calculated against that supplier's own GST-inclusive contract sum, excluding options. A larger deposit is greater cash exposure, not evidence that a supplier will fail."
            followups=["What advance-payment protection and payment milestones would you require?"]
        elif any(w in text for w in ["haul","distance","depot","travel","mobilis","mobiliz"]):
            for q in quotes:
                facts.append({"quote_id":q["id"],"vendor":q["vendor_name"],"depot_to_site":q["mobilisation_distance"],"spoil_haul":package["project"]["spoil_haul"],"fill_haul":package["project"]["fill_haul"]})
            answer="Depot-to-site distance affects plant mobilisation. Spoil haulage is site-to-disposal; imported fill travels source-to-site. They are separate legs. All distances here are simulated road proxies, not measured routes or approved heavy-vehicle access."
            followups=["Which disposal facility accepts the material, and which truck configuration and route are permitted?"]
        elif any(w in text for w in ["diesel","fuel"]):
            context=package["public_context"]["diesel"]
            facts.append({"diesel_context":context})
            point=context.get("current")
            answer=(f"AIP's Brisbane wholesale diesel observation on {point['date']} is {point['cents_per_litre_inc_gst']:.2f} cents/litre including GST. " if point else "No eligible diesel observation is available. ")+"This is fuel-price context, not the supplier's delivered cost. We do not know fuel consumption, so no adjustment to the bid total is justified. A later-downloaded historical series is retrospective context, not proof of what the bidder knew."
            followups=["How many litres are allowed, and is a fuel surcharge already included in the quote?"]
        elif any(w in text for w in ["soil","ground screening","clay"]):
            context=package["public_context"]["soil"]
            facts.append({"soil_screening":context})
            answer=f"The public soil screening is for {package['project']['suburb']}'s centre, not the fictional site. Mapped soil order: {context.get('soil_order') or 'not available'}; mapped topsoil clay: {context.get('mapped_clay_percent_0_30cm','not available')}%. This does not establish excavatable rock, contamination, bearing capacity or a dewatering price."
            followups=["Is there a site-specific geotechnical report and a confirmed spoil classification?"]
        elif any(w in text for w in ["year","season","weather","rain","eofy","eoty","shutdown"]):
            for q in quotes:
                facts.append({"quote_id":q["id"],"year_end_offer":q["year_end_offer"],"shutdown":q["supplier_shutdown"],"weather_exclusion":q["scenario_pattern"]=="wet_weather_excluded","sources":q["terms_evidence"]})
            facts.append({"quote_calendar":package["project"]["quote_calendar"],"work_calendar":package["project"]["work_calendar"],"weather_context":package["project"]["weather_context"]})
            public_weather=package["public_context"]["weather"]
            facts.append({"public_weather":public_weather})
            summary=public_weather.get("seasonal_summary")
            answer="Calendar-year end and 30 June financial-year end are separate features. Stated year-end adjustments are already in the quoted rates. "
            if summary:
                assumptions=public_weather["assumptions"]
                answer+=f"Across {summary['historical_windows']} earlier regional weather windows, {summary['min_affected_weekdays']}–{summary['max_affected_weekdays']} of {assumptions['working_days']} scheduled weekdays were potentially affected under a {assumptions['rain_threshold_mm']} mm threshold and {assumptions['recovery_calendar_days']} assumed recovery day(s). These are ERA5-based exposure scenarios, not recorded lost workdays. Standby/dewatering costs remain unpriced."
            else:
                answer+="No eligible historical weather windows support this work period; no lost-day estimate is justified."
            followups=["What is the planned work window, and who bears wet-weather standby and dewatering costs?"]
        else:
            cheapest=min(quotes,key=lambda q:q["contract_ex_gst_cents"])
            for q in quotes:
                facts.append({"quote_id":q["id"],"vendor":q["vendor_name"],"contract_ex_gst_cents":q["contract_ex_gst_cents"],"optional_ex_gst_cents":q["optional_ex_gst_cents"],"findings":q["findings"],"source":q["document_path"]})
            answer=f"{cheapest['id']} has the lowest submitted price on an ex-GST basis ({money(cheapest['contract_ex_gst_cents'])}). That is not a recommendation: compare scope findings, allowances, quantities and payment terms before selecting a supplier. Priced options are kept separate; exclusions and rate-only items do not have a known total cost."
            followups=["Are all four work zones required, and are the rock quantity and spoil classification confirmed?"]
        return {"mode":"scripted review baseline — no live model","question":question,"answer":answer,"facts":facts,"followup_questions":followups,
                "evidence":evidence,"retrieval":"local lexical vectors; not neural semantic retrieval","synthetic":True}

    def estimate(self,inputs,include_evidence=True):
        """A transparent scenario calculator; NOT a validated market estimator."""
        required=[("disturbed_area_m2","What area will actually be disturbed (m²), rather than the whole property acreage?"),
                  ("depth_m","What average excavation depth should we assume (metres)?"),
                  ("rock_fraction","What fraction of excavated volume is rock, or what does the geotechnical report say?"),
                  ("spoil_haul_km","How far is the proposed disposal destination from the site (one-way kilometres)?"),
                  ("fill_haul_km","How far is the fill source from the site (one-way kilometres)?"),
                  ("mobilisation_km","What depot-to-site mobilisation distance should we use?"),
                  ("as_of","As of what date should historical quotes be available?")]
        missing=[{"field":key,"question":question} for key,question in required if inputs.get(key) in [None,""]]
        if missing:
            return {"mode":"scripted clarification","questions":missing,"synthetic":True}
        values={}
        for key,upper in [("disturbed_area_m2",200000),("depth_m",3),("rock_fraction",1),("spoil_haul_km",300),("fill_haul_km",300),("mobilisation_km",300)]:
            try:
                value=float(inputs[key])
            except (ValueError,TypeError):
                raise ValueError(f"{key} must be a number")
            if not math.isfinite(value) or value<0 or value>upper or (key in ["disturbed_area_m2","depth_m"] and value==0):
                raise ValueError(f"{key} must be within the supported demonstration range")
            values[key]=value
        as_of=date.fromisoformat(str(inputs["as_of"]))
        area=values["disturbed_area_m2"]
        depth=values["depth_m"]
        volume=area*depth
        quantities=[area*.5,volume*.5,math.sqrt(area)*1.5,area*.5*.12,area*.5,min(1200,area*.08),
             area*.25,volume*.25,area*.25*.12,math.sqrt(area),area*.25,area*.25,area*.25*.18,volume*.12,
             math.sqrt(area)*1.2,volume*.35,volume*.15,volume*values["rock_fraction"],area,max(3,math.ceil(volume/1500)),1]
        # One full-scope quote per historical project; never use future tenders or an unallocated lump sum.
        eligible={}
        for q in self.quotes:
            if q["scenario_pattern"]=="complete" and date.fromisoformat(q["quote_date"])<as_of:
                eligible.setdefault(q["project_id"],q)
        ranked=sorted(eligible.values(),key=lambda q:abs(math.log(self.projects[q["project_id"]]["disturbed_area_m2"]/area)))[:12]
        if len(ranked)<3:
            return {"mode":"insufficient evidence","message":"At least three earlier synthetic projects are required; no estimate returned.","synthetic":True}
        breakdown=[]
        for index,spec in enumerate(SCOPE):
            code,zone,description,unit,_=spec
            rates=[]
            rate_evidence=[]
            for q in ranked:
                line=next(l for l in q["lines"] if l["scope_item_id"]==code)
                rate=line["rate_cents"]
                # Explicit scenario coefficients, identical to the generator. Not empirically learned.
                p=self.projects[q["project_id"]]
                adjustments=[]
                old_rate=rate
                if code=="EX01":
                    delta=cents(values["spoil_haul_km"],45)-cents(p["spoil_haul"]["estimated_road_km"],45)
                    adjustments.append({"reason":"Replace the source spoil-haul assumption","source_km":p["spoil_haul"]["estimated_road_km"],"target_km":values["spoil_haul_km"],"coefficient_cents":45,"coefficient_unit":"per m³ per km","delta_cents":delta,"basis":"Invented simulation coefficient, not an observed commercial adjustment"})
                    rate+=delta
                if code=="EX02":
                    delta=cents(values["fill_haul_km"],35)-cents(p["fill_haul"]["estimated_road_km"],35)
                    adjustments.append({"reason":"Replace the source fill-delivery assumption","source_km":p["fill_haul"]["estimated_road_km"],"target_km":values["fill_haul_km"],"coefficient_cents":35,"coefficient_unit":"per m³ per km","delta_cents":delta,"basis":"Invented simulation coefficient, not an observed commercial adjustment"})
                    rate+=delta
                if code=="MO01":
                    delta=cents(values["mobilisation_km"],3500)-cents(q["mobilisation_distance"]["estimated_road_km"],3500)
                    adjustments.append({"reason":"Replace the source depot-to-site assumption","source_km":q["mobilisation_distance"]["estimated_road_km"],"target_km":values["mobilisation_km"],"coefficient_cents":3500,"coefficient_unit":"per mobilisation item per km","delta_cents":delta,"basis":"Invented simulation coefficient, not an observed commercial adjustment"})
                    rate+=delta
                if rate<0:
                    adjustments.append({"reason":"Floor the adjusted rate at zero","delta_cents":-rate,"basis":"Calculation guard, not a supplier concession"})
                rate=max(0,rate)
                rates.append(rate)
                if include_evidence:
                    rate_evidence.append({"quote_id":q["id"],"project_id":q["project_id"],"vendor_id":q["vendor_id"],"vendor_name":q["vendor_name"],
                        "quoted_rate_cents":old_rate,"adjustment_cents":rate-old_rate,"adjusted_rate_cents":rate,
                        "quoted_quantity":line["quantity"],"unit":line["unit"],"adjustments":adjustments,
                        "evidence":line["evidence"],"document_sha256":q["document_sha256"]})
            qty=rounded(quantities[index])
            low,mid,high=min(rates),int(median(rates)),max(rates)
            breakdown.append({"scope_item_id":code,"zone":zone,"description":description,"quantity":qty,"unit":unit,
                "low_cents":cents(qty,low),"central_cents":cents(qty,mid),"high_cents":cents(qty,high),
                "rate_low_cents":low,"rate_central_cents":mid,"rate_high_cents":high})
            if include_evidence:
                ordered=sorted(rate_evidence,key=lambda r:r["adjusted_rate_cents"])
                median_ids={ordered[(len(ordered)-1)//2]["quote_id"],ordered[len(ordered)//2]["quote_id"]}
                for evidence in rate_evidence:
                    evidence["roles"]=(["lowest rate"] if evidence["adjusted_rate_cents"]==low else [])+(["median input"] if evidence["quote_id"] in median_ids else [])+(["highest rate"] if evidence["adjusted_rate_cents"]==high else [])
                breakdown[-1].update(quantity_basis={"type":"demonstration quantity rule","formula":QUANTITY_RULES[code],"quantity":qty,"unit":unit,"note":"Calculated from user inputs and fixed ratios; not measured from drawings or extracted from a source quote."},
                    aggregation={"method":"Minimum / median / maximum of adjusted ex-GST unit rates; median is truncated to whole cents before multiplication.","sample_count":len(rates)},rate_evidence=rate_evidence)
        totals={key:sum(line[key] for line in breakdown) for key in ["low_cents","central_cents","high_cents"]}
        output={"mode":"synthetic scenario calculator","synthetic":True,"as_of":str(as_of),"inputs":values,"totals_ex_gst":totals,
            "central_inc_gst_cents":totals["central_cents"]+gst(totals["central_cents"]),"breakdown":breakdown,
            "comparables":[{"quote_id":q["id"],"project_id":q["project_id"],"date":q["quote_date"],"path":q["document_path"]} for q in ranked],
            "range_basis":"Sum of component-wise minimum / median / maximum rates in the selected synthetic examples; not a statistical confidence interval.",
            "assumptions":["Demonstration scope quantities are inferred using fixed, visible geometric ratios; not a design takeoff.",
                "Export volume is assumed at 35% of excavated volume; imported fill at 15%.",
                "Haul adjustments: AUD 0.45/m³/km for spoil and AUD 0.35/m³/km for fill; mobilisation AUD 35/km. All are invented simulation coefficients.",
                "Public context, when available, is displayed separately; it does not automatically change the rate-based estimate. No site survey or disposal acceptance is established.",
                "Year-end conditions are reviewed separately; no universal year-end price multiplier is applied."]}
        if include_evidence:
            output["comparables"]=[{"rank":index+1,"quote_id":q["id"],"project_id":q["project_id"],"vendor_id":q["vendor_id"],"vendor_name":q["vendor_name"],
                "project_name":self.projects[q["project_id"]]["name"],"suburb":self.projects[q["project_id"]]["suburb"],
                "ground_scenario":self.projects[q["project_id"]]["soil_scenario"],"disturbed_area_m2":self.projects[q["project_id"]]["disturbed_area_m2"],
                "area_difference_percent":rounded((self.projects[q["project_id"]]["disturbed_area_m2"]/area-1)*100),
                "date":q["quote_date"],"age_days":(as_of-date.fromisoformat(q["quote_date"])).days,"path":q["document_path"],
                "document_sha256":q["document_sha256"],"why_selected":"Earlier complete, fully priced synthetic scope; among the 12 nearest disturbed areas. One offer per job."}
                for index,q in enumerate(ranked)]
            output["provenance"]={"eligible_jobs":len(eligible),"used_jobs":len(ranked),"unique_suppliers":len({q["vendor_id"] for q in ranked}),
                "selection":"First complete quote per earlier job, then 12 nearest disturbed areas ranked by absolute log(area ratio).",
                "matched_on":["quote predates estimate date","complete synthetic scope with allocated unit rates","disturbed area"],
                "not_matched_on":["ground type","suburb","season or year-end conditions","quote age within the eligible period"],
                "pricing_adjustments":["Spoil haul: AUD 0.45 per m³ per km difference","Fill delivery: AUD 0.35 per m³ per km difference","Mobilisation: AUD 35 per km difference"],
                "not_applied":["Inflation or diesel escalation","Weather-related productivity or standby costs","Ground-condition normalisation"],
                "range_construction":"Add each item's lowest, median and highest adjusted rate × estimated quantity. The bounds combine different offers; they are not actual whole-package bids or a confidence interval.",
                "quantity_source":"User inputs plus explicit demonstration geometry ratios, not a measured bill of quantities.",
                "evidence_type":"Synthetic source quotations. Rates and adjustment coefficients are invented."}
            output["external_context"]=self.context.scenario(inputs,reference_date=ranked[0]["quote_date"])
        return output

    def plan_questions(self,inputs):
        """Sensitivity-based question ordering over explicit scenario bounds, not learned probabilities."""
        if not inputs.get("disturbed_area_m2") or not inputs.get("as_of"):
            candidates=[{"field":"disturbed_area_m2","question":"What area will actually be disturbed (m²)?"},{"field":"as_of","question":"What is the estimate date?"}]
            return {"mode":"clarification required","questions":[q for q in candidates if not inputs.get(q["field"])]}
        defaults={"disturbed_area_m2":inputs["disturbed_area_m2"],"as_of":inputs["as_of"],"depth_m":None,"rock_fraction":None,"spoil_haul_km":None,"fill_haul_km":20,"mobilisation_km":20}
        for key in ["suburb","planned_start_date","weather_working_days","rain_threshold_mm","recovery_days","lost_hours","standby_cost_per_day_ex_gst","fuel_litres"]:
            if key in inputs:
                defaults[key]=inputs[key]
        defaults.update({key:value for key,value in inputs.items() if key in defaults and value not in [None,""]})
        bounds={"depth_m":[.15,.6],"rock_fraction":[0,.25],"spoil_haul_km":[10,60]}
        wording={"depth_m":"What is the average excavation depth?","rock_fraction":"What proportion is rock, based on the ground investigation?","spoil_haul_km":"What is the site-to-disposal haul distance?"}
        unknown=[key for key in bounds if defaults.get(key) in [None,""]]
        scenarios=[]
        for combination in product(*[bounds[key] for key in unknown]):
            values=dict(defaults)
            values.update(dict(zip(unknown,combination)))
            result=self.estimate(values,include_evidence=False)
            if "totals_ex_gst" not in result:
                return result
            scenarios.append({"answers":dict(zip(unknown,combination)),"low_cents":result["totals_ex_gst"]["low_cents"],"high_cents":result["totals_ex_gst"]["high_cents"],"central_cents":result["totals_ex_gst"]["central_cents"]})
        low=min(s["low_cents"] for s in scenarios)
        high=max(s["high_cents"] for s in scenarios)
        width=high-low
        questions=[]
        for key in unknown:
            answers=[]
            for value in bounds[key]:
                subset=[s for s in scenarios if s["answers"][key]==value]
                a,b=min(s["low_cents"] for s in subset),max(s["high_cents"] for s in subset)
                answers.append({"value":value,"low_cents":a,"high_cents":b})
            reduction=width-sum(a["high_cents"]-a["low_cents"] for a in answers)/len(answers)
            questions.append({"field":key,"question":wording[key],"alternatives":answers,"illustrative_range_reduction_cents":max(0,round(reduction)),
                "explanation":{"initial_width_cents":width,"mean_conditional_width_cents":round(sum(a["high_cents"]-a["low_cents"] for a in answers)/len(answers)),"method":"Initial range width minus the equally weighted mean range width after the two hypothetical answers. This is a sensitivity ranking, not a learned probability."}})
        questions.sort(key=lambda q:q["illustrative_range_reduction_cents"],reverse=True)
        reference=dict(defaults)
        for key in unknown:
            reference[key]=sum(bounds[key])/len(bounds[key])
        return {"mode":"sensitivity-based question planner","synthetic":True,"low_cents":low,"high_cents":high,"width_cents":width,
            "scenario_count":len(scenarios),"questions":questions,"assumptions":defaults,
            "range_basis":"Scenario envelope with equal weighting of two illustrative answers per unknown. Potential tightening is a sensitivity score, not a calibrated expected value or confidence level.",
            "reference_estimate":self.estimate(reference),"reference_uses_midpoint_assumptions":bool(unknown),
            "unpriced_conditions":["Assumes non-hazardous spoil accepted by the nominated destination; treatment costs are not established.","Weather, shutdown and year-end terms require separate review; no inferred universal surcharge."]}
