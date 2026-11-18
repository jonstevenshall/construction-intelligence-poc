"""Explicit, cached public-source ingestion. Never called automatically by the app."""
import argparse
import hashlib
import io
import json
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .corpus import ROOT, SUBURBS, dump

DEST=ROOT/"data"/"context"
NS={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
AIP_URL="https://aip.com.au/wp-content/uploads/2026/11/AIP_TGP_Data_13-Nov-2026.xlsx"
SOIL_URL="https://soils.csiro.au/arcgis/rest/services/ASRIS/NationalSoilGrids/MapServer"


def fetch(url):
    request=urllib.request.Request(url,headers={"User-Agent":"EarthworksIntelligenceLab/0.2 (non-commercial evaluation prototype)"})
    with urllib.request.urlopen(request,timeout=60) as response:
        return response.read()


def workbook_rows(data,sheet_name):
    """Read cached XLSX cell values with the standard library; do not alter the workbook."""
    with ZipFile(io.BytesIO(data)) as archive:
        strings=[]
        if "xl/sharedStrings.xml" in archive.namelist():
            strings=["".join(si.itertext()) for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        workbook=ET.fromstring(archive.read("xl/workbook.xml"))
        sheet=next(s for s in workbook.find("m:sheets",NS) if s.attrib["name"]==sheet_name)
        rel_id=sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        rels=ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target=next(r.attrib["Target"] for r in rels if r.attrib["Id"]==rel_id)
        target=target.lstrip("/") if target.startswith("/") else "xl/"+target
        result=[]
        for row in ET.fromstring(archive.read(target)).findall("m:sheetData/m:row",NS):
            values={}
            for cell in row.findall("m:c",NS):
                value=cell.find("m:v",NS)
                if value is None:
                    continue
                text=value.text
                if cell.attrib.get("t")=="s":
                    text=strings[int(text)]
                values[cell.attrib["r"]]=text
            result.append(values)
        return result


def import_diesel(raw,retrieved):
    rows=workbook_rows(raw,"Diesel TGP")
    header=rows[0]
    if header.get("D1")!="Brisbane" or "DIESEL" not in header.get("A1","") or "inclusive of GST" not in header.get("A1",""):
        raise ValueError("AIP workbook header changed; inspect before importing")
    notes=workbook_rows(raw,"NOTES")
    note=next(row["B16"] for row in notes if "B16" in row)
    if "inclusive of GST" not in note:
        raise ValueError("GST basis not established in AIP source notes")
    records=[]
    for row in rows[1:]:
        a=next((key for key in row if key.startswith("A")),None)
        if not a:
            continue
        index=a[1:]
        if "D"+index not in row:
            continue
        try:
            day=date(1899,12,30)+timedelta(days=int(float(row[a])))
            value=float(row["D"+index])
        except (ValueError,TypeError,OverflowError):
            continue
        if date(2020,1,1)<=day<=date(2026,11,13) and math.isfinite(value) and 0<value<1000:
            records.append({"date":str(day),"cents_per_litre_inc_gst":value,"source_cell":f"'Diesel TGP'!D{index}","source_date_cell":f"'Diesel TGP'!A{index}"})
    records.sort(key=lambda r:r["date"])
    if len(records)<1000 or not any(r["date"].startswith("2025") for r in records):
        raise ValueError("Insufficient AIP coverage")
    result={"source_id":"AIP-DIESEL","provider":"Australian Institute of Petroleum / ORIMA Research","source_url":AIP_URL,
        "landing_page":"https://aip.com.au/resources/historical-ulp-and-diesel-tgp-data/","source_sha256":hashlib.sha256(raw).hexdigest(),
        "retrieved_at":retrieved,"publication_date":"2026-11-13","type":"published wholesale price observations",
        "units":"AUD cents per litre including GST","city":"Brisbane","notes_cell":"'NOTES'!B16",
        "records":records,"licence_note":"Publicly accessible AIP numeric extract; attribution retained. Source workbook is not redistributed.",
        "limitations":["Wholesale terminal average, not the contractor's delivered fuel price.","Weekday observations; no invented weekend rows.","This downloaded revision does not establish the exact data vintage a bidder had in 2025.","No fuel quantity or fuel share is known, so no automatic total-price escalation is applied."]}
    dump(DEST/"diesel.json",result)
    return result


def import_weather(raw,url,retrieved):
    payload=json.loads(raw)
    if not isinstance(payload,list) or len(payload)!=len(SUBURBS):
        raise ValueError("Expected one weather result per requested suburb")
    cells={}
    locations=[]
    for (suburb,latitude,longitude),result in zip(SUBURBS,payload):
        daily=result.get("daily",{})
        days=daily.get("time",[])
        amounts=daily.get("precipitation_sum",[])
        if len(days)!=2192 or len(amounts)!=len(days) or result.get("daily_units",{}).get("precipitation_sum")!="mm":
            raise ValueError("Weather coverage/units differ from the requested six-year daily series")
        for amount in amounts:
            if amount is not None and (not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<0):
                raise ValueError("Invalid precipitation value")
        key=f"ERA5_{result['latitude']}_{result['longitude']}"
        cell={"id":key,"latitude":result["latitude"],"longitude":result["longitude"],"time":days,"precipitation_mm":amounts}
        if key in cells and cells[key]!=cell:
            raise ValueError("Same grid point returned inconsistent weather")
        cells[key]=cell
        locations.append({"suburb":suburb,"requested_coordinates":[latitude,longitude],"cell_id":key})
    result={"source_id":"OPENMETEO-ERA5","provider":"Open-Meteo / Copernicus Climate Change Service ERA5","source_url":url,
        "documentation_url":"https://open-meteo.com/en/docs/historical-weather-api","retrieved_at":retrieved,
        "source_sha256":hashlib.sha256(raw).hexdigest(),"model":"ERA5","data_type":"gridded weather reanalysis, not a site rain gauge",
        "resolution":"0.25 degrees, approximately 25 km","timezone":"Australia/Brisbane","period":"2020-01-01/2025-12-31",
        "licence":"CC BY 4.0; credit Open-Meteo and Copernicus/ECMWF ERA5. Free endpoint used for non-commercial evaluation.",
        "locations":locations,"cells":list(cells.values()),
        "limitations":["Regional reanalysis, not measured rain at a fictional property.","Rain does not establish that a construction task stopped.","Historical weather is not an archived forecast; this is a retrospective snapshot downloaded after the synthetic tender year."]}
    dump(DEST/"weather.json",result)
    return result


def soil_query(latitude,longitude):
    return SOIL_URL+"/identify?"+urllib.parse.urlencode({"f":"pjson","geometry":f"{longitude},{latitude}","geometryType":"esriGeometryPoint","sr":4326,
        "layers":"all:1,2,7,8","tolerance":1,"mapExtent":f"{longitude-.01},{latitude-.01},{longitude+.01},{latitude+.01}","imageDisplay":"800,800,96","returnGeometry":"false"})


def import_soils(responses,retrieved):
    locations=[]
    for (suburb,latitude,longitude),raw in zip(SUBURBS,responses):
        result=json.loads(raw)
        if "error" in result:
            raise ValueError("CSIRO service returned an error")
        layers={r["layerId"]:r for r in result.get("results",[])}
        asc=layers.get(1,{}).get("attributes",{}).get("Raster.ASC_ORDER_NAME")
        clay_raw=layers.get(7,{}).get("attributes",{}).get("Classify.Pixel Value")
        try:
            clay=float(clay_raw)
            if not math.isfinite(clay) or not 0<=clay<=100:
                clay=None
        except (ValueError,TypeError):
            clay=None
        locations.append({"suburb":suburb,"screening_coordinates":[latitude,longitude],"soil_order":asc,"mapped_clay_percent_0_30cm":clay,
            "status":"mapped value returned" if asc or clay is not None else "no mapped coverage returned",
            "source_url":soil_query(latitude,longitude),"source_sha256":hashlib.sha256(raw).hexdigest(),"raw_results":result.get("results",[]),
            "spatial_basis":"Suburb-centre screening only; not a sample or investigation at a fictional project site."})
    result={"source_id":"CSIRO-ASRIS","provider":"CSIRO / ACLEP ASRIS National Soil Grids","source_url":SOIL_URL,
        "legend_url":SOIL_URL+"/legend","retrieved_at":retrieved,"data_type":"regional mapped soil screening",
        "depth_interval":"Clay layer 0–30 cm","locations":locations,
        "licence_note":"Attribution: CSIRO / ACLEP. Retain dataset-specific source metadata and check reuse terms before broader redistribution.",
        "limitations":["Screening at real suburb centres, not site-specific geotechnical findings.","Topsoil clay content does not establish rock volume, contamination, bearing capacity or days needed to recover after rain.","No rock, soil-treatment or dewatering surcharge is inferred from the map."]}
    dump(DEST/"soils.json",result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--download",action="store_true",help="Explicitly retrieve fixed public-source snapshots")
    args=parser.parse_args()
    if not args.download:
        parser.error("Use --download to opt into public-source requests; the app never downloads on startup")
    DEST.mkdir(parents=True,exist_ok=True)
    retrieved=datetime.now(timezone.utc).isoformat()
    parameters={"latitude":",".join(str(s[1]) for s in SUBURBS),"longitude":",".join(str(s[2]) for s in SUBURBS),
        "start_date":"2020-01-01","end_date":"2025-12-31","daily":"precipitation_sum","models":"era5","timezone":"Australia/Brisbane"}
    weather_url="https://archive-api.open-meteo.com/v1/archive?"+urllib.parse.urlencode(parameters)
    print("Importing AIP Brisbane diesel observations…",flush=True)
    diesel=import_diesel(fetch(AIP_URL),retrieved)
    print(f"Imported {len(diesel['records'])} diesel observations",flush=True)
    print("Importing six years of regional ERA5 rainfall…",flush=True)
    weather=import_weather(fetch(weather_url),weather_url,retrieved)
    print(f"Imported {len(weather['cells'])} unique grids for {len(weather['locations'])} suburbs",flush=True)
    soil_raw=[]
    for suburb,latitude,longitude in SUBURBS:
        print("Importing soil screening: "+suburb,flush=True)
        soil_raw.append(fetch(soil_query(latitude,longitude)))
    soils=import_soils(soil_raw,retrieved)
    dump(DEST/"manifest.json",{"retrieved_at":retrieved,"status":"imported public-source snapshots, separate from synthetic bid truth",
        "diesel_observations":len(diesel["records"]),"weather_grid_cells":len(weather["cells"]),
        "rainfall_daily_values":sum(len(c["time"]) for c in weather["cells"]),"regional_soil_screenings":len(soils["locations"]),
        "source_ids":[diesel["source_id"],weather["source_id"],soils["source_id"]]})
    print((DEST/"manifest.json").read_text(),flush=True)


if __name__=="__main__":
    main()
