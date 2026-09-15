# Dealer section on the report: link-out shell (on main) + thin cited signals

**Status:** the link-out shell shipped in PR #21 and is on `main`. This document also covers the
second slice, search-derived dealer flags, which is off by default behind
`REVRANK_DEALER_SIGNALS_ENABLED`.
**Non-goals:** a dealer score or rating of any kind, review-site quotes or star averages, scraping,
filtering or ranking cars by dealer risk, and MarketCheck Dealers Search / Places or any other paid
dealer endpoint.

## Why a dealer section at all

A buyer's risk is not only the car. Who is selling it decides what the out-the-door price becomes,
whether the advertised price survives contact with the desk, and whether a problem after the sale
has anyone behind it. The report already separates verified facts from seller claims for the vehicle;
the dealer deserves the same treatment rather than an implied endorsement.

The section is deliberately thin. RevRank has no licensed dealer-reputation data, so the honest
product is: here is who the record says is selling it, here is how to reach them, here are the public
pages you can read yourself, and here is what a couple of searches turned up — with every limit
stated. Anything richer would be a score we cannot stand behind.

## Slice A — link-out shell (free, always on, already on `main`)

Source: the `dealer` object of the MarketCheck inventory row **already fetched** for the listing, so
the whole slice costs zero extra provider calls. `backend/app/dealer.py` maps it into `DealerInfo`
(`Candidate.dealer`) and constructs the links; the shape is documented in `docs/API_CONTRACT.md`.

- Identity and contact: name, website, phone, street/city/state/ZIP, plus a one-line address.
- A keyless Google Maps **search** over the reported name and address:
  `https://www.google.com/maps/search/?api=1&query=…`. A search, not a pin: resolving coordinates
  would be RevRank asserting a location the record did not give.
- Constructed lookups the buyer runs themselves — **the free path, and the one that always works**,
  because none of it needs a key or a provider call: a BBB name search, a DealerRater ZIP-area search
  (that site has no name search, and the link says so), a web search for official records (attorney
  general, consumer protection, DMV, dealer licence), a Google News search, and a site-scoped search
  across owner forums and complaint boards (ComplaintsBoard, ConsumerAffairs, Reddit, AutoGuide
  forums). Each link carries a `kind` — records, news, boards or reviews — so the UI can word it for
  what it leads to, and each note says it is outbound and unread by RevRank; records add that a filed
  case is an allegation, boards that unmoderated posts are opinions rather than records.
- **Review and complaint platforms live here and only here**, as outbound links, never as machine-read
  signals. Slice B's deny list enforces the other half of that rule.
- Refusals: a dealer name is never derived from a hostname or listing URL; a missing field stays
  null and the card shows an honest empty state; a syndicated copy of the listing never supplies the
  dealer, because it may name a marketplace instead of the selling rooftop.
- `POST /api/compare` rebuilds the address line and every link from the reported fields, so a report
  cannot display a link that arrived with the request.

## Slice B — thin cited signals (opt-in, spends search credits)

Slice B is an addition to the free path, never a replacement for it: with the pass off, unavailable or
empty, the card still carries the five constructed searches above, and every degraded message says so.

`backend/app/dealer_signals.py` runs up to `REVRANK_DEALER_SIGNAL_SEARCHES` (default 2, max 3)
searches per distinct dealer and asks the configured model to read the excerpts back as at most three
green and three red flags, each citing the excerpts it used. `Report.dealer_signals` carries the
result per candidate; two cars at one rooftop share a single search set.

The query plan puts the bodies that license and discipline dealers first — attorney general, consumer
protection, DMV and FTC, then state motor vehicle boards and licence actions — and reaches for news
last, so a report run at the default of two searches never spends a credit on coverage before records.

Only two kinds of source are read:

- **`official`** — a public body's own page, recognised by host suffix (`.gov`, `.us`, `.mil`): state
  attorneys general, DMVs and motor vehicle boards, state consumer-protection offices, the FTC.
- **`news`** — any other host, but **only** when the search provider returned a publication date. That
  date is the one available signal that a page is an attributable article rather than an undated
  directory, profile or landing page.

Everything else is dropped before the model sees it: review platforms (Google, Yelp, DealerRater,
Trustpilot, Birdeye), complaint platforms (BBB, ConsumerAffairs, ComplaintsBoard, PissedConsumer,
Reddit), marketplaces, social networks, directories and wikis.

Every signal carries the four things needed to attribute it: the **quote** (a capped provider
snippet), the **source** (page title and host), the **date** (or an explicit "undated") and the
**URL**. Each *flag* repeats that attribution underneath its own sentence, so a reader never has to
take a flag on trust or go hunting for what it was built from. A signal also carries a `nature` read
from its own wording — `action` for a settlement, order or licence action, `allegation` for a filed
suit, complaint or investigation, `unclear` otherwise — and the UI labels that distinction rather
than collapsing both into one word.

Two things the feature deliberately does not do to a shortlist. A candidate with no dealer record —
a private sale, a pasted listing, a synthetic example — gets no block and triggers no search, because
searching a private seller's name is not this feature. And no dealer signal is ever registered as
analyst evidence, so no shortlist position, metric or filter can move on a dealer's record; a
regression test asserts the analyst's citable sources contain none of these ids.

