# Spec: Constraint chat → cited shortlist re-rank (+ depreciation / condition placeholders)

**Status:** approved direction 2026-09-14 (Tongli); UI shell on `main` (PRs #12–#16); DeepSeek
wiring, constraint parsing and the cited re-rank implemented (see "Implemented backend" below).  
**LLM:** DeepSeek OpenAI-compatible (`REVRANK_LLM_BASE_URL=https://api.deepseek.com/v1`, model `deepseek-flash` = V4.1 Flash). Tool-calling for analyst + optional free-form constraint parse.  
**Non-goals:** CarEdge-style nearby inventory discovery; dealer negotiate-for-you; fair-price / $saved / 0–100 fit scores; revived `.rank-*` black-box UI.

## Problem
Buyers paste 2–3 listing URLs and get a report, but cannot say what matters (“keep 4 years”, “manual only”, “under $45k”) without an opaque score. CarEdge Ask does discovery chat; RevRank should do **constraint controls on an existing shortlist** that only reweights **cited** facts.

## User journey
1. Import / recover 2–3 candidates (existing).
2. Review / confirm facts + MSRP (existing; NeoVIN OEM / original / combined as plain text).
3. **Constraints panel** on Review or Report — editable chips (budget, years, miles, location, priorities, must-haves) with suggested starters when empty.
4. **Apply to report** (or Generate on Review) merges chips into `Preferences` and regenerates cited analysis.
5. Report shows cited tradeoffs plus **placeholder** blocks for Depreciation and Condition / feature-vs-price (honest empty copy until models land).

## UI source of truth (Frontend)
- Component: `frontend/src/ConstraintPanel.tsx` (chips + Apply / Clear).
- Desktop: secondary column; mobile (≤900px): summary row **above** content + bottom sheet for edit — do **not** reuse Import `side-panel` hide at 850px.
- Optional free-form parse (DeepSeek) may **propose** chip updates later; never replace chips+Apply with discovery chat.
- Dirty state: when live chips ≠ `report.preferences`, show “Constraints changed — Apply to rebuild.”

## Constraint parse (backend / DeepSeek — implemented)
**Endpoint:** `POST /api/constraints` body `{message, preferences?}` → `ConstraintResponse`.  
**Inputs:** the current preferences plus the buyer's message. Candidate ids are deliberately *not*
sent: this endpoint may only write preference fields, so it has no use for them.  
**Output:** a validated `Preferences`, the `constraints` it recognised (each with the buyer's own
quote and whether rules or the model produced it), a deterministic `reply`, `unmapped` phrases and
`notes`.  
**Rules:** the model proposes structure; code validates and merges into preferences; unknown fields,
cars and facts are refused; no comps are invented.

The fields are the real `Preferences` fields rather than the sketch names in the draft above, so
there is no translation layer and pydantic validates the result: `budget` (was `budget_max`),
`ownership_years` (`hold_years`), `annual_mileage` (`annual_miles`), `max_mileage`, `transmission`,
`must_haves` (`must_have[]`), `excludes` (`exclude[]`), `priorities`, `location`. `nice_to_have[]`
and `notes` are not implemented: a nice-to-have with no effect on the comparison would be a chip
that does nothing, and free-text notes would be an unvalidated channel into the report.

## Cited re-rank / ratings
- Keep deterministic comparison arithmetic.
- LLM analyst + finding ranker use DeepSeek when `llm_enabled`.
- Every claim still needs tool citations; invalid → drop / deterministic fallback (`dropped_claims` surfaced in UI).
- Ranking = order/emphasis of validated findings + preference fit — not a black-box 0–100 without formula.

## Placeholders (ship UI now, logic later)
1. **Depreciation / hold-period** — “Coming next: … We won’t invent a number.”
2. **Condition / feature-vs-price** — same honest pattern. Prefer empty modules over omission.

## Config
- `REVRANK_LLM_API_KEY`, `REVRANK_LLM_BASE_URL`, `REVRANK_LLM_MODEL=deepseek-flash`
- Health exposes `llm_enabled` when key+model set.
- Offline tests stub DeepSeek; no live calls in CI.

## Success
- [x] Spec in `docs/`
- [x] Constraint chips → Apply UI on Review/Report
- [x] Depreciation + condition placeholder sections visible
- [x] DeepSeek wired; analyst/rank use it when enabled
- [x] Optional free-form parse → chips (no discovery chat)
- Deploy when balance allows live verify

## Implemented backend

### How a model mapping is accepted

`backend/app/constraints.py` runs deterministic phrase rules first, always. They read a budget,
hold period, annual mileage, an odometer ceiling, transmission (including "I do not want a manual",
which flips), a `City, ST` location, must-haves from a bounded feature vocabulary plus explicit
"must have …" phrases, exclusions, and priorities from a bounded vocabulary. The numeric patterns
run most specific first and claim their spans, so "under $32,000 and nothing over 60k miles" yields
a budget *and* a ceiling rather than two readings of one number.

A configured model then proposes `{"constraints": [{field, value, quote}], "unmapped": [quote]}` in
JSON mode, and each item must:

- name one of the nine preference fields — a candidate field, a price or a mileage reading fails;
- quote a contiguous phrase from the buyer's message (collapsed whitespace, case-insensitive);
- carry a number recoverable from that quote — the digits of the value, of value/1000 or of
  value/100 must appear in it, so "about 30k" can yield 30000 and never 48000.

One unusable item discards the whole model result: the rules answer stands and `notes` says so.
This is the same gate and the same degrade-cleanly pattern as `assist_extraction`. The `reply` the
buyer reads is composed from the accepted constraints, not by the model, so the panel cannot narrate
a constraint that was rejected.

### Two orderings, kept apart

`Report.shortlist` is deterministic. Each car gets one check per stated constraint with an explicit
status: `meets`, `conflicts`, `not_established` (the listing is silent — never rendered as "no", and
never bankable as a pass) or `unknown` (missing, disputed, or an unusable unit). Order: conflicts
ascending, then unestablished-or-unknown ascending, then met descending, then the lower asking price
when every price is comparable, then import order. Every entry carries the checks behind its
position, so this is a count of the buyer's own constraints, not a black-box 0–100. With nothing
stated, the import order stands and no price tiebreak runs, because that would imply a preference
nobody expressed.

`AIAnalysis.ranking` is the model's order, and only appears when every position survives the
existing credibility gate: cites tool results fetched in that run, every number appears in them, and
it cites the car it is about. A partly-supported ranking is discarded whole with its reason returned
so the model can retry — an order the evidence does not carry is worse than none — and the
deterministic order stands. The deterministic fit is also exposed as citable `M.*.fit` metrics, so
ranking on constraint satisfaction traces back to computation rather than model judgement.

New metric rows for the compare table: `Mileage ceiling: {n}`, `Transmission wanted: {x}`,
`Exclude: {item}` and `Constraint fit`.

### Placeholder caveats

The backend does not re-implement the placeholder sections; it supplies the caveats they render,
naming the evidence each needs. Depreciation needs dated licensed transaction evidence and
generation/variant cohort matching — today's asking prices for cars of different ages are not a
depreciation curve, so nothing is extrapolated from the hold period. Condition versus price needs a
pre-purchase inspection or condition report and a permitted option-value source. A test asserts
neither caveat contains a currency amount, a percentage or a star rating.

### Degrading when the balance runs out

| Step | Degrades to |
| --- | --- |
| Constraint parsing | Deterministic phrase rules, with a note in the response |
| Field extraction | Deterministic rules extraction, with a warning |
| Finding order | Deterministic finding order, with a warning |
| Cited analysis | `ai_analysis.status = "unavailable"`, report stays `analysis_mode: "rules"` |
| Cited re-rank | Deterministic constraint-fit shortlist only |

`GET /api/health` also reports the non-secret `llm_model` and `llm_endpoint_host`; the key travels
in a header and `llm.py` keeps provider URLs, response bodies and raw exception text out of error
messages.

### Tests

`backend/tests/test_constraint_chat.py` and `test_shortlist_rerank.py` script the model by
monkeypatching `request_json` and `chat`, and refuse socket access, so CI makes no MarketCheck,
Tavily or model call. They cover rules-only parsing of every field from one sentence, negation
flipping a transmission, an accepted model mapping, an ungrounded number / ungrounded quote /
unknown field / listing fact each discarding the whole mapping, the endpoint contract including a
422 for an unknown preference field, every constraint-check status, silence never passing an
exclusion, shortlist ordering with and without constraints, caveat wording, and `set_ranking`
acceptance plus five rejection paths and the fallback.
