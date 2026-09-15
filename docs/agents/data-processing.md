# Data processing agent brief

## Delivered

FastAPI v0.1 backend under `backend/app/`: guarded on-demand fetch, source policy
registry, JSON-LD and conservative text extraction, field evidence/warnings,
synthetic demo candidates, deterministic buyer-aware comparison/report generation,
optional server-side LLM assistance with validation, SQLite report persistence, and
explicit health/source/import/compare/report endpoints.

## Safety and accuracy boundaries

Live fetching is disabled by default and exact operator allowlisting is required.
CarEdge and CarGurus default to restricted; other major sources are unreviewed.
The fetcher checks robots.txt, blocks private/non-public DNS addresses, limits
redirects, time and response size, does not use cookies/proxies/bypass techniques,
and returns structured blocked/unsupported results. No market values are invented.

Without an LLM key reports are explicitly rules-based. Numeric arithmetic stays in
code. Asking prices are not transactions; missing history is not clean history.

`POST /api/compare` is request-scoped: one cancel token (`cancel.py`) carries the
`REVRANK_COMPARE_TIMEOUT_SECONDS` deadline through the deterministic phase and the
optional model work, which run in worker threads so the endpoint can watch for a
client disconnect. An abandoned request starts no further model turn, tool call or
provider request and saves nothing; a spent budget returns the deterministic report
with the AI path reported unavailable or partial, never inferred. Nothing about a
compare is module state, so concurrent compares cannot cancel or time out each other.

## Run and test

From the repository root: `.venv/bin/python -m pytest backend/tests -q`.
Run API with `.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`.
Environment keys are documented in `.env.example`. A MarketCheck key currently
only reports configuration; licensed enrichment is intentionally not fabricated.

## Limitations

URL-import follow-up: unsupported-host messages now identify RevRank as the source
of the restriction. Pasted text takes precedence over a reference URL, makes no
network request, and retains user-input provenance. A regression test covers this
fallback. This change does not enable a live source.

No external live source was enabled during implementation, no arbitrary marketplace
crawler exists, and no custom ML model is trained. URL adapters and market feeds
must be added one at a time after rights and sample quality are reviewed.
