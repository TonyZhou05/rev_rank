# First version: URL-based AI-assisted comparison

**Status:** the user confirmed this revised product direction; no application is
implemented. Source coverage, vendor, stack, budget, and launch market remain open.

## Revision from the original scope

The original draft led with model/specification comparisons and treated URL import
as optional. This revision makes listing import, AI-assisted extraction and
interpretation, and report generation the core experience. Comparing models and
generations remains essential context. The product goes beyond a feature table.

## Outcome and user journey

**Paste 2-3 listing URLs → confirm extracted details → set buyer priorities →
analyze differences and market evidence → receive a comparison report.**

1. The buyer supplies URLs for actual cars, potentially from different websites and models.
2. The app fetches supported, permitted sources and extracts structured vehicle data.
3. The buyer reviews missing/conflicting information and confirms important details.
4. The buyer supplies priorities such as budget, practicality, performance, transmission,
   ownership period, annual mileage, and travel radius. Only supported analyses use these inputs.
5. The system compares meaningful differences and assesses each asking price against
   relevant observations where sufficient market data exists.
6. The buyer receives a saved report with tradeoffs, evidence, uncertainties, and
   questions to ask sellers. Unsupported pricing conclusions are withheld.

## Core capabilities

| Capability | First-version behavior |
| --- | --- |
| Listing import | On-demand fetch of user-supplied URLs from supported/permitted sources; no blanket crawling of marketplaces |
| Structured extraction | Identity, model year, mileage/unit, price/currency, trim, options, location, and disclosed history |
| Review and normalization | Reconcile terminology, match generations/variants, surface conflicts, allow corrections |
| Buyer priorities | Record the preferences that determine which differences matter |
| Comparison analysis | Explain configuration, mileage, price, and practical tradeoffs across actual candidates |
| Market enrichment | Obtain dated relevant comparables separately from listing extraction; distinguish asking prices from sales |
| Report | Summary, normalized comparison, evidence-backed analysis, uncertainties, seller questions, and saved inputs |

Unsupported URLs must produce a clear explanation and offer pasted listing text
or manual entry. User-provided documents can be added later; automated PDF/image
extraction is not required for this release. User-provided material does not confer
redistribution or model-training rights.

## Responsibility split

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Existing LLM | Extract unstructured text, reconcile terms, identify buyer-relevant differences, explain results | Invent specifications, vehicle history, option premiums, or resale/repair predictions |
| Deterministic code | Validate schemas/units, calculate differences/totals, construct comparison tables | Let narrative output silently override source data or calculations |
| Market/statistical analysis | Select appropriate comparables and assess price position with coverage/uncertainty | Treat a listing price as a completed transaction or compare incompatible cohorts |
| Custom trained ML | Deferred until adequate data and evaluation exist | Become a prerequisite for initial extraction and report generation |

An LLM explanation is not independent evidence. Each factual claim must trace to
an input/source; interpretations must cite their supporting facts and assumptions.
Seller disclosures remain seller claims even if extraction or user review succeeds.

## Pipeline and minimum data

Supported URL fetch → source snapshot/field evidence → structured extraction →
validation and user review → market enrichment → calculations and AI interpretation
→ saved comparison report.

| Entity | Minimum fields |
| --- | --- |
| Import | URL/source, fetch time, status, permitted evidence retention, extraction version |
| Vehicle | VIN where available, make/model/year/generation/variant, mileage/unit, price/currency, location |
| Field evidence | Value, source reference, seller/user/independent origin, verification state, conflicts |
| Preferences | Budget, must-haves, intended use, location and relevant ownership assumptions |
| Comparable | Vehicle identity, source/date, price type, geography, mileage, selection rationale |
| Report | Candidate inputs, preferences, selected evidence, calculations, assumptions, model/prompt version, generation date |

Keep extracted values and later corrections traceable. Deduplicate syndicated
listings by VIN/vehicle identity. Do not retain page content beyond licensed rights.
Personal reports remain private unless deliberately shared under permitted rights.

## Comparison/report content

