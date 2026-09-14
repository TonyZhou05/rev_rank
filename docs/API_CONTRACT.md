# v0.1 integration contract

React/Vite frontend uses relative `/api` requests, proxied to FastAPI on 8000 in development.
Backend also serves built frontend files for a single-origin local deployment.
JSON field names are snake_case. Nulls represent unknown values. No secret goes to browser.

## Candidate

Core fields:
`id: string; title: string; make/model/trim/generation: string|null; year: number|null;
price: number|null; currency: string; mileage: number|null; mileage_unit: 'mi'|'km';
transmission/body/engine/drivetrain/fuel_type/location: string|null; features: string[]; history: string|null;
source_url: string|null; source_kind: 'synthetic'|'user'|'listing';
evidence: Record<string, {value: string, source: string, status: 'seller_claim'|'user_confirmed'|'extracted'|'synthetic'}>;
warnings: string[]; verified_fields: string[];
retrieval_method: 'direct'|'search'|'licensed'|'registry'|'paste'|'synthetic';
observations: Observation[]; conflicts: string[]`.

Recovery fields (populated during listing recovery):
- `observations: [{field, value, source_url, retrieved_at, observed_at?, method, vin?}]` - Source observations collected during recovery
- `conflicts: string[]` - Fields where sources disagree

MSRP fields (buyer-entered only):
- `msrp: number|null` - Original MSRP; buyer-entered and user_confirmed ONLY, NEVER scraped/LLM/MarketCheck filled
- `percent_of_msrp: number|null` - Derived at compare time as `(price/msrp)*100`; NOT user-editable input
  - Computed only when: price and msrp are both set, currency is not UNK, and msrp is in verified_fields
  - Otherwise null
- MSRP must be in verified_fields to be used in calculations (ensures buyer manually confirmed)

Days-on-market fields (from licensed inventory payload only):
- `dom: number|null` - Days on market from MarketCheck; null for search/direct/paste recovery
- `dom_active: number|null` - Active days on market from MarketCheck; null otherwise
- `first_seen_at: string|null` - First seen date from MarketCheck; null otherwise
- These fields are populated ONLY from already-fetched MarketCheck payload; 0 extra paid calls

NHTSA safety data (attached at compare time):
- `nhtsa_safety: object|null` - Model-year safety data (not VIN-specific); see NHTSASafetyData schema

Candidate fields editable in frontend. Corrections mark corresponding field user_confirmed;
this confirms user input, NOT independent factual verification of seller claims.

## Endpoints

- `GET /api/health` -> `{status: 'ok', llm_enabled: boolean, market_enabled: boolean, api_revision: number, ...}`.
- `GET /api/sources` -> `{sources: [{domain,name,status,reason}], live_fetch_enabled: boolean}`.
  Source status strings: `allowed | restricted | unsupported` (not "unreviewed"). Restricted/unsupported do not fetch.
  Note: Local allowlist ≠ reuse license; verify source-specific rights before integration.
- `GET /api/demo` -> `{candidates: Candidate[]}`. Three clearly synthetic candidates.
- `POST /api/import` body `{url?: string, text?: string, vin?: string, recover?: boolean, recovery_source?: 'auto'|'marketcheck'|'search'}` ->
  ImportResponse (see below).
  User text may accompany a URL and is analyzed locally/through configured LLM without fetching URL.
  Operational import failures are structured results; invalid schemas use 422.
- `POST /api/compare` body `{candidates: Candidate[2..3], preferences: Preferences}` -> Report.
- `GET /api/reports` -> `{reports: [{id,title,created_at,analysis_mode}]}`.
- `GET /api/reports/{id}` -> Report; not found 404.

### ImportResponse

```
{
  status: 'success'|'partial'|'restricted'|'unsupported'|'blocked'|'failed',
  candidate: Candidate|null,
  message: string,
  attempts: RetrievalAttempt[],
  recovery_status: RecoveryStatus|null
}
```

