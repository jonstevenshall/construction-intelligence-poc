"""Seeded, auditable synthetic tenders. Money is stored as integer AUD cents."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACRE_M2 = Decimal("4046.8564224")
DISCLAIMER = "SYNTHETIC TEST DATA — invented suppliers, sites, quantities, prices and terms; not market evidence."
SUBURBS = [
    ("Brendale", -27.32, 152.99), ("Wacol", -27.59, 152.93),
    ("Eagle Farm", -27.43, 153.09), ("Rocklea", -27.54, 153.00),
    ("Yatala", -27.75, 153.23), ("Redbank", -27.61, 152.87),
    ("Caboolture", -27.08, 152.95), ("Loganholme", -27.68, 153.19),
    ("Richlands", -27.60, 152.95), ("Hemmant", -27.45, 153.13),
]
ADJECTIVES = ["Amber", "Banksia", "Copper", "Drift", "Evergreen", "Fern", "Granite", "Harbour", "Ironbark", "Juniper"]
NOUNS = ["Ridge", "Creek", "Range", "Vale", "Grove"]
PATTERNS = ["main_building_only", "optional_externals", "rate_only_rock", "provisional_rock",
            "drainage_excluded", "quantity_departure", "wet_weather_excluded", "lump_sum", "tax_inclusive"]
# Sample-inspired taxonomy, with an additional explicit mobilisation item.
# Rates below are invented scenario parameters, not copied market rates.
SCOPE = [
 ("MB01", "Main building", "Strip and stockpile topsoil", "m²", 320),
 ("MB02", "Main building", "Detailed excavation for footings and services", "m³", 2150),
 ("MB03", "Main building", "Subsoil drainage and pits", "m", 6800),
 ("MB04", "Main building", "Supply and compact crushed rock base", "m³", 9100),
 ("MB05", "Main building", "Geotextile and blinding", "m²", 670),
 ("MB06", "Main building", "Temporary site access matting", "m²", 1800),
 ("IL01", "ILUs", "Strip and stockpile topsoil", "m²", 320),
 ("IL02", "ILUs", "Detailed excavation for footings and services", "m³", 2150),
 ("IL03", "ILUs", "Supply and compact crushed rock base", "m³", 9100),
 ("IL04", "ILUs", "Kerbs and ramps", "m", 7400),
 ("IL05", "ILUs", "Geotextile and blinding", "m²", 670),
 ("CP01", "Carpark and access roads", "Strip and stockpile topsoil", "m²", 320),
 ("CP02", "Carpark and access roads", "Supply and compact crushed rock base", "m³", 9100),
 ("CP03", "Carpark and access roads", "Stormwater and sewer service trenching", "m³", 2800),
 ("CP04", "Carpark and access roads", "Kerbs and ramps", "m", 7400),
 ("EX01", "Site externals", "Export surplus spoil including nominated disposal", "m³", 3400),
 ("EX02", "Site externals", "Import certified fill including delivery", "m³", 4500),
 ("EX03", "Site externals", "Rock excavation with hydraulic breaker", "m³", 11200),
 ("EX04", "Site externals", "Proof rolling and moisture conditioning", "m²", 430),
 ("EX05", "Site externals", "Erosion control, dust suppression and water cart", "day", 92000),
 ("MO01", "Preliminaries", "Plant mobilisation and demobilisation", "item", 250000),
]


def rounded(value, places="0.01"):
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def cents(quantity, rate):
    return int((Decimal(str(quantity)) * Decimal(rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gst(ex_cents):
    return cents("0.1", ex_cents)


def haversine(a, b):
    a1, o1, a2, o2 = map(math.radians, [*a, *b])
    h = math.sin((a2-a1)/2)**2 + math.cos(a1)*math.cos(a2)*math.sin((o2-o1)/2)**2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(h)))


def distance(a, b):
    straight = haversine(a, b)
    return {"straight_line_km": rounded(straight), "estimated_road_km": rounded(straight * 1.3),
            "method": "synthetic road-distance proxy: haversine × 1.30; not routed or truck-validated",
            "observed": False, "assumed_road_factor": 1.3}


def calendar_context(day):
    year_end=date(day.year,12,31)
    financial_end=date(day.year if day.month<=6 else day.year+1,6,30)
    season={12:"summer",1:"summer",2:"summer",3:"autumn",4:"autumn",5:"autumn",6:"winter",7:"winter",8:"winter",9:"spring",10:"spring",11:"spring"}[day.month]
    return {"date":str(day),"month":day.month,"southern_hemisphere_season":season,
            "days_to_calendar_year_end":(year_end-day).days,"days_to_financial_year_end":(financial_end-day).days,
            "calendar_year_end_within_30_days":(year_end-day).days<=30,
            "financial_year_end_within_30_days":(financial_end-day).days<=30,
            "public_holiday_calendar_status":"not yet imported"}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def generate(out=ROOT / "data", seed=20251115):
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    docs = out / "documents"
    docs.mkdir(exist_ok=True)
    vendors = []
    for i in range(50):
        suburb, lat, lon = SUBURBS[i % len(SUBURBS)]
        vendors.append({"id": f"V{i+1:03}", "name": f"{ADJECTIVES[i//5]} {NOUNS[i%5]} Earthworks (Fictional)",
            "fictional": True, "depot_suburb": suburb,
            "depot_address": f"Depot DEMO-{i+1:03}, Fictional Plant Road, {suburb} QLD",
            "depot_coordinates": [rounded(lat+rng.uniform(-0.008,0.008),"0.00001"), rounded(lon+rng.uniform(-0.008,0.008),"0.00001")],
            "coordinate_status": "invented point near suburb; not a verified address",
            "base_price_factor": rounded(rng.uniform(0.85,1.22)),
            "deposit_percent": [10,20,30,40,50][i%5],
            "capacity_m3_per_day": rng.choice([180,240,320,450]),
            "offer_note": rng.choice(["Single mobilisation included", "Firm price subject to scope confirmation", "Volume offer for agreed quantities"]),
            "wet_weather_policy": "normal_seasonal_allowance_only"})
        vendors[-1]["year_end_policy"]=["conditional_discount","rush_capacity_premium","no_adjustment"][i%3]
        vendors[-1]["shutdown_scenario"]={"start":"2025-12-22","end":"2026-01-05","synthetic":True} if i%4==0 else None
    four_bid_jobs = set(rng.sample(range(300), 100))
    projects, quotes, cases = [], [], []
    noncomplete_index = 0
    quote_counter = 0
    for i in range(300):
        month = i//25 + 1
        days = [d for d in range(1,calendar.monthrange(2025,month)[1]+1) if date(2025,month,d).weekday()<5]
        tender = date(2025,month,days[i%len(days)])
        suburb, lat, lon = SUBURBS[rng.randrange(len(SUBURBS))]
        area_m2 = int(rng.uniform(1800,100000))
        work_fraction = rounded(rng.uniform(0.45,0.9))
        depth = rng.choice([0.15,0.25,0.4,0.6,0.9])
        disturbed = rounded(area_m2*work_fraction)
        soil = rng.choice(["sandy", "mixed fill", "clay", "rock-bearing"])
        rock_volume = rounded(disturbed*depth*(0.2 if soil=="rock-bearing" else 0.035))
        base_volume = disturbed*depth
        quantities = [disturbed*.5, base_volume*.5, math.sqrt(disturbed)*1.5, disturbed*.5*.12,
             disturbed*.5, min(1200,disturbed*.08), disturbed*.25, base_volume*.25,
             disturbed*.25*.12, math.sqrt(disturbed), disturbed*.25, disturbed*.25,
             disturbed*.25*.18, base_volume*.12, math.sqrt(disturbed)*1.2,
             base_volume*.35, base_volume*.15, rock_volume, disturbed,
             max(3,math.ceil(base_volume/1500)), 1]
        location = [rounded(lat+rng.uniform(-.018,.018),"0.00001"), rounded(lon+rng.uniform(-.018,.018),"0.00001")]
        disposal = [rounded(location[0]+rng.uniform(.06,.25),"0.00001"), rounded(location[1]+rng.uniform(-.2,.2),"0.00001")]
        borrow = [rounded(location[0]+rng.uniform(-.2,-.05),"0.00001"), rounded(location[1]+rng.uniform(.04,.18),"0.00001")]
        project = {"id": f"P{i+1:03}", "name": f"Demo {suburb} Development {i+1:03}", "synthetic": True,
            "site_address": f"Lot DEMO-{i+1:03}, Imaginary Access Road, {suburb} QLD", "suburb":suburb,
            "coordinates":location, "coordinate_status":"invented demonstration point, not a verified property",
            "tender_date":str(tender), "planned_start_date": str(tender+timedelta(days=28)),
            "quote_calendar":calendar_context(tender),"work_calendar":calendar_context(tender+timedelta(days=28)),
            "site_area_m2":area_m2, "site_area_acres":rounded(Decimal(area_m2)/ACRE_M2,"0.0001"),
            "disturbed_fraction":work_fraction, "disturbed_area_m2":disturbed, "average_excavation_depth_m":depth,
            "soil_scenario":soil, "geotechnical_status":rng.choice(["synthetic report available","not investigated"]),
            "slope_scenario":rng.choice(["gentle","moderate","steep"]),
            "disposal_site":{"id":f"TIP-{i+1:03}","name":"Fictional disposal destination", "coordinates":disposal,"acceptance":"unverified; synthetic assumption only"},
            "fill_source":{"id":f"FILL-{i+1:03}","name":"Fictional certified-fill source", "coordinates":borrow},
            "spoil_haul":distance(location,disposal), "fill_haul":distance(borrow,location),
            "public_context":{"rainfall":None,"diesel_price":None,"terrain_dataset":None,"soil_mapping":None,"disposal_fee":None},
            "weather_context":{"seasonal_climatology":None,"quote_date_observations":None,"work_period_observations":None,
                "forecast_as_of_quote":None,"station_id":None,"station_distance_km":None,
                "note":"No observed or forecast weather has been imported. Future actual rainfall must never be used as quote-time knowledge."},
            "scope":[{"id":s[0],"zone":s[1],"description":s[2],"unit":s[3],"quantity":rounded(q)} for s,q in zip(SCOPE,quantities)],
            "simulation_assumptions":{"season_factor":rounded(1+0.004*(month-1)), "soil_price_factor": {"sandy":1,"mixed fill":1.05,"clay":1.12,"rock-bearing":1.18}[soil],
                 "note":"invented price-generation rules; not learned from actual market observations"}}
        projects.append(project)
        chosen = rng.sample(vendors, 4 if i in four_bid_jobs else 3)
        for j, vendor in enumerate(chosen):
            quote_counter += 1
            pattern = "complete" if j==0 else PATTERNS[noncomplete_index%len(PATTERNS)]
            if j:
                noncomplete_index += 1
            qid=f"Q{quote_counter:04}"
            mob=distance(vendor["depot_coordinates"],location)
            factor=vendor["base_price_factor"]*project["simulation_assumptions"]["season_factor"]*project["simulation_assumptions"]["soil_price_factor"]*rng.uniform(.97,1.03)
            year_end_offer=None
            if project["quote_calendar"]["calendar_year_end_within_30_days"] or project["quote_calendar"]["financial_year_end_within_30_days"]:
                if vendor["year_end_policy"]=="conditional_discount":
                    factor*=.97
                    cutoff=date(2025,6,30) if month==6 else date(2025,12,31)
                    year_end_offer={"type":"conditional_discount","percent":3,"condition":f"Award by {cutoff}; 3% offer already incorporated in quoted rates. Do not deduct again.","synthetic":True}
                elif vendor["year_end_policy"]=="rush_capacity_premium":
                    factor*=1.04
                    year_end_offer={"type":"capacity_premium","percent":4,"condition":"Year-end capacity premium already incorporated in quoted rates; confirm programme availability.","synthetic":True}
            lines=[]
            for k,(spec, required) in enumerate(zip(SCOPE,project["scope"])):
                code,zone,description,unit,base_rate=spec
                qty=required["quantity"]
                rate=cents(factor,base_rate)
                if code=="MO01":
                    rate += cents(mob["estimated_road_km"],3500)
                if code=="EX01":
                    rate += cents(project["spoil_haul"]["estimated_road_km"],45)
                if code=="EX02":
                    rate += cents(project["fill_haul"]["estimated_road_km"],35)
                status="priced"
                notes=[]
                if pattern=="main_building_only" and zone not in ["Main building","Preliminaries"]:
                    status="excluded"; notes.append("Tender covers main building only; other zones excluded.")
                if pattern=="optional_externals" and zone=="Site externals":
                    status="optional"; notes.append("Optional price; excluded from submitted contract total.")
                if pattern=="drainage_excluded" and code=="MB03":
                    status="excluded"; notes.append("Drainage and pits by head contractor.")
                if pattern=="rate_only_rock" and code=="EX03":
                    status="rate_only"; notes.append("No rock quantity committed; measure and agree actual volume.")
                if pattern=="provisional_rock" and code=="EX03":
                    status="provisional"; qty=rounded(qty*.5); notes.append("Provisional allowance only; excess measured rock is additional.")
                if pattern=="quantity_departure" and code=="MB02":
                    qty=rounded(qty*.8); notes.append("Our measured excavation quantity is 20% below the tender quantity; clarify before comparing.")
                amount=cents(qty,rate) if status not in ["excluded","rate_only"] else 0
                lines.append({"id":f"{qid}-{code}","scope_item_id":code,"zone":zone,"description":description,
                    "quantity":None if status=="rate_only" else qty,"unit":unit,"rate_cents":rate,"amount_cents":amount,"status":status,
                    "required_quantity":required["quantity"],"notes":notes,"included_in_line_id":None})
            if pattern=="lump_sum":
                total=sum(l["amount_cents"] for l in lines)
                lines[0].update(quantity=1,unit="item",rate_cents=total,amount_cents=total)
                lines[0]["notes"]=["Single lump sum covers the full listed scope; no individual line rate allocation was offered."]
                for line in lines[1:]:
                    line.update(status="included_elsewhere",amount_cents=0,rate_cents=None,quantity=None,included_in_line_id=lines[0]["id"])
            contract_ex=sum(l["amount_cents"] for l in lines if l["status"] in ["priced","provisional"])
            optional_ex=sum(l["amount_cents"] for l in lines if l["status"]=="optional")
            tax=gst(contract_ex)
            deposit=vendor["deposit_percent"]
            wording=[f"Deposit of {deposit}% of the GST-inclusive submitted contract sum payable before mobilisation.",
                "Balance by measured progress claims; payment due 14 days after an accepted claim.",
                vendor["offer_note"], "Hazardous or contaminated material, asbestos and acid sulfate treatment excluded pending classification.",
                "No disposal facility acceptance or contamination classification has been independently verified in this synthetic scenario."]
            if pattern=="wet_weather_excluded":
                wording.append("Dewatering, wet-weather standby and remobilisation following rain are excluded and require a separate agreement.")
            else:
                wording.append("Ordinary water-cart operation is included as listed; abnormal dewatering and latent ground conditions require clarification.")
            if year_end_offer:
                wording.append(year_end_offer["condition"])
            if vendor["shutdown_scenario"]:
                shutdown=vendor["shutdown_scenario"]
                wording.append(f"Planned shutdown from {shutdown['start']} to {shutdown['end']}; confirm any programme overlap.")
            quote={"id":qid,"project_id":project["id"],"vendor_id":vendor["id"],"vendor_name":vendor["name"],"synthetic":True,
                "quote_date":str(tender),"revision":1,"valid_until":str(tender+timedelta(days=30)),"currency":"AUD",
                "display_tax_basis":"inclusive" if pattern=="tax_inclusive" else "exclusive",
                "submitted_total_cents":contract_ex+tax if pattern=="tax_inclusive" else contract_ex,
                "contract_ex_gst_cents":contract_ex,"gst_cents":tax,"contract_inc_gst_cents":contract_ex+tax,
                "optional_ex_gst_cents":optional_ex,"review_total_ex_gst_cents":contract_ex+optional_ex,
                "deposit_percent":deposit,"deposit_basis":"submitted contract total including GST, excluding optional work",
                "deposit_cents":cents(Decimal(deposit)/100,contract_ex+tax),"mobilisation_distance":mob,
                "mobilisation_price_status":"bundled in lump sum" if pattern=="lump_sum" else "separately priced",
                "terms":wording,"lines":lines,"document_id":f"DOC-{qid}","document_path":f"documents/{qid}.md",
                "scenario_pattern":pattern,"unit_price_allocation_available":pattern!="lump_sum"}
            quote["year_end_offer"]=year_end_offer
            quote["supplier_shutdown"]=vendor["shutdown_scenario"]
            doc=[f"# {vendor['name']} — {qid}","",DISCLAIMER,"",f"Project: {project['id']} — {project['name']}",
                 f"Site: {project['site_address']}",f"Date: {quote['quote_date']} | Revision 1 | Valid until {quote['valid_until']}",
                 f"Area: {project['site_area_acres']} acres / {project['site_area_m2']} m². Disturbed area and depths are separate scope inputs.",
                 "Currency AUD. All line rates and line amounts below exclude GST.","", "## Schedule", "", "Item | Zone | Description | Quantity | Unit | Rate AUD | Amount AUD | Treatment | Qualification", "---|---|---|---:|---|---:|---:|---|---"]
            for line in lines:
                rate="—" if line["rate_cents"] is None else f"{line['rate_cents']/100:.2f}"
                qty="—" if line["quantity"] is None else str(line["quantity"])
                note=" ".join(line["notes"]) or (f"Included in {line['included_in_line_id']}" if line["included_in_line_id"] else "As scheduled")
                doc.append(f"{line['scope_item_id']} | {line['zone']} | {line['description']} | {qty} | {line['unit']} | {rate} | {line['amount_cents']/100:.2f} | {line['status']} | {note}")
                line["evidence"]={"document_id":quote["document_id"],"path":quote["document_path"],"line":len(doc)}
            doc.extend(["","## Commercial totals",f"Submitted price: AUD {quote['submitted_total_cents']/100:.2f} ({quote['display_tax_basis']} of GST)",
                f"Contract subtotal excluding GST: AUD {contract_ex/100:.2f}",f"GST: AUD {tax/100:.2f}",f"Contract including GST: AUD {(contract_ex+tax)/100:.2f}",
                f"Optional work excluding GST, NOT in submitted total: AUD {optional_ex/100:.2f}",
                f"Review total including priced options, excluding GST: AUD {(contract_ex+optional_ex)/100:.2f}","","## Terms and qualifications"])
            quote["terms_evidence"]=[]
            for term in wording:
                doc.append("- "+term)
                quote["terms_evidence"].append({"document_id":quote["document_id"],"path":quote["document_path"],"line":len(doc)})
            doc.extend(["",f"Upfront deposit including GST: AUD {quote['deposit_cents']/100:.2f}",
                f"Depot to site: {mob['estimated_road_km']} km estimated one way. {mob['method']}.",
                f"Spoil destination: {project['spoil_haul']['estimated_road_km']} km estimated one way; different from depot mobilisation."])
            (docs/f"{qid}.md").write_text("\n".join(doc)+"\n")
            quote["document_sha256"]=hashlib.sha256((docs/f"{qid}.md").read_bytes()).hexdigest()
            quotes.append(quote)
        project_quotes=[q for q in quotes if q["project_id"]==project["id"]]
        cases.extend([
            {"id":f"{project['id']}-scope","project_id":project["id"],"question":"Which quotes have unresolved scope differences?",
             "expected_quote_patterns":{q["id"]:q["scenario_pattern"] for q in project_quotes},"assessment":"deterministic fixture expectations, not observed product results"},
            {"id":f"{project['id']}-cash","project_id":project["id"],"question":"What cash is required upfront for each offer?",
             "expected_deposit_cents":{q["id"]:q["deposit_cents"] for q in project_quotes},"assessment":"integer-cents calculation with explicit GST basis"}])
    write_jsonl(out/"projects.jsonl",projects)
    write_jsonl(out/"vendors.jsonl",vendors)
    write_jsonl(out/"quotes.jsonl",quotes)
    write_jsonl(out/"evaluation_cases.jsonl",cases)
    dump(out/"manifest.json",{"schema_version":1,"seed":seed,"period":"2025-01-01/2025-12-31","disclaimer":DISCLAIMER,
        "projects":len(projects),"quotes":len(quotes),"vendors":len(vendors),"evaluation_cases":len(cases),
        "currency":"AUD","money_storage":"integer cents","public_source_values_imported":False,
        "limitations":["No real supplier offers, market-calibrated rates or actual tender outcomes.","Distances are synthetic road proxies, not navigable truck routes.","One synthetic year cannot establish reliable pricing forecasts or weather effects.","Public source registry records candidate enrichments; no live feeds have been imported."]})
    return {"projects":projects,"vendors":vendors,"quotes":quotes,"cases":cases}


def load(out=ROOT/"data"):
    return {name:[json.loads(line) for line in (out/f"{name}.jsonl").read_text().splitlines() if line] for name in ["projects","vendors","quotes"]}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"data")
    parser.add_argument("--seed",type=int,default=20251115)
    args=parser.parse_args()
    result=generate(args.output,args.seed)
    print(json.dumps({k:len(v) for k,v in result.items()}))