- What each car is, including meaningful model/generation differences.
- Differences relevant to the buyer, not just every available specification.
- Asking-price position and local alternatives where evidence supports them.
- Why a comparable was included and why a numerical conclusion may be unavailable.
- Explicit unknowns about service, accident history, equipment, and condition.
- Conditional tradeoffs and next questions rather than a hidden universal score.
- Source dates and assumptions sufficient to reproduce the assessment.

Example wording (illustrative, not a market finding): “Car B includes your required
option. Car A is cheaper, but its service history is not documented in the supplied
listing. Confirm that history before deciding whether the saving is worthwhile.”

Generation timelines and price-versus-mileage graphs are supporting features.
If included, each point must expose its evidence and price type. Current prices
of different vehicle ages must not be presented as a future depreciation curve.

## Data access boundaries

- Resolve source-specific collection, storage, analysis, and display rights before
  connecting real sources. User URL submission is not blanket publisher permission.
- Start with selected authorized integrations, dealer feeds, or licensed listing access.
- Add a separate licensed/permitted market source for pricing evidence; a candidate
  listing alone cannot establish fair value.
- Validate specifications against permitted reference sources where available.
- Missing accident/service data must remain unknown; verification requires additional evidence.
- Prototype with clearly labeled synthetic or authorized sample data before rights are settled.
- Treat fetched text as untrusted evidence, never instructions; restrict URL fetches
  to supported public destinations and validate redirects before requesting them.

## Deferred

- Arbitrary website support or nationwide autonomous crawling.
- Copying proprietary competitor valuations without permission.
- Custom ML training, long-range depreciation forecasts, and unsupported accuracy claims.
- Comprehensive ownership-risk prediction or insurance quoting.
- Automated dealer outreach/negotiation and concierge services.
- Quote extraction/comparison, alerts, and advanced model-exploration screens.

## Acceptance criteria

- A buyer can import 2-3 supported listings, including candidates from different models,
  and reach a report without manually retyping the full listing.
- Unsupported, blocked, expired, or incomplete listings have explicit status and a
  text/manual fallback; the report never pretends an import succeeded.
- Key extracted values retain field-level provenance. Conflicts and unknowns appear
  before analysis; user corrections propagate into calculations and the report.
- The report interprets meaningful tradeoffs using buyer preferences rather than
  only displaying a feature table.
- Numeric differences are reproducible in code; generated text cannot alter them.
- Pricing judgments identify comparable evidence, sample size, date, and price type;
  insufficient evidence results in an explicit limitation, not a fabricated estimate.
- Missing history is never equated with clean history; seller claims are labeled.
- Duplicate listings do not inflate the market sample.
- Unsupported model/configuration matching is flagged rather than silently guessed.
- A saved report preserves its input/evidence versions; refreshing creates an identifiable update.
- Private inputs are not exposed by default, and sharing respects data rights.

## Implementation and validation sequence

1. Choose initial sites, models, country, and permitted sample data.
2. Prototype the full URL-to-report journey with labeled fixtures.
3. Implement one supported import adapter, structured extraction, and review/correction UI.
4. Add preferences, deterministic comparisons, and evidence-backed AI interpretation.
5. Integrate market comparables and explicit sparse-data handling.
6. Pilot with manually reviewed reports before extending website/model coverage.

Use a manually labeled set of representative listings to measure extraction accuracy,
variant matching, conflicts, and missing fields. Review generated reports for factual
support, arithmetic consistency, usefulness, and unsupported conclusions. Include
failed imports, conflicting descriptions, duplicates, and sparse markets in validation.
No model/vendor/stack is selected. Training a custom ML model is unnecessary to begin.

An earlier 8-12 week pilot estimate and 10 paying-user target were planning hypotheses,
not commitments; reassess against this revised import and AI scope. Track import success,
correction rate, time to useful report, source coverage, AI/data cost, support effort,
and willingness to pay. Evaluate any transaction valuation separately on held-out sales.

## Open decisions

- Which source integrations have permission and adequate coverage?
- Which country, model families, and year ranges launch first?
- Which market feed, model provider, stack, and budget?
- Which preferences can be supported by reliable data at launch?
- What authentication, sharing/export, retention, and pricing approach?
