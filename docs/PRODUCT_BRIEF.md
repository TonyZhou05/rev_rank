# Product brief

Planning snapshot: 2026-09-12. This summarizes the conversation, not a shipped app.

## One sentence

RevRank turns 2-3 vehicle listing URLs into a personalized comparison report using
AI-assisted extraction, verified/qualified facts, buyer priorities, and market evidence.

## Problem and origin

The user wants a product similar to CarEdge with more trustworthy comparisons.
The initial example was CarEdge's BMW M2 depreciation table: resale value fell
from $64,675 at age two to $40,845 at age three, following only $2,000 of depreciation
across the first two years. This is an unexplained discontinuity to investigate,
not proof of the correct value or of the cause of the discrepancy.

Other publishers also display materially different M2 depreciation estimates.
Different starting prices, cohorts, dates, mileage, or methodologies may account
for differences. The product should expose these assumptions instead of combining
incompatible numbers into one confident answer.

## User direction versus proposals

| Status | Decision |
| --- | --- |
| User direction | Build an MVP before pursuing a broad CarEdge-like platform. |
| User direction | Compare different models through actual vehicle candidates. |
| Confirmed revision | URL import → detail verification → buyer priorities → AI-assisted analysis → evidence-backed report is the first-version workflow. |
| User direction | Enable cross-website comparisons; investigate whether crawling is permitted. |
| Discussed positively | Interactive graphs, local details, comprehensive reports, and an integrated buying journey. |
| Proposed, unconfirmed | US-first, USD, three model families, enthusiast/performance-car starting segment. |
| Proposed, unconfirmed | Supported listing-source integrations plus a licensed market feed and permitted specifications; quote comparison later. |
| Not selected | Vendors, stack, budget, launch models, monetization, final schedule. |

## Who and what

Initial target hypothesis: a used-car buyer choosing between a few models and then
between specific cars. Enthusiast vehicles are a candidate segment, not an
exclusive commitment. Possible examples are M2, Supra, and Cayman; actual coverage
must be chosen after assessing data quality and customer demand.

Primary question: **Which model and actual car fit my needs and budget, and what
evidence supports the price?**

## Core journey — revised first version

1. **Import:** paste 2-3 listing URLs from supported, permitted sources.
2. **Verify:** review extracted identity, price, mileage, equipment, location, and
   disclosed history; resolve material conflicts or leave them explicitly unknown.
3. **Personalize:** enter budget, intended use, must-have features, ownership period,
   annual mileage, and location as relevant to the comparison.
4. **Analyze:** identify meaningful model/generation/vehicle differences and compare
   each candidate with appropriate market observations.
5. **Report:** explain tradeoffs, evidence quality, uncertainties, and seller questions;
   preserve the candidates and inputs for later review.

Model exploration, generation graphs, and market charts support this workflow.
Dealer quote comparison and monitoring are later extensions. See [MVP.md](MVP.md)
for the revised scope and acceptance criteria.

## Why an app instead of another chat answer

Graphs or longer AI reports alone are weak differentiation. The app should maintain
normalized vehicle identities, fresh market observations, saved preferences,
shortlists, and quotes across the entire decision. Selecting a generation changes
the comparables; comparables support the shortlist; quotes update the comparison.

Every material conclusion should link to its evidence or disclose its assumptions.
An existing LLM performs extraction and buyer-relevant interpretation. Deterministic
code performs arithmetic; licensed market observations support pricing judgments.
Custom ML is a later option, not a first-release dependency.

## Three different meanings of comparison

| Comparison | Example | Data approach |
| --- | --- | --- |
| Models | M2 vs. Supra: specs and market distributions | Permitted specs and licensed observations |
| Listings | Specific cars advertised across dealers/sites | Licensed feeds, dealer permission, user-entered details |
| Publishers' estimates | CarEdge depreciation vs. another provider | Publisher permission/licensing; normalize assumptions |

First release prioritizes URL-based comparisons of actual cars, including cars from
different models. It does not depend on copying competitors' proprietary valuation
tables or promising import from every website.

## Competitive context

- **CarEdge:** broad ownership research, shopping tools, AI negotiation, and human concierge services.
- **iSeeCars:** model comparisons, depreciation research, VIN/local-market analysis.
- **CarGurus:** inventory, listing-based deal analysis, saved searches, alerts.
- **KBB:** transaction-informed purchase estimates and distinct value definitions.
- **Edmunds:** ownership-cost comparisons with published assumptions.
- **TrueCar:** shopping and transaction-informed pricing context.
- **CLASSIC.COM:** enthusiast markets, generation/variant taxonomy, comparables, charts.
- **Hagerty:** collector valuations, condition distinctions, historical evidence.

These competitors already offer many individual features. The opportunity is a
clearer integrated decision workflow and high-quality evidence in a limited scope.
Matching nationwide coverage, distribution, or long-range forecast accuracy is not
an MVP objective. Superior accuracy remains a hypothesis to test.

## Data and legal strategy

This is a product recommendation, not legal clearance. Applicable law depends on
operating jurisdiction, target markets, access methods, and use.

- Review rights to collect, store, refresh, analyze, display, export, and retain data.
- CarEdge and CarGurus published terms restrict unauthorized scraping and reuse.
  Recheck current terms and obtain advice/permission before an integration.
- Evaluate licensed inventory/specification feeds such as MarketCheck. CLASSIC.COM
  offers an API that may be relevant to taxonomy/market data; scope needs confirmation.
- Government services such as NHTSA vPIC and FuelEconomy.gov can provide some factual
  inputs. Exact build/options and generation classification need additional work.
- Dealer partnerships may supply authorized listings or transaction evidence.
- User-entered observations and quotes can support private comparisons. Uploading a
  third-party document does not automatically grant redistribution or training rights.
- Attribution, robots.txt, a browser extension, or a scraping vendor is not itself
  a commercial reuse license. Do not bypass access restrictions as an MVP strategy.

## Accuracy principles

Separate asking prices, last observed prices, confirmed transactions, trade-in
values, and forecasts. Preserve region, currency, date, mileage, generation, and
variant. Mark sparse evidence and missing history explicitly.

For future valuation claims, use independently verified outcomes, time-based
holdouts, VIN deduplication, a simple comparable baseline, and uncertainty/coverage
metrics. A current-value benchmark does not validate a five-year forecast.

## Business hypotheses

- Free model exploration could attract buyers; a paid detailed report or short-term
  buyer pass may fit an episodic purchase better than an ongoing subscription.
- Previously discussed test prices: $19-39 per report or $49-79 per buyer pass.
  These are unvalidated experiments, not selected pricing.
- Early distribution could come from owner communities, inspectors, and specialist
  partners. Do not assume a large SEO footprint or paid acquisition will be economical.
- Track data cost, support time, conversion, refunds, and contribution per customer.
- Seek verified outcomes with consent to improve the evidence base over time.

## Reference links

Links record research leads; recheck current terms and commercial offerings.

- https://caredge.com/bmw/m2/depreciation
- https://caredge.com/terms
- https://www.cargurus.com/about/terms-of-use
- https://www.iseecars.com/car/bmw-m2/resale-value
- https://support.classic.com/classic.com-api
- https://docs.marketcheck.com/docs/get-started/data-feeds/introduction
- https://vpic.nhtsa.dot.gov/api/
- https://www.fueleconomy.gov/feg/ws/index.shtml
- https://www.kbb.com/faq/used-cars/
- https://www.edmunds.com/about/more-about-tco.html
