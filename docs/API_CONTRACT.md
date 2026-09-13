# v0.1 integration contract

React/Vite frontend uses relative `/api` requests, proxied to FastAPI on 8000 in development.
Backend also serves built frontend files for a single-origin local deployment.
JSON field names are snake_case. Nulls represent unknown values. No secret goes to browser.

## Candidate

`id: string; title: string; make/model/trim/generation: string|null; year: number|null;
price: number|null; currency: string; mileage: number|null; mileage_unit: 'mi'|'km';
transmission/location: string|null; features: string[]; history: string|null;
source_url: string|null; source_kind: 'synthetic'|'user'|'listing';
evidence: Record<string, {value: string, source: string, status: 'seller_claim'|'user_confirmed'|'extracted'|'synthetic'}>;
warnings: string[]; verified_fields: string[]`.

Candidate fields editable in frontend. Corrections mark corresponding field user_confirmed;
this confirms user input, NOT independent factual verification of seller claims.

## Endpoints

- `GET /api/health` -> `{status: 'ok', llm_enabled: boolean, market_enabled: boolean}`.
- `GET /api/sources` -> `{sources: [{domain,name,status,reason}], live_fetch_enabled: boolean}`.
  Status strings: allowed, restricted, unreviewed. Restricted/unreviewed do not fetch.
- `GET /api/demo` -> `{candidates: Candidate[]}`. Three clearly synthetic candidates.
- `POST /api/import` body `{url?: string, text?: string}` ->
  `{status: 'success'|'partial'|'restricted'|'unsupported'|'blocked'|'failed', candidate: Candidate|null, message: string}`.
  User text may accompany a URL and is analyzed locally/through configured LLM without fetching URL.
  Operational import failures are structured results; invalid schemas use 422.
- `POST /api/compare` body `{candidates: Candidate[2..3], preferences: Preferences}` -> Report.
- `GET /api/reports` -> `{reports: [{id,title,created_at,analysis_mode}]}`.
- `GET /api/reports/{id}` -> Report; not found 404.

Preferences: `{budget: number|null, annual_mileage: number, ownership_years: number,
location: string, priorities: string[], must_haves: string[]}`.

Report: `{id,created_at,title,summary,analysis_mode: 'llm'|'rules',preferences,candidates,
findings: [{title,detail,candidate_ids: string[],evidence_fields: string[]}],
metrics: [{label,values: string[]}],
questions: [{candidate_id,questions: string[]}],
market: {status: string,message: string,comparables: object[]}, warnings: string[]}`.

LLM explanations are optional via backend configuration and must never replace arithmetic.
Without a key, full deterministic extraction/comparison works and mode is explicitly rules.
No current market observations are fabricated: unconfigured market returns unavailable.
Responses include an honest evidence report even without licensed market access.

## Working boundaries

Frontend agent owns frontend/ and docs/agents/frontend.md.
Backend agent owns backend/ and docs/agents/data-processing.md.
Parent owns root tooling, shared contract, integration and general documentation.
Test agent is spawned after implementation and owns tests/ and docs/agents/testing.md.
