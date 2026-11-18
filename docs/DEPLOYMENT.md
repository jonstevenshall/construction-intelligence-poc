# Deployment

## Public Coolify demo

Use Docker Compose, branch `main`, base directory `/`, Compose location `/compose.coolify.yaml`, and route the app service to internal port `8765`. Configure `POSTGRES_PASSWORD` at runtime. Keep both `postgres-data` and `app-state` volumes persistent. The database has no public port.

The supplied Coolify configuration explicitly enables `PUBLIC_DEMO=true`. Visitors can enter the simulation without an access token, even if an old `DEMO_ACCESS_TOKEN` remains configured. Stored evidence is read-only, private-kind datasets are excluded from public evidence paths, and import previews cannot commit records.

For live chat configure `LLM_ENABLED=true`, `OPENAI_MODEL=gpt-6-luna` and a server-side `OPENAI_API_KEY`. No key is included in Git, Docker build context or browser code. `LLM_ENABLED=false` sends no provider requests.

Public model spend uses `var/public-demo-usage.sqlite`, shared by all visitors and persisted in `app-state`. The public ceiling is fixed at US$3 lifetime and US$3 per UTC day. Private-mode budget environment variables cannot raise it. Reservations are atomic and survive uncertain provider outcomes; restarting the app does not reset the allowance. Concurrent conversations share the same atomic spend ledger; visitors do not block each other behind a single-user gate. Exhausting the allowance stops paid requests while read-only exploration remains available. This is an application-side control using the recorded conservative Standard pricing schedule, not a change to the provider account's billing settings.

After deployment verify `/health` and anonymous `/api/status`, then enter from a fresh browser session. Confirm there is no visitor token prompt and that `/api/data/import` returns 403. Retain health checks and the startup grace period.

## Private/local use

Run `python3 -m earthworks.app` for loopback-only offline tools. Set `PUBLIC_DEMO=true` in the ignored local `.env` to use public-mode behaviour locally. To enable private imports, use `PUBLIC_DEMO=false`; paid private mode or a non-loopback private bind requires a `DEMO_ACCESS_TOKEN` of at least 24 characters. The private ledger remains `var/usage.sqlite`, with independently configured lifetime/daily settings.

The local Compose file defaults to public-demo mode and exposes the app on loopback only. Edit the deployment's `PUBLIC_DEMO` setting deliberately when choosing private mode. Use secret storage rather than committing environment values.

## Agent and data boundaries

A chat turn permits at most four main model requests, one optional public-search helper and one explanation-only repair. There are no model upgrades or automatic retries of uncertain HTTP failures. Requests are capped at 64,000 input bytes and 4,096 output tokens. Hosted-search fees and a conservative search-context reservation are included before a request is sent.

Versioned sources under `data/datasets/` load at startup. Private instances can use the Data tab to preview and commit structured imports, or run `python3 -m earthworks.datasets PATH`. The agent itself has read-only evidence tools. Source extracts without established redistribution terms are not bundled; see [public context](PUBLIC_CONTEXT.md).
