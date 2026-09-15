# Search-assisted listing recovery: feasibility investigation

Investigated 2026-09-13. The original research and proposed design are below. The
follow-up sections record the 403 diagnosis and alternative channels, then a live
recovery failure measured against the deployed app. The search, licensed-inventory
and VIN-decode adapters are now implemented behind opt-in settings.

## Follow-up (2026-09-15 UTC): a CarMax URL that no channel could recover

Reported against https://revrank.onrender.com: importing
`https://www.carmax.com/car/70199979` ended with the trail *Direct · blocked, Licensed ·
completed, Licensed · completed, Search · failed, Recovery · failed*. Two licensed
lookups reported as completed, followed by an overall failure, read as a bug in how
recovery combines its sources. It was not. Each leg was isolated with the recovery-source
switch (2 MarketCheck calls, 1 Tavily call):

| Leg | Measured result |
| --- | --- |
| Direct | `robots.txt` itself returns HTTP 403 from the Render datacenter range, so the site's rules could not be read and nothing was fetched. Same Akamai classification as 2026-09-13, now applied to `/robots.txt` as well. |
| Licensed, `vdp_url=https://www.carmax.com/car/70199979` | HTTP 200, **0 listings**. |
| Licensed, `stock_no=70199979` | HTTP 200, **0 listings** — an index-wide lookup, not scoped to CarMax. |
| Search (Tavily) | **HTTP 432**, Tavily's "plan limit exceeded": the account's credits are spent. No search ran. |

What this rules out:

- **Not a URL-pattern bug.** `normalize_input_url`, `identity_url` and `listing_id` return
  `https://www.carmax.com/car/70199979` and `70199979`, and the 2026-09-13 probe recorded
  `vdp_url=https://www.carmax.com/car/70181882` matching one CarMax row exactly. The same
  pattern works; this car is not in the provider's index.
- **Not a licensed-coverage-of-CarMax problem.** MarketCheck documents `carmax.com` as a
  source and returned a CarMax row two days earlier.
- **Not a sale.** `/v2/search/car/active` holds active inventory only, so a car that stops
  being listed drops out of it. Nothing here observed a transaction.

What was actually wrong in RevRank, and is fixed here:

- `licensed_records()` labelled every lookup that got an HTTP 200 as `completed`, including
  the two that returned nothing. Status now reflects what a lookup produced: `not_found`
  when the provider held no row, or held rows that are not this listing. The detail says
  which of the two happened.
- The outcome message named only the search failure, so a licensed miss was invisible unless
  the buyer opened "Import details". In `auto` mode the licensed miss is now stated first.
- `Search provider returned HTTP 432.` said nothing an operator could act on. Refusal codes
  (401, 403, 429, 432 for search; 401, 403, 422, 429 for MarketCheck) now carry their meaning,
  and the recovery message repeats it instead of swallowing it.
- The page's paid-provider meter read "Tavily 6/1000 credits" while Tavily was refusing every
  call. `usage.py` counts only the calls this checkout sent, and on Render `.local/usage.json`
  is on the ephemeral filesystem, so every deploy resets it to zero. The meter now says so on
  hover. The provider's own limit is the one that refuses a call.

A second probe against the same URL, run independently with the account key, widened the
licensed leg and agreed: `vdp_url` with and without `www` on `/active` → `num_found=0`;
`stock_no=70199979` with and without `source=carmax.com` → `num_found=0`; and
`/v2/search/car/all` → HTTP 404, since no such endpoint exists.

**Is the car sold, or was it never in MarketCheck?** Nothing above can tell the two apart, and
neither can the web: the Wayback availability API reports no snapshot of the URL ever, CarMax
returns 403 to any request from here, and a search for the stock number finds no CarMax page.
The one channel that distinguishes them is MarketCheck's past-inventory endpoint, and RevRank
now asks it — see below. If it holds the row, the car was listed and has since expired; if it
does not, MarketCheck never carried this listing.

**Expired-listing recovery, implemented here.** `/v2/search/car/recents` covers expired listings
from the last 90 days and takes the same `vdp_url` and `stock_no` filters as `/active`. Its one
extra requirement is a scope parameter, and `source` — the listing's own website — satisfies it.
Recovery now spends one scoped call there when every active lookup came back empty, which is an
import that would otherwise recover nothing. An expired row binds the VIN, which unlocks the free
NHTSA decode for year/make/model, and its price and mileage stay in the past: `Record(historical=True)`
keeps them out of the candidate's current fields and routes the price to `last_listed_price`. The
endpoint also publishes MarketCheck's own *inferred* sales; RevRank neither reads nor repeats that
inference, because a listing leaving the market is not evidence that it sold.

