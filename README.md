# RevRank

Compare actual cars from listing URLs or pasted descriptions. Review extracted
facts, choose what matters to you, and generate a saved comparison report with
source evidence, meaningful tradeoffs, and questions for each seller.

React + TypeScript frontend · FastAPI backend · local report storage.

## Run locally

Requires Python 3.10+ and Node 18+ (Node 22 recommended for a fresh installation).
From this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
cp .env.example .env
.venv/bin/python scripts/dev.py
```

Skip copying `.env.example` if you already have a configured `.env`.
Open http://127.0.0.1:5173. The API is at http://127.0.0.1:8000/api/health.
Ctrl+C stops both processes. Override ports with `--api-port` and `--web-port`.

For a built single-server run:

```sh
npm --prefix frontend run build
.venv/bin/python scripts/dev.py --built
```

Open http://127.0.0.1:8000. This is a local, single-user prototype with no account
system; do not expose it publicly. Reports may include private user-supplied details.

## First comparison

1. Load the clearly labeled synthetic examples, or paste two listing descriptions.
2. Review and correct prices, units, configuration, and missing information.
3. Generate a report, inspect the evidence, and save/export/print it.

`samples/` contains labeled synthetic text examples for exercising imports.
They are not real listings or market observations.

## Live import and AI

The local ten-site test profile and actual per-site results are in
[US source checks](docs/source-tests/README.md). Enabled means a fetch can be
attempted, not that the website or listing extraction works. Restart the API after
editing `.env`. Re-run the checks with `.venv/bin/python scripts/check_sources.py --live`.

- Live fetching starts disabled. Configure exact reviewed hostnames in
  `REVRANK_ALLOWED_DOMAINS` and set `REVRANK_LIVE_FETCH_ENABLED=true` only after
  establishing appropriate access/reuse rights. Site rules and access checks still
  apply. Unsupported or blocked sources offer pasted-text/manual fallbacks.
- Set `REVRANK_LLM_API_KEY`, `REVRANK_LLM_BASE_URL`, and `REVRANK_LLM_MODEL` to enable
  the optional OpenAI-compatible integration. DeepSeek (`https://api.deepseek.com/v1`,
  `deepseek-flash`) is the configured default; any compatible endpoint works, but it must
  support function calling. The report's AI comparison
  (`backend/app/analyst.py`) gets facts only through tools: reviewed listing fields,
  NHTSA recalls, complaints and 5-Star ratings, and RevRank's own calculations. A
  statement is kept only if it cites tool results from that run and every number in it
  appears in them; unsupported statements are dropped and counted. When the model records
  nothing usable, the report copies fetched tool results into per-car flags, year/spec
  comparisons and seller questions rather than leaving those sections empty. The same gate covers
  the shortlist re-rank: an order is shown only when every position cites its evidence,
  otherwise the deterministic constraint-fit order stands. Small local models (for
  example 3B) mostly fail these checks, so use a capable hosted model.
- Buyer constraints can be typed as a sentence. `/api/constraints` maps language onto the
  preference schema only, and a model mapping is accepted only where it quotes the buyer's
  own words, so it cannot invent a constraint or touch a listing fact. Without a model
  configured, deterministic phrase rules do the same job. See
  [the spec](docs/constraint-chat-cited-rerank.md).
- Pasted URLs may lack `https://` or include surrounding text. VINs in URLs (TrueCar,
  Edmunds, Carfax, Autolist) are read with check-digit validation. Listing ids are read
  for CarMax, Carvana, Autotrader, KBB, Cars.com and CarGurus (`#listing=`).
- `scripts/eval_imports.py` and `scripts/eval_analysis.py` are live self-tests: they
  import real URLs and audit fields or the AI analysis. `eval_imports.py` is a dry run
  that prints the worst-case cost unless given `--spend`.
- Paid providers are metered per month in `.local/usage.json` and refused at
  `REVRANK_MARKETCHECK_MONTHLY_CALLS` / `REVRANK_SEARCH_MONTHLY_CREDITS`; see "Paid API
  budget" in [AGENTS.md](AGENTS.md). The import page's "Recovery source (debug)" switch
  limits recovery to MarketCheck or to search, and shows this month's usage. That meter
  counts only the calls this checkout sent, and on Render `.local/` is on the ephemeral
  filesystem, so a deploy resets it to zero. A provider's own refusal (Tavily HTTP 432,
  MarketCheck HTTP 401/429) is the authoritative signal, and it is reported as such.
- Without an AI key, extraction and reports use explicitly labeled rules-based
  analysis. The app does not pretend to have called an AI model.
- One `POST /api/compare` is bounded by `REVRANK_COMPARE_TIMEOUT_SECONDS` (85s, just under the
  page's own 90s limit) and stops within about 250ms of the page aborting the request. A spent
  budget still returns the deterministic comparison, with the AI path reported unavailable rather
  than invented. Each call is logged under one `X-RevRank-Request-Id`, also returned as a header.
- CarMax (Akamai) and Carvana (Cloudflare challenge) deny RevRank's fetcher on
  every page, not just listings. RevRank does not evade bot managers. After a
  blocked, failed, or thin import it can recover the vehicle from other sources.
  When `REVRANK_BROWSER_RECOVERY_ENABLED` is on (default **off** until Tongli
  opts in; not counsel clearance), a private in-app browse of **only the listing
  URL the buyer pasted** runs first (Playwright; allowlisted VDPs only).
  Licensed inventory and search are secondary (`REVRANK_MARKETCHECK_API_KEY`,
  `REVRANK_SEARCH_PROVIDER`). Active inventory drops a car the moment it stops
  being listed, so when every active lookup is empty one scoped call goes to
  MarketCheck's expired listings (`REVRANK_MARKETCHECK_PAST_INVENTORY_ENABLED`,
  default on). Those rows bind the VIN and show a dated last-listed price; they
  never supply a current price or mileage, and a listing leaving the market is
  never reported as a sale.
  `REVRANK_VIN_DECODE_ENABLED=true` adds a free NHTSA VIN decode that cross-checks
  year/make/model. See [recovery findings](docs/search-pipeline-investigation.md).
- One `POST /api/import` is bounded by `REVRANK_IMPORT_TIMEOUT_SECONDS` (55s) and
  stops when the page aborts, the same way compare does.
- Market evidence is separate from listing extraction. Missing licensed data must
  produce an unavailable state, not fabricated fair-value estimates.
- `.env` and `.local/` are ignored by Git. Keep keys server-side.

The website URLs are evidence inputs, not permission to copy or redistribute
publisher content. User confirmations correct inputs; they do not independently
verify a seller's condition or history claims.

## Verify

```sh
npm --prefix frontend run build
.venv/bin/python -m pytest backend/tests tests -q
```

Network/source checks are separately documented by the testing agent; they are not
part of ordinary offline regression tests.

## Project guide

- [First-version scope](docs/MVP.md)
- [Product brief and original research](docs/PRODUCT_BRIEF.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API contract](docs/API_CONTRACT.md)
- [Frontend agent](docs/agents/frontend.md)
- [Data-processing agent](docs/agents/data-processing.md)
- [Independent testing agent](docs/agents/testing.md)
- [Agent instructions](AGENTS.md)

The application is an initial implementation of the revised URL-to-report journey.
Coverage, pricing accuracy, and launch-market decisions remain under evaluation.