**recovery_status** (frozen vocabulary):
- `recovered` - Successfully recovered from licensed inventory or search
- `identity_only` - Only NHTSA VIN decode succeeded; listing details unknown
- `identity_conflict` - Sources disagree on VIN or identity
- `not_found` - No matching listing found
- `not_listing` - URL is a search/category page, not a single listing
- `failed` - Recovery attempted but provider error occurred
- `disabled` - Recovery was disabled or URL invalid for recovery
- `unavailable` - No recovery provider configured
- `null` - Recovery not attempted or not applicable

**RetrievalAttempt**: `{method: string, status: string, detail: string}`

### Badge suggestions for recovery_status (Frontend owns final copy)

| recovery_status    | Suggested badge | Color   |
|--------------------|-----------------|---------|
| recovered          | "Recovered"     | green   |
| identity_only      | "VIN Only"      | yellow  |
| identity_conflict  | "Conflict"      | red     |
| not_found          | "Not Found"     | gray    |
| not_listing        | "Not a Listing" | orange  |
| failed             | "Failed"        | red     |
| disabled           | "Disabled"      | gray    |
| unavailable        | "Unavailable"   | gray    |

Preferences: `{budget: number|null, annual_mileage: number, ownership_years: number,
location: string, priorities: string[], must_haves: string[]}`.

### Report

```
{
  id: string,
  created_at: string,
  title: string,
  summary: string,
  analysis_mode: 'llm'|'rules',
  preferences: Preferences,
  candidates: Candidate[],
  findings: Finding[],
  metrics: Metric[],
  questions: Questions[],
  market: Market,
  warnings: string[],
  ai_analysis: AIAnalysis|null,
  cross_model: boolean,
  nhtsa_data: Record<candidate_id, NHTSASafetyData>
}
```

**cross_model**: `true` if any make/model differs across candidates (case-insensitive comparison).

**nhtsa_data**: Keyed by candidate id; contains model-year safety data for each candidate.

### NHTSASafetyData

```
{
  scope: "Model-Year Safety Data (not VIN-specific)",  // Fixed label, always present
  year: number|null,
  make: string|null,
  model: string|null,
  recalls_count: number|null,
  complaints_count: number|null,
  overall_rating: string|null,
  frontal_rating: string|null,
  side_rating: string|null,
  rollover_rating: string|null,
  vehicle_url: string|null,        // https://www.nhtsa.gov/vehicle/{VehicleId}; null when unrated
  recalls: NHTSARecall[],          // up to 5; counts above stay full
  complaints: NHTSAComplaint[]     // up to 5; counts above stay full
}

{  // NHTSARecall
  campaign_number: string,
  component: string,
  summary: string,
  report_date: string|null,
  url: string|null                 // https://www.nhtsa.gov/recalls?nhtsaId={campaign_number}
}

{  // NHTSAComplaint
  odi_number: string,
  component: string,
  summary: string,
  date_filed: string|null,
  url: string|null                 // null: NHTSA publishes no per-ODI permalink, so the UI
}                                  // links complaints through vehicle_url or nhtsa.gov/recalls
```

This is model-year level data from NHTSA. VIN-level recall status is OUT OF SCOPE.
Never invent counts; null means data unavailable.

### Metrics

Standard metrics include:
- Asking price, Budget headroom, Model year
- Mileage as supplied, Mileage normalized to km
- Transmission, Engine, Drivetrain, Body, Fuel Type
- Generation / trim, Location
- Projected odometer (when units match)
- Must-have: {item} (for each must_have)
- **% of original MSRP (you entered)**: Calculated as `price/msrp*100` when:
  - Both price and msrp are set
  - msrp is in verified_fields (user confirmed)
  - Currency is known and matches
  - Otherwise shows "N/A" or "MSRP not confirmed"

LLM explanations are optional via backend configuration and must never replace arithmetic.
Without a key, full deterministic extraction/comparison works and mode is explicitly rules.
No current market observations are fabricated: unconfigured market returns unavailable.
Responses include an honest evidence report even without licensed market access.

## Working boundaries

Frontend agent owns frontend/ and docs/agents/frontend.md.
Backend agent owns backend/ and docs/agents/data-processing.md.
Parent owns root tooling, shared contract, integration and general documentation.
Test agent is spawned after implementation and owns tests/ and docs/agents/testing.md.
