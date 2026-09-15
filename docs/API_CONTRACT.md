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

MSRP fields (buyer-entered or decoded from the VIN):
- `msrp: number|null` - Original (factory) MSRP. Two sources only: the buyer, or a MarketCheck NeoVIN
  decode of a known 17-character VIN. Never scraped from a page, never LLM-suggested, and never a
  listing's own `msrp` from inventory search (that figure often just repeats the asking price).
- `percent_of_msrp: number|null` - Derived at compare time as `(price/msrp)*100`; NOT a user-editable input
  - Computed only when: price and msrp are both set, currency is not UNK, and the MSRP is *sourced*
  - Otherwise null
- An MSRP is *sourced* when `msrp` is in `verified_fields` (the buyer entered or confirmed it), or when
  `evidence.msrp.source` starts with `MarketCheck NeoVIN` (status `extracted`)
- NeoVIN fill is a suggestion, not a verified fact: it stays editable, and a buyer edit replaces it and
  marks the field `user_confirmed`. An existing MSRP is never overwritten by a decode.
- `evidence.msrp.source` grammar for a decode, which the UI reads for its label:
  `MarketCheck NeoVIN <oem_msrp|original_msrp|combined_msrp> for VIN <VIN>; …`, or
  `MarketCheck NeoVIN msrp labeled <oem_msrp|original_msrp> for VIN <VIN>; …`
- The decode also appends one `observations` entry (`field: "msrp"`, `method: "licensed"`) whose
  `source_url` is the decode endpoint without its API key

Days-on-market fields (from licensed inventory payload only):
- `dom: number|null` - Days on market from MarketCheck; null for search/direct/paste recovery
- `dom_active: number|null` - Active days on market from MarketCheck; null otherwise
- `first_seen_at: string|null` - First seen date from MarketCheck; null otherwise
- These fields are populated ONLY from already-fetched MarketCheck payload; 0 extra paid calls

NHTSA safety data (attached at compare time):
- `nhtsa_safety: object|null` - Model-year safety data (not VIN-specific); see NHTSASafetyData schema

Dealer fields (from the licensed inventory payload only):
- `dealer: DealerInfo|null` - The selling business as the MarketCheck record described it; see DealerInfo
  below. Populated ONLY from a payload already fetched for the listing: 0 extra paid calls, nothing
  scraped, and no review site read.

Candidate fields editable in frontend. Corrections mark corresponding field user_confirmed;
this confirms user input, NOT independent factual verification of seller claims.

## Endpoints

- `GET /api/health` -> `{status: 'ok', llm_enabled: boolean, llm_model: string, llm_endpoint_host: string,
  market_enabled: boolean, api_revision: number, licensed_inventory_enabled: boolean,
  vin_decode_enabled: boolean, neovin_msrp_enabled: boolean, usage: {...}}`.
  `llm_model` and `llm_endpoint_host` name the configured model (DeepSeek by default); the API key
  is never exposed.
- `GET /api/sources` -> `{sources: [{domain,name,status,reason}], live_fetch_enabled: boolean}`.
  Source status strings: `allowed | restricted | unsupported` (not "unreviewed"). Restricted/unsupported do not fetch.
  Note: Local allowlist ≠ reuse license; verify source-specific rights before integration.
- `GET /api/demo` -> `{candidates: Candidate[]}`. Three clearly synthetic candidates.
- `POST /api/import` body `{url?: string, text?: string, vin?: string, recover?: boolean, recovery_source?: 'auto'|'marketcheck'|'search'}` ->
  ImportResponse (see below).
  User text may accompany a URL and is analyzed locally/through configured LLM without fetching URL.
  Operational import failures are structured results; invalid schemas use 422.
  When the import ends with a known VIN (pasted, read from the URL, shown on the page, or bound during
  recovery) and `neovin_msrp_enabled`, one MarketCheck NeoVIN decode fills `candidate.msrp`. It runs once
  per import, is skipped when an MSRP is already present, and is reported as a `licensed` attempt.
  `recovery_source: 'search'` suppresses it, like every other MarketCheck call.
- `POST /api/constraints` body `{message: string, preferences?: Preferences}` -> ConstraintResponse.
  Maps free-form buyer language onto Preferences and nothing else; it never returns a vehicle fact.
- `POST /api/compare` body `{candidates: Candidate[2..3], preferences: Preferences}` -> Report.
  Cancellable and time-bounded; see "Compare cancellation and timeout" below.
- `GET /api/reports` -> `{reports: [{id,title,created_at,analysis_mode}]}`.
- `GET /api/reports/{id}` -> Report; not found 404.

### Compare cancellation and timeout

Every response carries `X-RevRank-Request-Id` (16 hex characters, one per call, exposed through CORS).
It is the only identifier the server logs for a compare, so a client retry is distinguishable from
the attempt it replaced. It is not a report id and is not persisted.

One request-scoped budget covers both compare phases: `REVRANK_COMPARE_TIMEOUT_SECONDS`, 85s by
default, just under the page's own 90s compare limit. `GET /api/health` reports the configured value
as `compare_timeout_seconds`, so the page can align its own limit.

