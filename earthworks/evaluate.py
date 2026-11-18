"""Evaluate imported structured observations against synthetic fixture truth."""
import argparse
import json
from pathlib import Path

from .agent import scope_findings
from .corpus import ROOT, load

NUMERIC_FIELDS=["contract_ex_gst_cents","gst_cents","optional_ex_gst_cents","deposit_cents"]
MATERIAL_KINDS={"excluded","optional","rate_only","provisional","quantity_departure","wet_weather_excluded"}


def expected(quote):
    return {"quote_id":quote["id"],**{key:quote[key] for key in NUMERIC_FIELDS},
        "flags":[{"kind":f["kind"],"scope_item_id":f.get("scope_item_id","")} for f in scope_findings(quote)]}


def evaluate(observations,quotes):
    truth={q["id"]:q for q in quotes}
    correct=checked=flags_expected=flags_found=material_fn=0
    examples=[]
    seen=set()
    for item in observations:
        qid=item.get("quote_id")
        if qid not in truth or qid in seen:
            raise ValueError("Unknown or repeated quote_id: "+str(qid))
        seen.add(qid)
        target=expected(truth[qid])
        for field in NUMERIC_FIELDS:
            checked+=1
            if type(item.get(field)) is int and item[field]==target[field]:
                correct+=1
            else:
                examples.append({"quote_id":qid,"field":field,"expected":target[field],"observed":item.get(field)})
        target_flags={(f["kind"],f["scope_item_id"]) for f in target["flags"]}
        observed_flags={(f.get("kind"),f.get("scope_item_id","")) for f in item.get("flags",[]) if isinstance(f,dict)}
        flags_expected+=len(target_flags)
        flags_found+=len(target_flags&observed_flags)
        for kind,scope in sorted(target_flags-observed_flags):
            material_fn+=kind in MATERIAL_KINDS
            examples.append({"quote_id":qid,"missing_flag":kind,"scope_item_id":scope})
        for kind,scope in sorted(observed_flags-target_flags):
            examples.append({"quote_id":qid,"unexpected_flag":kind,"scope_item_id":scope})
    return {"status":"Evaluation against synthetic ground truth only","quotes_observed":len(seen),"numeric_fields_correct":correct,
        "numeric_fields_checked":checked,"expected_flags_detected":flags_found,"expected_flags":flags_expected,
        "material_false_negatives":material_fn,"discrepancies":examples,"semantic_assessment":"not performed",
        "external_product_testing":"not performed; this evaluates synthetic observations only"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("observations",type=Path,nargs="?")
    parser.add_argument("--demo",action="store_true")
    args=parser.parse_args()
    quotes=load()["quotes"]
    if args.demo:
        observations=[expected(q) for q in quotes[:12]]
        # Intentionally flawed synthetic transcription demonstrates material omission detection.
        observations[1]["flags"]=[]
        observations[0]["deposit_cents"]+=10000
        report=evaluate(observations,quotes)
        report["observation_provenance"]="Intentionally flawed synthetic demonstration outputs; not external-tool observations"
        (ROOT/"data"/"demo-observations.json").write_text(json.dumps({"observations":observations},indent=2)+"\n")
    elif args.observations:
        payload=json.loads(args.observations.read_text())
        report=evaluate(payload["observations"],quotes)
        report["observation_provenance"]=payload.get("provenance","unspecified; must be documented before external product claims")
    else:
        parser.error("Provide an observations JSON file or --demo")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
