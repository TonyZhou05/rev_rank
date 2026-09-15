# Dealer section on the report: link-out shell + thin cited signals

**Status:** implemented on this branch in two slices. Slice A (link-out shell) is always on and free.
Slice B (search-derived flags) is off by default behind `REVRANK_DEALER_SIGNALS_ENABLED`.
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

## Slice A — link-out shell (free, always on)

Source: the `dealer` object of the MarketCheck inventory row **already fetched** for the listing, so
the whole slice costs zero extra provider calls. `backend/app/dealer.py` maps it into `DealerInfo`
(`Candidate.dealer`) and constructs the links; the shape is documented in `docs/API_CONTRACT.md`.

- Identity and contact: name, website, phone, street/city/state/ZIP, plus a one-line address.
- A keyless Google Maps **search** over the reported name and address:
  `https://www.google.com/maps/search/?api=1&query=…`. A search, not a pin: resolving coordinates
  would be RevRank asserting a location the record did not give.
- Constructed lookups the buyer runs themselves: a BBB name search, and a DealerRater ZIP-area
  search (that site has no name search, and the link says so).
- Refusals: a dealer name is never derived from a hostname or listing URL; a missing field stays
  null and the card shows an honest empty state; a syndicated copy of the listing never supplies the
  dealer, because it may name a marketplace instead of the selling rooftop.
- `POST /api/compare` rebuilds the address line and every link from the reported fields, so a report
  cannot display a link that arrived with the request.

## Slice B — thin cited signals (opt-in, spends search credits)

`backend/app/dealer_signals.py` runs up to `REVRANK_DEALER_SIGNAL_SEARCHES` (default 2, max 3)
searches per distinct dealer and asks the configured model to read the excerpts back as at most three
green and three red flags, each citing the excerpts it used. `Report.dealer_signals` carries the
result per candidate; two cars at one rooftop share a single search set.

Which sources are read: consumer complaint boards from a fixed list, `.gov` / `.us` pages, and other
hosts **only** when the provider returned a publication date. Everything else — review platforms,
marketplaces, social networks, directories — is dropped before the model sees it.

The guardrails are structural, not prompt-deep:

| Risk | How it is prevented |
| --- | --- |
| Scraping or terms breach | This module imports no fetcher. Only the provider's title, snippet and date are stored, capped at 320 characters. |
| Reproducing licensed ratings | Review platforms are on a deny list checked at the registrable domain, so no star average or review text can be quoted. |
| An invented dealer score | Flags are capped, cited sentences. A sentence containing rating/score/recommendation wording is rejected, and nothing is counted or averaged. |
| A fabricated figure | A claim is dropped unless it cites a returned excerpt and every number in it appears in that excerpt, its title, or the provider's date. |
| Silence read as innocence | No results is reported as "an absence of search results, not a clean record". A missing provider, missing dealer name, spent budget, search failure and model failure each set `status` and explain themselves. |
| Wrong business | Caveats state that a name plus a city is not an identifier, so a same-name business elsewhere can surface. |
| Bleed into vehicle claims | Signals are business level and labelled "About the dealer, not this VIN". Vehicle green/red flags come from the analyst and stay separate. |

Cost: Tavily prices an advanced search at 2 credits, so the default is 4 credits per dealer per
report; the block reports the `searches` and `credits` it actually spent, and `usage.py` still refuses
a call once the monthly cap is reached. Without an LLM key the excerpts are listed uninterpreted.

## Rights position

Neither slice establishes a reuse license. Slice A displays fields from a licensed feed whose display
and storage rights are still open (see `docs/marketcheck-integration.md`, step 8), and slice B shows
short provider-supplied excerpts with attribution and a link, which is the same posture as listing
recovery: excerpts as evidence of what a page says, never a copy of the page. Both stay personal and
local until those rights are settled, and the deny list keeps review platforms out of the question
entirely.

## Tests

- `backend/tests/test_dealer_shell.py` — payload mapping, the exact Maps URL and its encoding,
  address assembly, constructed lookups, dropped unsafe websites, "no dealer identity" and
  "name but no address" paths, the syndicated-copy rule, search recovery having no block, the import
  response over the wire, and the compare-time rebuild. It also asserts recovery still spends exactly
  one provider call.
- `backend/tests/test_dealer_signals.py` — host classification and the deny list, query wording,
  excerpt capping, the citation and number gates, score-wording rejection, the flag caps, every
  degraded status, credit accounting, and the shared search set for one rooftop.

Both suites stub the provider adapters and assert no network access.

## Not done yet

- No dealer signal appears on the Review step; the section is report-only.
- `news` classification leans on the provider's date, which is a proxy for "this is an article".
- Slice B has never been run live: it was built and tested against stubs to stay inside the search
  budget, so its first real run should be a single deliberate one on a known dealer.
