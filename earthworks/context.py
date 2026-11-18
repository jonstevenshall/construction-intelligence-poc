"""Public evidence and explicit wet-weather scenarios; never inferred actual lost days."""
import bisect
import json
import math
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean

from .corpus import ROOT, cents, haversine, rounded


class PublicContext:
    def __init__(self,directory=None):
        self.directory=Path(directory or ROOT/"data"/"context")
        self.data={}
        for name in ["weather","diesel","soils"]:
            path=self.directory/(name+".json")
            if path.exists():
                self.data[name]=json.loads(path.read_text())
        self.weather_cells={cell["id"]:dict(zip(cell["time"],cell["precipitation_mm"])) for cell in self.data.get("weather",{}).get("cells",[])}
        self.diesel_dates=[row["date"] for row in self.data.get("diesel",{}).get("records",[])]

    def status(self):
        return {name:{"status":"imported snapshot","source_id":pack["source_id"],"retrieved_at":pack["retrieved_at"],"source_url":pack["source_url"]} for name,pack in self.data.items()}

    def soil(self,suburb,site_coordinates=None):
        pack=self.data.get("soils")
        if not pack:
            return {"status":"not imported"}
        row=next((row for row in pack["locations"] if row["suburb"]==suburb),None)
        if not row:
            return {"status":"no regional screening"}
        return {**row,"source_id":pack["source_id"],"provider":pack["provider"],"retrieved_at":pack["retrieved_at"],
            "distance_from_site_km":rounded(haversine(site_coordinates,row["screening_coordinates"])) if site_coordinates else None,
            "limitations":pack["limitations"],"price_adjustment_cents":None}

    def diesel(self,as_of,reference_date=None):
        pack=self.data.get("diesel")
        if not pack:
            return {"status":"not imported"}
        def previous(day):
            index=bisect.bisect_right(self.diesel_dates,str(day))-1
            if index<0:
                return None
            row=pack["records"][index]
            return {**row,"age_days":(date.fromisoformat(str(day))-date.fromisoformat(row["date"])).days,
                "aud_per_litre_ex_gst":rounded(row["cents_per_litre_inc_gst"]/110,"0.0001")}
        current=previous(as_of)
        reference=previous(reference_date) if reference_date else None
        result={"status":"imported snapshot","source_id":pack["source_id"],"provider":pack["provider"],"source_url":pack["source_url"],
            "retrieved_at":pack["retrieved_at"],"publication_date":pack["publication_date"],"source_sha256":pack["source_sha256"],
            "units":pack["units"],"current":current,"reference":reference,"limitations":pack["limitations"],
            "price_adjustment_cents":None,"snapshot_published_after_requested_date":pack["publication_date"]>str(as_of),
            "explanation":"The latest published observation on or before the requested date is shown. No fuel quantity/share is known, so this does not change the quoted total."}
        if current and reference:
            result["change_percent"]=rounded((current["cents_per_litre_inc_gst"]/reference["cents_per_litre_inc_gst"]-1)*100)
        return result

    @staticmethod
    def workdays(start,count):
        days=[]
        day=start
        while len(days)<count:
            if day.weekday()<5:
                days.append(day)
            day+=timedelta(days=1)
        return days

    @staticmethod
    def exposure(series,start,count,threshold,recovery_days,assumed_lost_hours,shift_hours):
        days=PublicContext.workdays(start,count)
        required={str(day-timedelta(days=lag)) for day in days for lag in range(recovery_days+1)}
        missing=sorted(key for key in required if key not in series or series[key] is None)
        if missing:
            return {"complete":False,"missing_dates":missing}
        wet=[]
        recovery=[]
        affected=[]
        for day in days:
            key=str(day)
            rain=series[key]>=threshold
            lagged=any(series[str(day-timedelta(days=lag))]>=threshold for lag in range(1,recovery_days+1))
            if rain:
                wet.append(key)
            if lagged and not rain:
                recovery.append(key)
            if rain or lagged:
                affected.append(key)
        return {"complete":True,"start":str(days[0]),"end":str(days[-1]),"scheduled_weekdays":len(days),
            "rain_threshold_weekdays":len(wet),"additional_recovery_weekdays":len(recovery),"potentially_affected_weekdays":len(affected),
            "modelled_lost_day_equivalents":rounded(len(affected)*assumed_lost_hours/shift_hours),
            "affected_dates":affected,"rain_dates":wet,"recovery_dates":recovery,
            "actual_lost_workdays":None}

    def weather(self,suburb,start_date,as_of,working_days=20,threshold_mm=10,recovery_days=1,lost_hours=4,shift_hours=8):
        pack=self.data.get("weather")
        if not pack:
            return {"status":"not imported"}
        start=date.fromisoformat(str(start_date))
        estimate_date=date.fromisoformat(str(as_of))
        for name,value,lower,upper in [("working_days",working_days,1,60),("threshold_mm",threshold_mm,.1,100),("recovery_days",recovery_days,0,5),("lost_hours",lost_hours,0,24),("shift_hours",shift_hours,1,24)]:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not lower<=value<=upper:
                raise ValueError(name+" is outside the supported range")
        if int(working_days)!=working_days or int(recovery_days)!=recovery_days or lost_hours>shift_hours:
            raise ValueError("Days must be integers and assumed lost hours must not exceed the shift")
        location=next((row for row in pack["locations"] if row["suburb"]==suburb),None)
        if not location:
            return {"status":"no regional weather coverage"}
        series=self.weather_cells[location["cell_id"]]
        cell=next(cell for cell in pack["cells"] if cell["id"]==location["cell_id"])
        historical=[]
        for year in range(2020,2026):
            try:
                candidate=start.replace(year=year)
            except ValueError:
                candidate=start.replace(year=year,day=28)
            # Complete analogue windows must finish before the estimate date and target year.
            candidate_days=self.workdays(candidate,int(working_days))
            if candidate.year>=start.year or candidate_days[-1]>=estimate_date:
                continue
            scenario=self.exposure(series,candidate,int(working_days),threshold_mm,int(recovery_days),lost_hours,shift_hours)
            if scenario["complete"]:
                historical.append(scenario)
        same_period=self.exposure(series,start,int(working_days),threshold_mm,int(recovery_days),lost_hours,shift_hours)
        annual=[]
        for year in range(2020,2026):
            rows=[value for day,value in series.items() if day.startswith(str(year)) and value is not None]
            annual.append({"year":year,"days_available":len(rows),"rain_days_ge_1mm":sum(value>=1 for value in rows),
                "rain_days_ge_10mm":sum(value>=10 for value in rows),"rain_days_ge_25mm":sum(value>=25 for value in rows),"rainfall_mm":rounded(sum(rows))})
        result={"status":"imported snapshot","source_id":pack["source_id"],"provider":pack["provider"],"source_url":pack["source_url"],
            "documentation_url":pack["documentation_url"],"retrieved_at":pack["retrieved_at"],"source_sha256":pack["source_sha256"],
            "suburb":suburb,"requested_coordinates":location["requested_coordinates"],"grid_coordinates":[cell["latitude"],cell["longitude"]],
            "resolution":pack["resolution"],"data_type":pack["data_type"],"period":pack["period"],"licence":pack["licence"],
            "assumptions":{"start_date":str(start),"working_days":int(working_days),"rain_threshold_mm":threshold_mm,"recovery_calendar_days":int(recovery_days),
                "assumed_lost_hours_per_affected_day":lost_hours,"shift_hours":shift_hours,"work_calendar":"Monday–Friday; public holidays and shutdowns are not removed"},
            "historical_windows":historical,"same_period_retrospective":same_period if same_period["complete"] else None,
            "annual_rainfall":annual,"actual_lost_workdays":None,"price_adjustment_cents":None,
            "snapshot_retrieved_after_estimate_date":pack["retrieved_at"][:10]>str(estimate_date),
            "method":"Rain-threshold days plus a union of assumed recovery days, restricted to scheduled weekdays. Assumed lost hours convert exposure into modelled day equivalents. These are not recorded lost days or contractual entitlements.",
            "limitations":pack["limitations"]+["The default 10 mm threshold, one recovery day and four lost hours are uncalibrated scenario inputs, not a construction standard.","Regional clay screening never automatically sets a recovery period.","Retrospective snapshots are not proof of the information available when a historical quote was issued."]}
        if historical:
            values=[window["potentially_affected_weekdays"] for window in historical]
            result["seasonal_summary"]={"historical_windows":len(historical),"min_affected_weekdays":min(values),"mean_affected_weekdays":rounded(mean(values)),"max_affected_weekdays":max(values),
                "mean_modelled_lost_day_equivalents":rounded(mean(window["modelled_lost_day_equivalents"] for window in historical))}
        return result

    def for_project(self,project,as_of=None,**weather_assumptions):
        as_of=as_of or project["tender_date"]
        return {"suburb":project["suburb"],"weather":self.weather(project["suburb"],project["planned_start_date"],as_of,**weather_assumptions),
            "diesel":self.diesel(as_of),"soil":self.soil(project["suburb"],project["coordinates"]),
            "interpretation":"Real public regional context attached to an invented project. No claim that these conditions caused the synthetic quoted price."}

    def scenario(self,inputs,reference_date=None):
        """Convert explicit user allowances into separate what-if costs, never reprice a bid."""
        as_of=str(inputs["as_of"])
        suburb=inputs.get("suburb","Brendale")
        start=inputs.get("planned_start_date") or str(date.fromisoformat(as_of)+timedelta(days=28))
        weather=self.weather(suburb,start,as_of,working_days=inputs.get("weather_working_days",20),
            threshold_mm=inputs.get("rain_threshold_mm",10),recovery_days=inputs.get("recovery_days",1),lost_hours=inputs.get("lost_hours",4))
        diesel=self.diesel(as_of,reference_date or inputs.get("reference_date"))
        costs={"included_in_estimate":False,"weather_cost_cents":None,"diesel_change_cents":None,
            "basis":"Separate user-assumption scenarios; no automatic adjustment to the estimate and no claim of observed loss."}
        standby=inputs.get("standby_cost_per_day_ex_gst")
        if standby not in [None,""]:
            standby=float(standby)
            if not math.isfinite(standby) or not 0<=standby<=100000:
                raise ValueError("Daily standby cost must be between 0 and AUD 100,000 ex GST")
            costs["standby_cost_per_day_ex_gst"]=standby
            windows=weather.get("historical_windows",[])
            if windows:
                assumptions=weather["assumptions"]
                fraction=Decimal(str(assumptions["assumed_lost_hours_per_affected_day"]))/Decimal(str(assumptions["shift_hours"]))
                amounts=[cents(Decimal(w["potentially_affected_weekdays"])*fraction,cents(standby,100)) for w in windows]
                costs["weather_cost_cents"]={"low":min(amounts),"mean":round(mean(amounts)),"high":max(amounts)}
                costs["weather_formula"]="Each historical window's modelled lost-day equivalents × user-supplied cost per full lost-day equivalent; summarised across windows. Not a contractual entitlement or an additive contingency recommendation."
        fuel=inputs.get("fuel_litres")
        if fuel not in [None,""]:
            fuel=float(fuel)
            if not math.isfinite(fuel) or not 0<=fuel<=10000000:
                raise ValueError("Fuel allowance must be between 0 and 10,000,000 litres")
            costs["fuel_litres"]=fuel
            current,reference=diesel.get("current"),diesel.get("reference")
            if current and reference:
                delta=(Decimal(str(current["cents_per_litre_inc_gst"]))-Decimal(str(reference["cents_per_litre_inc_gst"])))/Decimal("1.1")
                costs["diesel_delta_cents_per_litre_ex_gst"]=rounded(delta,"0.0001")
                costs["diesel_change_cents"]=cents(fuel,delta)
                costs["diesel_formula"]="User-supplied litres × (current minus reference wholesale cents/litre) ÷ 1.1 to remove GST. Only the fuel allowance is compared."
        return {"suburb":suburb,"weather":weather,"diesel":diesel,"soil":self.soil(suburb),"cost_scenarios":costs,
            "price_effect":"No public-context adjustment is included in the rate-based estimate. Check existing allowances before considering a separate scenario."}
