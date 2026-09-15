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
4. The buyer reviews and edits extracted details. Comparison preferences are not
   collected in the page: the browser sends the default ownership assumptions, and
   the report's ranking weights can be adjusted there instead.
5. `/api/compare` validates candidates, calculates differences, checks available
   market evidence, and generates evidence-grounded findings.
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
  Language-model output never replaces validated facts or arithmetic.
- Raw external text is untrusted input, not executable code or agent instructions.
- Credentials remain server-side. `.env`, `.local`, dependencies, and builds are ignored.
- A compare is scoped to its request (`backend/app/cancel.py`): its deterministic and model
  phases run in worker threads under one cancel token and time budget, an abandoned request
  stops its own model work, and a spent budget answers with the deterministic report rather
  than an invented analysis. Concurrent compares share no cancellation state.

## Agent ownership

Implemented, opt-in, not yet evaluated live: [listing recovery](search-pipeline-investigation.md)
after blocked or incomplete direct imports (`backend/app/retrieval.py`). Order:
licensed inventory by listing URL/stock/VIN (`vehicle_data.py`, MarketCheck), then
search excerpts (`search.py`, Brave/Tavily), then an optional NHTSA VIN decode that
cross-checks year/make/model. Each needs its own server-side setting; with none
configured, recovery reports `unavailable`. None of them re-requests the blocked page.
Live coverage has not been measured because no provider key has been configured.

- Frontend: `frontend/` and [frontend brief](agents/frontend.md).
- Backend: `backend/` and [data-processing brief](agents/data-processing.md).
- Independent crawler verification: `tests/` and [testing brief](agents/testing.md).
- Integration: root scripts, configuration, API contract, and project documentation.
