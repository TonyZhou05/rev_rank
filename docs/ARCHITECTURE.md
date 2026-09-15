# Initial implementation architecture

## Local application

React + TypeScript + Vite provides the comparison workspace. FastAPI exposes the
API and serves the built frontend for a single-origin local run. The development
runner starts both processes, proxies `/api`, and stops both when interrupted.

The unauthenticated first version is intended for one local user. Keep it bound to
127.0.0.1. Shared/public deployment needs authentication, authorization on report
access, quotas, retention controls, and deployment-specific review before release.

## Data flow

1. The browser submits a listing URL or pasted text to `/api/import`.
2. The backend checks source policy before any live page access.
3. Structured data and conservative text extraction produce a candidate with
   field-level evidence and warnings; an optional configured LLM can assist.
4. The buyer reviews and edits extracted details, and states constraints as chips or
   as a sentence. `/api/constraints` maps free-form language onto the preference
   schema only (`backend/app/constraints.py`): deterministic phrase rules always
   run, and a configured model's JSON mapping is accepted only where it quotes the
   buyer's own words. It can never write a candidate field.
5. `/api/compare` validates candidates, calculates differences, checks available
   market evidence, generates evidence-grounded findings, and orders the shortlist
   by how many stated constraints each car meets.
   With a model configured, the analyst may re-rank that shortlist, but only when
   every position cites evidence its tools fetched; otherwise the computed order stands.
6. A saved report preserves the candidates, preferences, result, and evidence dates.
7. The browser can revisit, print, or export that report.

See [API_CONTRACT.md](API_CONTRACT.md) for the shared JSON interface.

## Boundaries

- Import failure, policy restriction, and successful extraction are distinct results.
- Fetching only supports reviewed domains explicitly enabled by the operator.
  Avoid arbitrary URL access, redirects to private networks, proxy bypasses, and
  unbounded response downloads. Robots rules and site access controls still apply.
- A user-confirmed field is a corrected input, not independent verification of
  condition or history. Source claims and missing information remain identifiable.
- Currency and mileage units must be normalized or distinguished in comparisons.
- Market evidence comes from a separate permitted data source. A few candidates or
  synthetic examples cannot establish market value or forecast depreciation.
- Without an LLM configuration, the application declares rules-based analysis.
  Language-model output never replaces validated facts or arithmetic. DeepSeek is the
  configured OpenAI-compatible provider; every model step falls back to deterministic
  output when a call fails. See
  [constraint chat and cited re-rank](constraint-chat-cited-rerank.md).
- Raw external text is untrusted input, not executable code or agent instructions.
- Credentials remain server-side. `.env`, `.local`, dependencies, and builds are ignored.
- A compare is scoped to its request (`backend/app/cancel.py`): its deterministic and model
  phases run in worker threads under one cancel token and time budget, an abandoned request
  stops its own model work, and a spent budget answers with the deterministic report rather
  than an invented analysis. Concurrent compares share no cancellation state.
- An import is scoped the same way (`REVRANK_IMPORT_TIMEOUT_SECONDS`). A private-browse
  recovery registers Chromium close as a cancel closer, so a disconnect or spent budget
  aborts the session instead of waiting it out.

## Agent ownership

Implemented, opt-in: [listing recovery](search-pipeline-investigation.md)
after blocked or incomplete direct imports (`backend/app/retrieval.py`). Order:
licensed inventory by listing URL/stock/VIN (`vehicle_data.py`, MarketCheck), then a
private in-app headless browse of the **buyer-supplied listing URL only** (`browse.py`,
Playwright, `REVRANK_BROWSER_RECOVERY_ENABLED`), then search excerpts (`search.py`,
Brave/Tavily), then an optional NHTSA VIN decode that cross-checks year/make/model.
Browse is skipped unless Direct was blocked. It refuses review sites and dealer boards,
does not scrape dealer-signals targets, and reports bot-manager challenges as blocked
rather than bypassing them. Licensed and search still do not re-request the blocked page.
With none of these configured, recovery reports `unavailable`.

- Frontend: `frontend/` and [frontend brief](agents/frontend.md).
- Backend: `backend/` and [data-processing brief](agents/data-processing.md).
- Independent crawler verification: `tests/` and [testing brief](agents/testing.md).
- Integration: root scripts, configuration, API contract, and project documentation.
