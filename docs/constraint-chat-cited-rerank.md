# Spec: Constraint chat → cited shortlist re-rank (+ depreciation / condition placeholders)

**Status:** approved direction 2026-09-14 (Tongli); UI shell on `main` (PRs #12–#13).  
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

## Constraint parse (backend / DeepSeek — in flight)
**Inputs:** shortlist candidate ids + current preferences + optional user message.  
**Output JSON (validated):** e.g. `budget_max`, `must_have[]`, `nice_to_have[]`, `hold_years`, `annual_miles`, `transmission`, `exclude[]`, `notes`.  
**Rules:** LLM proposes structure; code merges into preferences; refuse unknown cars/facts; no invented comps.

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
- [ ] DeepSeek wired; analyst/rank use it when enabled
- [ ] Optional free-form parse → chips (no discovery chat)
- Deploy when balance allows live verify
