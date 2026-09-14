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
3. Set your budget, priorities, and must-have features.
4. Generate a report, inspect the evidence, and save/export/print it.

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
  the optional OpenAI-compatible integration. No specific vendor/model is required, but
  it must support function calling. The report's AI comparison
  (`backend/app/analyst.py`) gets facts only through tools: reviewed listing fields,
  NHTSA recalls, complaints and 5-Star ratings, and RevRank's own calculations. A
  statement is kept only if it cites tool results from that run and every number in it
  appears in them; unsupported statements are dropped and counted. Small local models
  (for example 3B) mostly fail these checks, so use a capable hosted model.
- Pasted URLs may lack `https://` or include surrounding text. VINs in URLs (TrueCar,
  Edmunds, Carfax, Autolist) are read with check-digit validation. Listing ids are read
  for CarMax, Carvana, Autotrader, KBB, Cars.com and CarGurus (`#listing=`).
- `scripts/eval_imports.py` and `scripts/eval_analysis.py` are live self-tests: they
  import real URLs and audit fields or the AI analysis. `eval_imports.py` is a dry run
  that prints the worst-case cost unless given `--spend`.
- Paid providers are metered per month in `.local/usage.json` and refused at
  `REVRANK_MARKETCHECK_MONTHLY_CALLS` / `REVRANK_SEARCH_MONTHLY_CREDITS`; see "Paid API
  budget" in [AGENTS.md](AGENTS.md). The import page's "Recovery source (debug)" switch
  limits recovery to MarketCheck or to search, and shows this month's usage.
- Without an AI key, extraction and reports use explicitly labeled rules-based
  analysis. The app does not pretend to have called an AI model.
- CarMax (Akamai) and Carvana (Cloudflare challenge) deny RevRank's fetcher on
  every page, not just listings. RevRank does not evade bot managers. After a
  blocked import it can recover the vehicle from other sources. Licensed inventory
  runs first (`REVRANK_MARKETCHECK_API_KEY`: listing URL, stock number, VIN, with
  provider dates). Search runs next (`REVRANK_SEARCH_PROVIDER`, `REVRANK_SEARCH_API_KEY`).
  `REVRANK_VIN_DECODE_ENABLED=true` adds a free NHTSA VIN decode that cross-checks
  year/make/model. See [recovery findings](docs/search-pipeline-investigation.md).
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