Still unverified against the live API: whether `source` + `vdp_url` is accepted on `/recents`, and
whether CarMax rows appear there. One MarketCheck call settles it, against any CarMax stock number
known to have been listed and then delisted:

```sh
curl -s "https://api.marketcheck.com/v2/search/car/recents?api_key=$MC_KEY&source=carmax.com&vdp_url=https://www.carmax.com/car/70199979&nodedup=true&append_api_key=false" | python3 -m json.tool | head -40
```

If it is rejected, the attempt is recorded as `licensed · failed` with the provider's reason and
recovery carries on to search exactly as before; nothing regresses.

## Follow-up (2026-09-13 UTC): why the pages are denied and which channels work

Header probes from the developer machine, with an honest `RevRank/0.1` user agent:

| Site | Edge | Observation |
| --- | --- | --- |
| CarMax | Akamai Bot Manager | `Access Denied` page with an `errors.edgesuite.net` reference on every tested path, including `/`, `/robots.txt` (200 on the earlier check), `/sitemap.xml`, and inventory pages. Akamai geolocated the client to Toronto, CA (`Kmx_Aka_Location`). |
| Carvana | Cloudflare managed challenge | `cf-mitigated: challenge`, "Just a moment..." interstitial on `/`, `/sitemap.xml` and the listing. `robots.txt` stays 200 and does not disallow `/vehicle/`. |

These are whole-site client classifications, not a listing-path rule. An HTTP change
to the RevRank fetcher cannot fix them honestly. Getting through would mean looking
like a browser to the bot manager: headless-browser stealth, residential/rotating
proxies, "web unlocker" scraping services, challenge solving, or reusing the user's
cookies server-side. All of those are bot-detection evasion and remain out of scope,
as stated below. The fetcher keeps reporting these as blocked. Deploying from a US
datacenter is not expected to help: bot managers commonly score datacenter ranges
as automated traffic. That was not tested.

Alternative channels tested:

| Channel | Result |
| --- | --- |
| Common Crawl index (CC-MAIN-2026-34, -30) | Zero captures for `www.carmax.com/car/*` or `www.carvana.com/vehicle/*`. Not viable. |
| Wayback Machine CDX | No capture of either listing. Availability API rate-limited (429). Not viable for fresh listings. |
| Search, CarMax stock `"70108828" carmax` | Still resolves to VIN 1G1FK1R64N0130896, now via multi-vehicle Edmunds/Cars.com inventory pages. The engine's summary gave 16,892 mi / Akron, OH / $69,998, while the earlier check gave 8,532 mi. This is exactly the cross-vehicle binding risk the per-record identity rules exist for. |
| Search, Carvana `carvana.com/vehicle/4711856`, `"4711856" carvana` | No matching vehicle. Carvana vehicle pages appear to be largely absent from the search index. Search is unlikely to recover Carvana URL-only inputs; ask for the VIN. |
| NHTSA vPIC `DecodeVinValues` (free, no key) | Works from this machine. Decodes 1G1FK1R64N0130896 as 2022 Chevrolet Camaro ZL1 coupe, 6.2L 8 cyl, check digit valid. A one-character change is flagged by the check digit. |
| MarketCheck `/v2/search/car/active` | Endpoint confirmed (HTTP 401 without a key). Documented `vdp_url`, `stock_no` and `vin` filters, `nodedup`, and per-listing `last_seen_at_date`. Coverage of these two listings is untested until a key is configured. |

The authorized equivalent of "a service account that can see the denied page" is a
licensed inventory feed that already holds the listing under its own agreements
(MarketCheck here), or the user's own browser session supplying the page text
(the pasted-text path). A third-party fetcher that defeats the site's bot manager
is not such a service.

### Implemented recovery order

1. Licensed inventory, if `REVRANK_MARKETCHECK_API_KEY` is set. Look up the
   query-stripped listing URL. Only a record whose `vdp_url` has the same host and
   path binds identity. If none matches and the seller URL has a stock pattern, look
   up the stock number, accepting only records on the seller's own host with the
   same `stock_no`. Several VINs, or a VIN that differs from the user's, stop with
   `identity_conflict`. Then look up the bound VIN with `nodedup=true` for
   syndicated copies. At most 3 requests. The provider's last-seen date becomes
   `observed_at`.
2. Search, only if licensed inventory found nothing. Same identity rules as before. Up to
   three queries: seller-scoped, then VIN, then VIN + "price". A fourth seller-focused query
   runs only for a missing CarMax location (see `docs/parsing-notes.md`).
3. NHTSA decode, if `REVRANK_VIN_DECODE_ENABLED=true`. Year/make/model must agree
   with every source; registry names may be coarser, e.g. "Camaro" vs "Camaro ZL1".
   A disagreement withholds the field as a conflict. The decoder fills an identity
   field only when no listing source supplies it. A check-digit error becomes a
   warning. Trim, body and engine are shown only as registry observations.
