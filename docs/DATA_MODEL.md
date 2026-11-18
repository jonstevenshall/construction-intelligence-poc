# Data model and assumptions

- `Project`: invented site address/coordinates, tender date, planned start, total property area, disturbed fraction, average excavation depth, scope quantities, hypothetical ground conditions and separate disposal/fill endpoints.
- `Vendor`: fictional name, depot, price-factor parameter, deposit policy, capacity parameter, hypothetical year-end policy and optional shutdown.
- `Quote`: project/vendor IDs, date, revision, validity, currency, submitted price and tax display basis, normalised ex-GST and gross totals, priced options, deposit percentage/basis/amount, terms and source references.
- `QuoteLine`: canonical scope item, zone, description, quoted versus required quantity, unit, integer-cent rate and amount, inclusion status, bundled-in line reference and evidence line.
- `Document`: generated original Markdown, stable ID and SHA-256 hash.
- `Chunk`: project/date/quote metadata, source line, text, index version and 384-dimensional vector.
- `ContextEdge`: source entity, relationship, destination entity and supporting document line.
- `PublicContext`: pending typed references with effective/publication/retrieval dates, spatial coverage, units, licence, observed/modelled status and transformation metadata.
- `EvaluationCase`: deterministic expected amounts and flags for the synthetic corpus.
- `DatasetVersion`: immutable source manifest, purpose/type/kind, declared field definitions, dates and import digest.
- `DatasetRecord`: arbitrary original JSON facts, source/locator/hash, dates and versioned lexical-vector projection.
- `DatasetEntity`: exact record-to-entity references; graph views add dataset membership and source links without inventing identity matches.
- `DatasetUpload`: original UTF-8 upload bytes, filename and SHA-256, committed atomically with records/index/links.

## Money and scope

All stored money is AUD integer cents. Line rates and amounts are ex GST; the quote explicitly states whether the submitted display includes GST. GST is rounded to cents on the contract subtotal. Optional items are excluded from the submitted total and separately priced. Deposits apply to each supplier's own submitted gross contract sum, excluding options.

Excluded and rate-only work has no known included amount. A zero in the amount column is a bookkeeping exclusion, not evidence that completing the work costs nothing. An included-elsewhere line has no independent rate allocation and points to its covering lump sum. Provisional rock is a stated allowance, not a fixed commitment for the entire required quantity.

## Fictional geography and distances

Addresses contain DEMO lot IDs and imaginary road names. Coordinate points are invented near named suburbs; they are not verified properties or geocoded addresses. The distance model uses great-circle distance × 1.30 as an explicit road proxy. It does not certify routes, truck access, facility acceptance or transit time.

Depot-to-site, site-to-disposal and fill-source-to-site are separate. The synthetic generator applies different explicit coefficients to mobilisation and material haul. These coefficients are demonstration assumptions, not observed commercial rates.

## Calendar and pricing generation

Calendar year-end is 31 December; financial year-end is 30 June. Supplier-specific synthetic policies can apply an already-incorporated 3% conditional discount or 4% capacity premium near either boundary, or no adjustment. Conditions are printed in the bid. The separate date-trend factor, soil factor and vendor factor are simulation parameters and do not prove real pricing causality.

Public weather and other context fields are null until actual observations are imported with provenance. A quote-date forecast, seasonal climatology, quote-date observation and later actual work-period observation are different record types.
