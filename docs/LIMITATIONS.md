# Status and limitations

- Corpus: synthetic, generated from explicit assumptions. No source PDF or actual supplier data is redistributed.
- Forecasts: scenario envelopes, not calibrated market estimates or statistical intervals. Scope quantities are a simplified geometric model.
- Question selection: deterministic sensitivity over three bounded uncertainties. It does not incorporate investigation cost, real priors or every site risk.
- AI: the earlier conversational integration was live-tested. The expanded calculation, persistent estimate and general web-search workflow has offline regression coverage; a live Coolify smoke test must be recorded separately. It is disabled by default and needs a server-side key. Model allowances and confidence are qualitative judgements; no pricing model has been trained or fine-tuned.
- Vectors: lexical hashing baseline; no claim of neural semantic retrieval quality. A true embedding model must be evaluated before replacing it.
- Context graph: explicit relationships with source references; not a complete causal graph or a record of unobserved reasoning.
- Public context: Attributed ERA5 rainfall is bundled separately. Fuel and soil adapters remain available, but their extracts are not included in the public release pending source-specific reuse verification. Rainfall is not a measured work stoppage; soil mapping is not site geotechnical evidence. Historical snapshots do not prove quote-time data vintages.
- Distance: simulated road proxy, not an actual route. No facility acceptance or heavy-vehicle compliance assertions.
- Extensibility: a common versioned JSONL evidence importer, catalogue and read-only search tool work across arbitrary fact fields. Existing bid/weather/fuel/soil calculators still have their own typed paths; they have not all been migrated to the common envelope. An arbitrary new source needs a mapping into the contract, and useful financial transformations still require validation.
- Scale: one synthetic portfolio, synchronous ingestion, some in-memory quote processing and exact vector ranking. The adapter proves schema/prompt independence, not throughput. No multitenant isolation, billion-quote performance proof or production availability claim.
- Deployment: Docker/Coolify files are provided. GitHub publication and actual webspace deployment are separate actions with separately verified status.
