# Construction Intelligence Lab

An **AI agent concept that helps non-specialists get indicative construction cost estimates** from a rough description of the work.

[Try the public simulation](https://earthworks.stevens-hall.com/).

The problem is bigger than comparing bids. An early brief is incomplete, the user may not know the technical vocabulary, and local conditions, restrictions and extra costs can change what needs to be allowed for. The agent explores those gaps, explains them in ordinary language and develops a provisional cost range as the conversation progresses.

It can:

- Ask useful clarifying questions and use labelled assumptions when the user does not know an answer.
- Calculate quantities and alternative scenarios from approximate descriptions.
- Search quotation evidence and investigate relevant local context, restrictions and public cost information.
- Explain why a finding matters and explore an additional cost allowance when appropriate.
- Keep the range, qualitative input confidence, priced scope and unpriced items visible.
- Show sources and a short explanation of how it reached each result.

**Earthworks is the first example dataset, not the limit of the concept.** The 300 projects, 50 suppliers, 1,000 quotations and their prices are synthesised. They demonstrate different scopes, terms, omissions and pricing structures; they are not real contractor offers or evidence of market accuracy. Without representative real quotation data and validation, this remains a concept demonstration rather than a calibrated estimator.

Historical rainfall is a separate, attributed public dataset. Fuel and soil adapters remain in the code, but their source extracts are not distributed with this release. A regional finding does not establish property-specific compliance or clearance.

## Try it

Describe work you are considering, such as levelling a sloping play area. The agent should make progress with rough dimensions and explicit assumptions rather than require a survey or technical identifiers before providing an indicative scenario.

The public demo has no visitor access token. All visitors share a **US$3 lifetime application-side model allowance**, including public-search costs, stored in a persistent ledger. When it is used, paid requests stop; the evidence and data model remain browsable. Stored datasets are read-only in the public instance. New structured files can be previewed without being saved.

## Run locally

Python 3.11+; no packages, Docker or API key are required for the offline tools:

```sh
python3 -m earthworks.app
```

Open [localhost:8765](http://localhost:8765). Paid model calls are disabled unless configured. To use live chat, set `OPENAI_API_KEY`, `LLM_ENABLED=true` and `OPENAI_MODEL=gpt-6-luna` in an ignored local `.env` or secret store. Never place an API key in browser code.

`PUBLIC_DEMO=true` enables anonymous use, a fixed shared US$3 ledger and read-only stored evidence. Private mode keeps token authentication and dataset imports; configure `DEMO_ACCESS_TOKEN` with at least 24 characters before exposing private mode or enabling paid calls there. See [deployment](docs/DEPLOYMENT.md).

## What is built

A small Python server, browser UI and an agent with bounded tools for reasoning, arithmetic, evidence retrieval, public research and component costing. The model chooses what to investigate; deterministic tools calculate totals and preserve referenced quotation rates. No pricing model is trained or fine-tuned.

PostgreSQL/pgvector is used for deployment, with SQLite for local development. Exact commercial values and relationships sit alongside versioned JSON evidence and retrieval projections. The current 384-dimensional vectors use lexical hashing, not neural semantic embeddings.

The Data tab shows actual structures and lets an operator describe a new dataset's objective, field meanings, units, coded values and entity links. CSV/JSON/JSONL imports are previewed and validated before records, original files, indexes and graph links are committed together. The same agent tools discover new sources without a source-specific question handler. Undefined semantics remain unknown; an import does not automatically install a pricing formula or regulatory rule.

This proves a small workflow and an extensible evidence contract. It does not demonstrate production-scale performance, exhaustive regulatory research, calibrated confidence or construction-domain accuracy.

## Checks

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
python3 -m earthworks.evaluate --demo
```

The evaluation uses deliberately flawed synthetic observations to exercise discrepancy detection; it is not a test of an external product. CI also exercises PostgreSQL/pgvector.

Read [architecture](docs/ARCHITECTURE.md), [evidence and scale](docs/EVIDENCE_PLATFORM.md), [data model](docs/DATA_MODEL.md), [test plan](docs/TEST_PLAN.md), [public context](docs/PUBLIC_CONTEXT.md) and [limitations](docs/LIMITATIONS.md).

## Source availability and commercial licensing

Required Notice: Copyright 2026 Jon Hall (https://github.com/jonstevenshall)

The application code and generated construction corpus are **source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE)**. Noncommercial use is permitted subject to its terms. Commercial use requires a separate agreement; commercial licensing or acquisition enquiries can be directed to [Jon Hall](https://github.com/jonstevenshall).

This is not a permissive open-source release. The licence governs reuse of the work; it does not reserve the underlying idea. Third-party data retains its own terms, recorded in [NOTICE](NOTICE).
