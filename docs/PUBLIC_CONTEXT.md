# Public context and wet-weather scenarios

The public release bundles a separate real rainfall snapshot. Its construction jobs, suppliers, bids and prices remain entirely synthetic.

## Bundled rainfall

The Open-Meteo historical API supplies ERA5 daily precipitation for 2020–2025: 2,192 days across five unique regional grids, 10,960 values, mapped to ten suburb centres. This is regional reanalysis at approximately 25 km resolution, not a site gauge or an archived quote-time forecast. Multiple suburbs share a grid and are not independent observations.

Attribution: Open-Meteo and Copernicus/ECMWF ERA5, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source/query URLs, retrieval time and hashes accompany the snapshot. The release selects regional values and derives scenario summaries; see [NOTICE](../NOTICE).

## Optional adapters

The code retains adapters for [AIP fuel-price data](https://aip.com.au/resources/historical-ulp-and-diesel-tgp-data/) and [CSIRO/ACLEP ASRIS soil screening](https://soils.csiro.au/arcgis/rest/services/ASRIS/NationalSoilGrids/MapServer). Their cached extracts are **not distributed in this release** because source-specific redistribution permission has not been established. An absent source is reported as not imported; no values are fabricated or added to prices.

The optional paths are excluded from Git and Docker build context. Operators must establish applicable reuse terms before downloading, distributing or deploying those extracts. The explicit `python3 -m earthworks.enrich --download` command downloads sources for local evaluation; it never runs automatically at startup and does not establish permission to redistribute them. Source-specific extracts and further licensed sources can be added in an appropriately configured private instance.

Fuel observations, when installed, preserve dates, units, GST basis and source cells. Wholesale prices do not establish supplier fuel consumption or delivered cost. Regional clay maps do not establish rock, contamination, engineering adequacy or recovery time.

## Rain days are not recorded lost workdays

The weather tool distinguishes rain-threshold days, scheduled weekdays potentially affected by rain/recovery, and modelled lost-day equivalents. Actual lost workdays remain unknown. Weekends can affect later recovery exposure and a weekday is never counted twice; public holidays and shutdowns are not removed.

Defaults of 10 mm/day, one recovery day, four lost hours and an eight-hour shift are explicit uncalibrated scenario assumptions. Historical analogue windows must finish before the estimate cutoff. Missing observations invalidate a window instead of becoming zero rain. Whole-year tables are retrospective, not proof of what a historical bidder knew.

A user-supplied daily standby cost can turn exposure scenarios into separate illustrative amounts. Optional fuel scenarios use explicit litres and an installed price difference. Neither is automatically added to quoted rates, and existing allowances must be checked for double counting. Calibrating actual loss requires site diaries, scheduled shifts, stopped hours and task-level evidence.