The guardrails are structural, not prompt-deep:

| Risk | How it is prevented |
| --- | --- |
| Scraping or terms breach | This module imports no fetcher. Only the provider's title, snippet and date are stored, capped at 320 characters. |
| Reproducing licensed ratings | Review and complaint platforms are on a deny list checked at the registrable domain, so no star average or user submission can be quoted; they remain link-outs from slice A. |
| An invented dealer score | Flags are capped, cited sentences. A sentence containing rating/score/recommendation wording is rejected, and nothing is counted or averaged. |
| A fabricated figure | A claim is dropped unless it cites a returned excerpt and every number in it appears in that excerpt, its title, or the provider's date. |
| An allegation read as a finding | `nature` is derived from the excerpt, the prompt must respect it, and the caveats spell out the difference. An allegation is never upgraded to an action. |
| Silence read as innocence | No results is reported as "No official/news flags found … an absence of search results, not a clean dealer." A missing provider, missing dealer name, spent budget, search failure and model failure each set `status` and explain themselves. |
| Wrong business | Caveats state that a name plus a city is not an identifier, so a same-name business elsewhere can surface. |
| Bleed into vehicle claims | Signals are business level and labelled "About the dealer, not this VIN". Vehicle green/red flags come from the analyst and stay separate. |
| Runaway cost or a hung request | Searches go through the existing `search()` adapter, so `usage.py` meters and refuses them like any other search. The pass is cancel-token aware: it stops before starting a search when the client is gone or the budget is short, and the model call carries the same token. |

Cost: Tavily prices an advanced search at 2 credits, so the default is 4 credits per dealer per
report; the block reports the `searches` and `credits` it actually spent. Without an LLM key the
excerpts are listed uninterpreted rather than guessed at.

## Rights position

Neither slice establishes a reuse license. Slice A displays fields from a licensed feed whose display
and storage rights are still open (see `docs/marketcheck-integration.md`, step 8), and slice B shows
short provider-supplied excerpts with attribution and a link, which is the same posture as listing
recovery: excerpts as evidence of what a page says, never a copy of the page. Both stay personal and
local until those rights are settled, and keeping review and complaint platforms out of the machine
path entirely is what keeps their licensed content out of the question.

## Tests

- `backend/tests/test_dealer_shell.py` (slice A, on `main`) — payload mapping, the exact Maps URL and
  its encoding, address assembly, constructed lookups, dropped unsafe websites, "no dealer identity"
  and "name but no address" paths, the syndicated-copy rule, and the compare-time rebuild.
- `backend/tests/test_dealer_signals.py` (slice B) — host classification and the deny list, query
  wording, excerpt capping, allegation/action wording, the citation and number gates, score-wording
  rejection, the flag caps, every degraded status, the search meter refusing the pass, cancel-token
  behaviour, credit accounting, and the shared search set for one rooftop.

Both suites stub the search provider and the model at their adapters and assert no network access, so
CI never spends a Tavily credit.

## Tavily spend policy

The pass spends through exactly the same path as listing recovery, so there is one meter and one gate,
not a second budget to keep in sync:

- `search_enabled` gates it. With no `REVRANK_SEARCH_PROVIDER` / `REVRANK_SEARCH_API_KEY` the block is
  `unavailable` and says which variables are missing; `/api/health` reports `dealer_signals_enabled`
  as true only when the feature flag *and* a provider are both set.
- `usage.py` meters it. Every search goes through `search()`, which counts the call against
  `REVRANK_SEARCH_MONTHLY_CREDITS` and refuses it at the cap; the refusal surfaces as the block's
  message rather than as silence. A test proves the meter alone stops the pass with no network.
- The cost is bounded per report: `REVRANK_DEALER_SIGNAL_SEARCHES` (default 2, max 3) per **distinct**
  dealer, so two cars at one rooftop pay once. The block reports the `searches` and `credits` spent.
- Cancellation is the compare contract: no search starts once the client has disconnected or the
  remaining budget is under `MIN_SECONDS`, and the model call carries the same token.
- CI never spends. `backend/tests/test_dealer_signals.py` stubs the search provider and the model at
  their adapters and asserts no network access, and the autouse fixture fails the test if either is
  called for real.

### One frugal live smoke

**Not yet run.** No search key exists in CI or in the agent environment, so every result to date is
from stubs. When a key is available, `scripts/dealer_signal_smoke.py` exists so the first real call is
a single priced one instead of an exploratory session: it searches for one dealer, prints how each
result was classified, makes no model call and fetches nothing.

```sh
.venv/bin/python scripts/dealer_signal_smoke.py "Dealer Name" --city Austin --state TX          # dry run: prints the cost
.venv/bin/python scripts/dealer_signal_smoke.py "Dealer Name" --city Austin --state TX --spend  # 2 Tavily credits
```

It is a dry run without `--spend` and refuses more than three searches. Record the outcome here rather
than re-running it to see whether the results change.

## Not done yet

- No dealer signal appears on the Review step; the section is report-only.
- `news` classification leans on the provider's date, which is a proxy for "this is an article".
- Slice B has never been run live: it was built and tested against stubs to stay inside the search
  budget, so its first real run should be the single smoke above on a known dealer.