- **Client abort.** When the page aborts the fetch, the server notices the disconnect within about
  250ms and stops the work: no further model turn, tool call or provider request starts, an in-flight
  model stream is closed rather than waited out, and no report is saved. The status is `499`
  (`{detail}`), which the aborted client never reads.
- **Budget spent.** The deterministic comparison, metrics, evidence and NHTSA data are returned as
  usual with `200`, `analysis_mode: 'rules'`, and `ai_analysis.status: 'unavailable'` whose `message`
  says the analysis stopped at the server time limit. Nothing is inferred from the unfinished run.
  A partial run that already validated findings keeps them with `ai_analysis.status: 'partial'` and
  says so in `message`. The report is saved like any other.
- **Budget spent before the comparison exists.** `503` with `{detail}`; nothing invented, safe to retry.
- Optional NHTSA model-year enrichment is skipped (`nhtsa_data` omits that candidate) rather than
  spending the whole budget before the analysis; the deterministic comparison is unaffected.
- Concurrent compares share no cancellation state, model client or connection: each call owns its
  token and works on its own copy of the report.

The page needs no request header for any of this: the id is generated per call server-side, and the
abort is the HTTP disconnect itself.

Abort detection depends on the disconnect reaching the API process. Uvicorn serving the built page
delivers it directly. An intermediate proxy may not: Vite's dev proxy keeps the upstream request open
when the browser aborts, because the proxy it bundles only reacts to a Node event that stops firing
once the request body has arrived, so `frontend/vite.config.ts` forwards the abort explicitly. Where
a proxy cannot be taught that, the time limit is the backstop rather than the abort, which is why the
server enforces its own budget instead of trusting the disconnect.

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
location: string, priorities: string[], must_haves: string[], max_mileage: number|null,
transmission: 'manual'|'automatic'|null, excludes: string[]}`.

`max_mileage` (odometer ceiling in the listing's own unit), `transmission` and `excludes` are
optional with defaults, so an older page that omits them still validates.

### ConstraintResponse

```
{
  mode: 'llm'|'rules',              // 'rules' whenever the model is absent or failed validation
  preferences: Preferences,         // validated; the only thing this endpoint may write
  constraints: Constraint[],
  reply: string,                    // composed from the accepted constraints, never model prose
  unmapped: string[],               // phrases from the message that were not mapped
  notes: string[]                   // which layer ran, and why the model result was discarded
}

{  // Constraint
  field: 'budget'|'annual_mileage'|'ownership_years'|'max_mileage'|'transmission'|'location'
       |'must_haves'|'excludes'|'priorities',
  label: string,
  value: string,                    // display text, e.g. "32,000" or "all-wheel drive"
  quote: string,                    // contiguous phrase from the buyer's own message
  source: 'rules'|'llm'
}
```

A model-proposed constraint is accepted only if `field` is one of the nine above, `quote` is a
contiguous substring of the message, and a numeric value is recoverable from its own quote (the
digits of the value, of value/1000, or of value/100 appear in the quote). One unusable item
discards the whole model result: `mode` returns `rules` and `notes` says so. The endpoint can never
write a Candidate field.

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
  nhtsa_data: Record<candidate_id, NHTSASafetyData>,
  shortlist: ShortlistEntry[]
}
```

### ShortlistEntry

Deterministic constraint-fit order, always present, and what the report shows when the model has no
ranking. There is no composite score: `checks` is the whole basis for a position.

```
{
  candidate_id: string,
  position: number,                 // 1-based
  meets: number,
  conflicts: number,
  open_items: number,               // not_established + unknown
  checks: ConstraintCheck[],
  rationale: string                 // states that this is constraint fit, not a value judgement
}

{  // ConstraintCheck
  field: ConstraintField,
  constraint: string,               // e.g. "Budget 26,000"
  status: 'meets'|'conflicts'|'not_established'|'unknown',
  detail: string
}
```

`not_established` means the listing is silent; it is never displayed as "no" and never counts as
met. `unknown` means the field is missing, disputed between sources, or in an unusable unit.

Ordering: conflicts ascending, then `open_items` ascending, then `meets` descending, then the lower
asking price when every price is comparable, then input order. With no constraints stated, the input
order stands and no price tiebreak is applied.

Constraint metric rows added to `metrics` when the matching preference is set: `Mileage ceiling: {n}`
(`within|over|unknown`), `Transmission wanted: {manual|automatic}` (`matches|does not match|unknown`),
`Exclude: {item}` (`present|listing denies it|not established`), and `Constraint fit`
(`{n} met · {n} open · {n} conflicting`).