4. Reconciliation. The seller's own listing (fresh direct page or its licensed
   record) is primary. Its value is kept when syndicated copies disagree, with a
   warning, and every observation is retained. If no primary value exists, or two
   primaries disagree, the field is withheld as before. History flags from the feed
   are dealer claims (`seller_claim`), never verification.

Offline regressions: `backend/tests/test_licensed_recovery.py`.

### Live Tavily run (2026-09-13)

With a Tavily key configured, recovery was run live on both user URLs:

- **CarMax 70108828.** CarMax's own inventory snippets bind the stock number to
  VIN 1G1FK1R64N0130896, and NHTSA confirms 2022 Chevrolet Camaro. Mileage is
  withheld because sources disagree: CarMax 8,532 vs hypercars.io 8,522. Price is
  $71,998 from a single hypercars.io snippet, undated, with currency unknown.
- **Carvana 4711856.** No VIN appears anywhere in search. Tavily does return the
  exact listing URL with Carvana's own summary: 2025 Audi A5 Sportback S line 45
  TFSI Premium Sedan 4D, $29,590, 41,239 mi.

Rule change from this run: a snippet whose URL is the exact input listing (same
host and path, query ignored) binds identity without a VIN. Every other page must
still name exactly one VIN. Such a recovery is labeled "VIN unknown" and skips the
NHTSA decode.

Extraction fixes from the same run:

- Flattened `Label: value;` excerpts are split into lines.
- A truncated trailing field ("City, State: Madison,") is dropped.
- "Asking $X" is read as a price.
- Retail summary sentences ("Used YEAR MAKE MODEL … for $X with N miles") are
  parsed, for known makes only.
- Shopper distances ("502 mi away") are no longer read as mileage.
- `money()` no longer truncates "$71,998." to 71.
- Search snippets are capped at 3 per site, so one publisher's inventory pages
  cannot crowd out other sources.

## Finding

Recovering vehicle information after a direct HTTP 403 is feasible through search
and independently accessible syndicated inventory. This does not make the original
HTTP request succeed. A successful recovery must preserve the blocked request and
identify where each replacement observation actually came from.

At the time of the original investigation RevRank stopped at failed direct retrieval.
Its optional LLM processes supplied text and has no search tool. The API-backed
recovery adapters described in the follow-up now provide this pipeline.

## Experiments using the assistant's search tool

The previous production-fetcher tests returned 403 for both supplied listing URLs.
This investigation tested search discovery, not a paid provider API or browser
anti-bot bypass. Provider parity with these results remains unmeasured.

| Input/query | Outcome |
| --- | --- |
| CarMax URL /car/70108828; query `"70108828" "CarMax"` | Found indexed CarMax inventory pages tying that stock number to VIN 1G1FK1R64N0130896, a 2022 Camaro ZL1, price $68,998, mileage 8,532, and an on-hold label |
| Exact VIN search, performed in the preceding investigation | Found Capital One and DealerRater syndicated records; their reported price was $69,998 and mileages differed (8,522 / 8,532) |
| Carvana URL /vehicle/4711856; exact URL and site-qualified ID searches | No relevant match returned in these queries; identity unresolved |

Evidence links:

- [CarMax indexed model inventory](https://www.carmax.com/cars/chevrolet/camaro/zl1/2022)
- [Capital One matching VIN](https://www.capitalone.com/cars/vehicle-details/2022/Chevrolet/Camaro/ZL1/1G1FK1R64N0130896)
- [DealerRater matching VIN](https://www.dealerrater.com/classifieds/2022-Chevrolet-Camaro-ad-1G1FK1R64N0130896-30994/)

Search metadata reported the first CarMax result crawled three days earlier. This
is not an observation that the vehicle remains on hold now. Repeated CarMax pages
are one publisher, not independent confirmations. The syndicated records may
share the same seller feed. Clean-title/no-accident claims were not verified here.
No comparable-market valuation was performed. This pair is a feasibility example,
not a recovery-rate benchmark.

## Proposed pipeline

1. Validate the URL using existing public-network and source controls. Normalize
   tracking parameters for identity lookup using source-specific rules; retain the
   original input. Extract a seller-scoped stock ID from recognized URL patterns.
2. Attempt direct retrieval once. Respect Retry-After on rate limits. Record 403,
   robots denial, missing page, and incomplete extraction as distinct outcomes.
3. If configured, query a search provider for the exact URL, then seller + exact
   stock ID. Do not treat a numerical ID alone as a globally unique vehicle.
4. Parse each result separately. Discover VIN candidates only from evidence that
   binds the seller/stock ID to that VIN. A result's relevance score is not an
   identity score. If conflicting VINs remain, stop for user review.
5. Search the confirmed VIN and/or query licensed inventory by VIN or original
   listing URL. Retrieve permitted result pages if needed. Every discovered URL
   still passes URL, DNS, redirect, content-size, and source checks; a search result
   must not automatically become an allowlisted crawl target.
6. Scope extraction to the record containing that VIN/stock number. Inventory
   pages contain multiple vehicles: concatenating them before extraction risks
   assigning another vehicle's price, features, or history to the candidate.
7. Store field observations separately and reconcile them explicitly. Prefer a
   fresh, vehicle-bound seller observation when justified, but retain conflicting
   observations and uncertain dates. Do not average conflicting prices, treat
   query time as data freshness, or use majority voting across duplicated feeds.
8. Return a sourced draft for review, with original-page access status and recovery
   method visible. If identity cannot be established, request VIN or pasted text.
9. Search market comparables separately, after identity resolution. Other webpages
   for the same VIN are not comparable vehicles and must not inflate sample size.

Suggested initial bounds, to tune using measurements: 3 search queries, up to 5
result candidates per query, 3 permitted page fetches, 45 seconds total per vehicle,
and explicit provider/request budgets. Cache only under the provider's applicable
terms; short-circuit once identity and sufficient attributable fields are found.

## API/provider options

| Option | Documented capability | Evaluation role / limit |
| --- | --- | --- |
| [Brave Web Search](https://api-dashboard.search.brave.com/app/documentation/web-search) | Ranked URLs and up to five extra snippets | First candidate for auditable URL/stock/VIN discovery; snippets can be incomplete or stale |
| [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) | Search results and optional cleaned raw content | Compare against Brave on identical cases; use source content, not a generated answer, as evidence |
| [MarketCheck inventory](https://docs.marketcheck.com/docs/api/cars/inventory/inventory-search) | `vin` and `vdp_url` filters, source fields, duplicate-listing retrieval | Structured recovery/enrichment candidate; check actual source coverage and commercial scope; not guaranteed to contain either sample |
| Browser rendering | JavaScript execution for accessible pages | Useful when the server returns a shell; not established as a solution to these 403s |

Provider capabilities above were checked in official documentation, but none of
these APIs was called with customer credentials in this investigation. Do not
commit to a provider or pay for a plan before testing coverage. Search access does
not automatically confer downstream redistribution rights for every result.

No rotating residential proxies, CAPTCHA solving, Googlebot impersonation, or
session-cookie harvesting is proposed. Those do not solve evidence matching,
freshness, or extraction accuracy, and are outside the current project approach.

## RevRank implementation implications

- Add `retrieval.py` for bounded orchestration and provider adapters under
  `search/`; retain `fetch.py` for guarded direct requests.
- Extend `ImportRequest` with optional VIN and recovery preference, and its response
  with retrieval attempts, match basis, and recovery method. A recovered import
  must not report that the original blocked page was fetched successfully.
- Extend the evidence schema beyond a single value per field: source URL,
  retrieval method, exact support, VIN/stock binding, retrieved timestamp,
  source-observed timestamp (nullable), and conflicts. Store provenance separately
  for seller statements, licensed observations, snippets, and user corrections.
- Keep extraction per source/vehicle record. LLMs may select supported spans;
  validators and deterministic reconciliation control identity and arithmetic.
- Show "Recovered from search", source dates, and conflicting field values in the
  React review screen. Use "last observed on hold" for dated indexed claims.
- Add opt-in search-provider configuration to `.env.example`; credentials stay
  server-side. Existing allowed website hosts are not a search API integration.

## Acceptance experiment before claiming coverage

Use at least 30 manually reviewed listing cases across the ten domains, covering
known VINs, URL-only inputs, 403s, removed listings, dynamic pages, multiple vehicles,
syndication, inconsistent price/mileage, and unsupported history claims. Keep the
two user examples as regression cases, with dated expectations rather than fixed
"current" prices. Do not label all cases from a domain successful after one fetch.

Measure identity-resolution rate, wrong-vehicle merges, per-field supported
accuracy, conflict detection, recovery coverage, price/status observation age,
latency, and provider cost per useful report. Identity precision takes precedence
over filling every field. Reject unsupported clean-history and current-availability
claims. Inject adversarial page instructions, malicious search URLs, and unrelated
VINs to check isolation. Test provider outages and missing credentials offline.

Recommendation: implement a provider-neutral search fallback, evaluate Brave and
Tavily with the same cases, and add a licensed inventory adapter if it materially
improves coverage. Ship recovery labels and conflict review together with search;
otherwise broader retrieval can make this accuracy-focused product less reliable.