**AIAnalysis.ranking**: `[{candidate_id, position, claim}]`, present only when the model ordered
every car and every position's claim passed the citation gate (cites tool results from that run,
every number appears in them, and it cites the car it is about). A partly-supported ranking is
discarded whole and the array stays empty.

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
  recalls_url: string|null,        // model-year page for the recalls count (see below)
  complaints_url: string|null,     // same page, #complaints tab; null when year/make/model missing
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
}                                  // links complaint rows through complaints_url
```

`recalls_url` / `complaints_url` shapes, in preference order:

1. Trim deep link, when the SafetyRatings `VehicleDescription` yields a body style and drive type:
   `https://www.nhtsa.gov/vehicle/2020/TOYOTA/CAMRY/4%252520DR/FWD#recalls` (`#complaints` for the
   other tab). NHTSA encodes a space inside these path segments as `%252520`; that literal form is
   what opens in a browser, so it is reproduced verbatim.
2. Year/make/model search landing, when body style or drive type is unknown:
   `https://www.nhtsa.gov/recalls?vymm=2020%20Toyota%20Camry` (no per-tab anchor exists here).

`https://www.nhtsa.gov/vehicle/{VehicleId}` is never emitted: the SafetyRatings numeric id has no
public page and returns "Page not found".

This is model-year level data from NHTSA. VIN-level recall status is OUT OF SCOPE.
Never invent counts; null means data unavailable.

### DealerInfo

```
{
  scope: "Dealer Business Information (not VIN-specific)",  // Fixed label, always present
  name: string|null,             // dealer.name from the inventory payload; never derived from a URL
  website: string|null,          // dealer.website, kept only when it is a plain HTTP(S) URL
  phone: string|null,            // dealer.phone as reported (formatting preserved)
  street: string|null,           // dealer.street
  city: string|null,             // dealer.city
  state: string|null,            // dealer.state
  postal_code: string|null,      // dealer.zip
  address: string|null,          // one line built from whichever parts above are present
  vehicle_location: string|null, // where the record put the car, which can differ from the rooftop
  maps_url: string|null,         // constructed Google Maps search (see below)
  vdp_url: string|null,          // the licensed listing this dealer record came with
  source_domain: string|null,    // host of website, else of vdp_url
  source: string,                // provenance sentence naming the record and its last-seen date
  notes: string[],               // caveats, e.g. business-level scope, car listed elsewhere
  links: [{label: string, url: string, note: string}]  // constructed lookup searches
}
```

Scope and provenance:
- Business level only. Nothing in this block is evidence about the individual vehicle, and no field is
  a rating: RevRank has no dealer score, and none is inferred, quoted or planned in this slice.
- Every field is copied from the `dealer` object of the MarketCheck inventory row already fetched for
  the listing. A field the payload omitted stays null instead of being guessed.
- The block travels with the seller's **own** licensed record. A syndicated copy of the same VIN may
  name a marketplace rather than the selling rooftop, so recovery leaves `dealer` null in that case.
  Search, direct, paste and synthetic imports have no dealer block at all.

`maps_url` shape: `https://www.google.com/maps/search/?api=1&query=<name + street + city + state + zip,
URL-encoded>`. It is keyless and coordinate-free by design — the reported text is handed to Maps as a
search rather than resolved into a pin RevRank would then be asserting. When the record carried a name
but no address, the query is the name alone and `notes` says so.

`links` are constructed search URLs for the buyer's own diligence, never fetched or summarized here:
- `https://www.bbb.org/search?find_country=USA&find_text=<name>&find_loc=<city, state>` when a name exists
- `https://www.dealerrater.com/consumer/search/dealer/?PostalCode=<zip>&Type=ZIP&ManufacturerName=Used-Car-Dealer`
  when a 5-digit ZIP exists; DealerRater has no name search, so this covers the area, not the dealer

`POST /api/compare` rebuilds `address`, `maps_url` and `links` from the reported name and address on
every candidate it receives, so a report never displays a link that arrived with the request. A block
whose name, address, website and phone are all empty is returned as `null` rather than an empty card.

### Metrics

Standard metrics include:
- Asking price, Budget headroom, Model year
- Mileage as supplied, Mileage normalized to km
- Transmission, Engine, Drivetrain, Body, Fuel Type
- Generation / trim, Location
- Projected odometer (when units match)
- Must-have: {item} (for each must_have)
- **% of original MSRP**: Calculated as `price/msrp*100` when:
  - Both price and msrp are set
  - The MSRP is sourced: in verified_fields (buyer confirmed) or NeoVIN-decoded (see MSRP fields above)
  - Currency is known and matches
  - Otherwise shows "N/A" or "MSRP not confirmed"

LLM explanations are optional via backend configuration and must never replace arithmetic.
Without a key, full deterministic extraction/comparison works and mode is explicitly rules.
No current market observations are fabricated: unconfigured market returns unavailable.
Responses include an honest evidence report even without licensed market access.

Depreciation, future sell value and condition-versus-price are not computed. Two `warnings` entries
name the evidence each needs and contain no figure; the report renders them as visible, empty
sections. See `docs/constraint-chat-cited-rerank.md`.

## Working boundaries

Frontend agent owns frontend/ and docs/agents/frontend.md.
Backend agent owns backend/ and docs/agents/data-processing.md.
Parent owns root tooling, shared contract, integration and general documentation.
Test agent is spawned after implementation and owns tests/ and docs/agents/testing.md.
