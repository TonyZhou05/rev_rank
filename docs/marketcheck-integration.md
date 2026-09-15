# MarketCheck integration plan

> **⚠ Budget: MarketCheck has 500 calls/month, Tavily 1,000 credits.** Don't call either unless a
> live call is necessary. Read "Paid API budget" in `AGENTS.md` before any request. The backend
> meters and caps paid calls in `.local/usage.json`.

Written 2026-09-13. Prices come from the MarketCheck and Tavily pricing pages on that date, plus
RevRank's own usage measurements. Recheck them before committing money.

## Why MarketCheck

Search recovery (Tavily) reads excerpts of CarMax's search-engine landing pages. Those excerpts are
undated, often cut off, and mix in neighboring cars, and Tavily's index decides what we can find (see
`docs/parsing-notes.md`). MarketCheck is a licensed inventory feed. It returns structured listings by
VIN or listing URL, with the dealer, price, miles, and first/last-seen dates. It replaces guesswork
with dated records.

## Cost: MarketCheck vs Tavily

| | Tavily search API | MarketCheck API |
| --- | --- | --- |
| Free tier | Researcher: 1,000 credits/month on the pricing page; this account's usage endpoint reports a 1,500 limit | 500 calls/month, 5 calls/s; "100 mile radius restriction" (Free and Basic) |
| Paid | Pay-as-you-go $0.008/credit; Project plan 4,000 credits/month | Basic $299/month + data fees (5,000 calls); Standard $749/month + data fees (unlimited, 40 calls/s) |
| Unit price | 2 credits per advanced search (measured: Tavily's response reports `usage.credits: 2`) | Inventory search $0.002/call; VIN history $0.006/call; basic VIN decode $0.0015/call |
| Calls per RevRank import | 3–4 searches = 6–8 credits | up to 3 inventory calls (listing URL, stock, VIN), plus 1 NeoVIN MSRP decode when the VIN is known, plus 1 optional history call |
| Cost per import | about $0.05–0.06 pay-as-you-go; free tier covers about 190–250 imports/month | about $0.006 in data fees (+$0.006 with history); free tier covers about 166 imports/month |

**Which is cheaper?**

- **Free tiers:** about the same volume, roughly 200 imports/month on Tavily vs 166 on MarketCheck.
- **Paid, low to mid volume:** Tavily is much cheaper. MarketCheck's per-call price is about 10× lower,
  but a paid plan starts at $299/month. Basic's 5,000 calls cover only about 1,650 imports, so heavier
  use means Standard at $749/month. Against Tavily's roughly $0.05 per import, Standard breaks even
  near 15,000 imports/month.
- **Per useful result:** the comparison may flip. From the 20-case live corpus, Tavily often returns no
  current price (the C43 case) and undated values. Measure MarketCheck's hit rate on the same corpus
  (step 3) before deciding.

## Live results (2026-09-13, 7 MarketCheck calls)

The free-tier key works. Raw responses (key-free) are saved in `.local/eval/probe-20260913/`: reuse them
instead of calling again.

| Lookup | Result |
| --- | --- |
| `vdp_url=https://www.carmax.com/car/70181882` (M2) | 1 row: $40,998, 40,047 mi, Carmax Rochester (NY), stock 70181882, first seen 2026-08-21, last seen 2026-09-13. Matches the page |
| `vin=WBS1H9C3XHV887640` (same M2) | the same single row: nothing extra for this car |
| `vin=WDDWK6EB4JF686842` (C43, carmax.com/car/28033756) | $32,998, 39,017 mi, last seen 2026-09-13. Tavily had no current price, only a stale $33,140 from vininspect |
| `vdp_url=https://www.carvana.com/vehicle/4711856` (Audi A5) | VIN WAUDACF56SA008147, $29,590, 41,239 mi, West Memphis, AR. Search never recovered a Carvana VIN or location |
| `/v2/history/car/WBS1H9C3XHV887640` | 14 dated entries back to 2017: new at BMW of Roseville; Craigslist, KBB and Autotrader private sales at $35,000–$37,000 in 2026-04 to 2026-08. It works on the free tier |
| 2 end-to-end imports in `recovery_source=marketcheck` mode (C43, Audi) | 1 call each: recovered with price, mileage, location, and the NHTSA cross-check |

What we learned:

- `vdp_url` matches CarMax and Carvana URLs exactly (`https://www.<site>/car/<id>` and `/vehicle/<id>`,
  without a query string). The 100-mile radius limit does not affect identity lookups.
- Carvana rows carry `stock_no: 2147483647`, a 32-bit placeholder. It is dropped.
- Rows include `build.body_type/engine/drivetrain/fuel_type`, `car_location` (the car's own place),
  colors, `dom`/`dom_active`, and `first_seen_at_date`. Body, engine, drivetrain, fuel and `car_location`
  are now mapped.
- `build.model` includes the body ("M2 Coupe", "A5 Sportback"). The NHTSA decode's model is shown when
  they differ.
- Tavily crawl (`POST /crawl`, limit 3) returned no pages for the CarMax and Carvana listing URLs, and
  billed 0 credits. Its crawler is blocked like ours.

## Live results (2026-09-15, 2 MarketCheck calls): a CarMax stock the index does not hold

`https://www.carmax.com/car/70199979`, probed against the deployed app in `recovery_source=marketcheck`
mode. Both lookups answered HTTP 200 with **zero** listings: `vdp_url=https://www.carmax.com/car/70199979`
and `stock_no=70199979`. The stock lookup is not scoped to CarMax, so no dealer in the active index
carries that number. A second probe with the account key confirmed it and widened the net: `vdp_url`
with and without `www`, and `stock_no` with and without `source=carmax.com`, all returned `num_found=0`.
`/v2/search/car/all` returns HTTP 404; there is no such endpoint.

The URL pattern is the same one that matched stock 70181882 two days earlier, so this is a per-listing
coverage gap, not a parsing or filter problem. `/v2/search/car/active` holds active inventory only: a car
that stops being listed leaves it. Never call that a sale.

Consequence for recovery: once the URL, stock and VIN lookups are empty, active inventory has nothing
left to offer, and the honest outcome is "no active record; it may already be sold or removed".

## Past inventory as the last licensed resort (built 2026-09-15, not yet live-verified)

`GET /v2/search/car/recents` holds expired listings from the last 90 days and accepts the same `vdp_url`
and `stock_no` identity filters as `/active`. Its only extra requirement is a scope: the endpoint rejects
an unscoped search, and the allowed scopes include `source`, the listing's own website. That is a scope we
want regardless, so an identity lookup fits the endpoint exactly:

```
GET /v2/search/car/recents?source=carmax.com&vdp_url=https://www.carmax.com/car/<stock>&nodedup=true
```

- **When it runs.** Only after every active lookup came back empty, so it never touches an import that
  already succeeded. `REVRANK_MARKETCHECK_PAST_INVENTORY_ENABLED=false` switches it off.
- **What it costs.** One call, on an import that would otherwise recover nothing. An expired-only recovery
  skips the NeoVIN decode, because an MSRP with no price to be a percentage of buys nothing, so the common
  no-VIN case stays at 3 calls. Worst case, with a supplied VIN and every lookup missing, is 5.
- **What it yields.** The VIN, which unlocks the free NHTSA decode for year/make/model, plus a dated
  `last_listed_price`. `Record(historical=True)` keeps the expired row out of current price and mileage,
  and no dealer block is attached: the rooftop named on an expired listing no longer has the car.
- **What it must never say.** The endpoint also publishes MarketCheck's own *inferred* sales, computed from
  a listing disappearing. RevRank does not read or repeat that inference. The candidate says the listing
  has left active inventory and that this does not confirm a sale.

Still to verify live, one call, against any CarMax stock known to have been listed and then delisted:
whether `source` + `vdp_url` is accepted on `/recents`, and whether CarMax rows appear there. A rejection
is recorded as `licensed · failed` with the provider's reason and recovery continues to search as before.

## What already exists

Implemented, with offline tests, and verified live on 2026-09-13:

- **Recovery source switch:** `ImportRequest.recovery_source` is `auto` (the default: MarketCheck first,
  then a private browse of the buyer-supplied URL when Direct was blocked and browse is enabled,
  then search only on a miss), `marketcheck`, `browse`, or `search`. The import page has a "Recovery source (debug)"
  control that shows this month's metered usage. Cached browser results are keyed by source.
- **Call order, cheapest first:** a known VIN goes first (1 call returns the seller's record and its
  copies). Otherwise: listing URL, then the seller's stock number only if the URL missed. Once the
  seller's record is found, no further VIN lookup runs, so a typical import is 1 call.
- **Usage meter:** `backend/app/usage.py` counts calls per UTC month in `.local/usage.json`. It refuses
  a call before sending it once the limit is reached, and the refusal appears as a failed attempt.
- `backend/app/vehicle_data.py`: `inventory_search()` calls `GET https://api.marketcheck.com/v2/search/car/active`,
  or `/v2/search/car/recents` with `past=True`, which additionally requires a `source` scope,
  with exactly one identity filter (`vdp_url`, `stock_no` or `vin`). It sends `rows=10`, `nodedup=true`
  (keep syndicated copies) and `append_api_key=false` (keep the key out of returned URLs), and caps the
  response size and time. Rows with a bad VIN or an unsafe `vdp_url` are dropped. Errors never echo the
  URL, because MarketCheck authenticates with a query parameter.
- `backend/app/retrieval.py`: `licensed_records()` runs first in recovery. Identity comes only from the
  seller's own listing: the exact listing URL, then the seller-scoped stock number. Two different VINs,
  or a VIN that differs from the user's, stop with `identity_conflict`. The bound VIN is then searched
  for syndicated copies. `last_seen_at_date` becomes each observation's date, and the seller's own record
  wins field disagreements. When active inventory holds nothing, one scoped past-inventory lookup follows
  (see "Past inventory as the last licensed resort"). Search runs only if MarketCheck found nothing.
- `backend/tests/test_licensed_recovery.py`: offline regressions for all of the above.
- **NeoVIN original MSRP:** `decode_neovin_msrp()` in `vehicle_data.py` calls
  `GET https://api.marketcheck.com/v2/decode/car/neovin/{vin}/specs` once for a known VIN and returns the
  one figure we are willing to call original MSRP. `attach_original_msrp()` in `retrieval.py` writes it to
  `Candidate.msrp`, with `evidence.msrp` sourced to the exact NeoVIN field and one `msrp` observation.
  Details in "Original MSRP from NeoVIN" below; offline tests in `backend/tests/test_neovin_msrp.py`.
- Configuration: `REVRANK_MARKETCHECK_API_KEY` in `.env`; `/api/health` reports `licensed_inventory_enabled`
  and `neovin_msrp_enabled`.

## Original MSRP from NeoVIN

A listing rarely states the factory sticker, and MarketCheck's own inventory `msrp` often just repeats the
asking price, so neither can fill "Original MSRP" on the review page. The NeoVIN decode can: it returns the
MSRP figures for the car as it was built. Confirmed live on 2026-09-14 for VIN `WBS33BA06NCJ75401`, which
returned `msrp: 86500`, `msrp_label: "oem_msrp"`, `oem_msrp: 93245`, `original_msrp: 93245`,
`combined_msrp: 93195`, `installed_options_msrp: 5700`, `delivery_charges: 995`, `mc_msrp: 93245`,
`build_specs_msrp: null`.

**Field priority.** The first available positive number among:

1. `oem_msrp`
2. `original_msrp`
3. `combined_msrp` (the as-built grand total)

Bare `msrp` is used only when `msrp_label` is `oem_msrp` or `original_msrp` and no named field contradicts
it; in the probe above the bare figure is $6,745 lower than the OEM one it is labeled with, which is why it
is never preferred. `build_specs_msrp`, `mc_msrp`, `installed_options_msrp` and `delivery_charges` are not
used as the sticker. When none of the three named fields is present, MSRP stays blank and the buyer can
still type it: no figure is derived from a bare or listing `msrp`.

**Where it runs.** Once per import, after the VIN is known:

- `POST /api/import` on the direct and pasted paths, for a VIN the buyer pasted, the URL carried, or the
  page showed (`backend/app/main.py`);
- `recover_listing()`, for the VIN bound by licensed inventory, the seller's stock number, or the buyer
  (`backend/app/retrieval.py`), including the VIN-decode-only outcome.

**Cost and rules.** One metered MarketCheck call per import, so an import is at most 3 inventory calls plus
1 decode. It is skipped when the candidate already has an MSRP (a buyer's value is never overwritten), when
no valid 17-character VIN exists, when `recovery_source=search`, and when `REVRANK_NEOVIN_ENABLED=false`.
A failure or an empty result is recorded as a `licensed` attempt and never blocks the import. The value is
labeled in the UI as coming from the NeoVIN OEM/original/combined field, stays editable, and unlocks
`% of original MSRP` as a sourced figure; a buyer edit marks it `user_confirmed` as before.

## Steps

### 1. Account and key

1. Create a free account at developers.marketcheck.com. Account creation and payment are yours to do,
   not an agent's.
2. Put the key in the local `.env` only: `REVRANK_MARKETCHECK_API_KEY=...`. Restart `scripts/dev.py`,
   because `.env` changes are not auto-reloaded.
3. Confirm with `curl -s http://127.0.0.1:8000/api/health`: `"licensed_inventory_enabled": true`.

### 2. Smoke-test the three lookups by hand (done 2026-09-13; see "Live results")

Don't repeat this; the responses are saved. For reference, it used a corpus listing with a known VIN, for example CarMax stock 70181882, VIN WBS1H9C3XHV887640. Keep the
key in an environment variable, not in shell history:

```sh
export MC_KEY="$(grep ^REVRANK_MARKETCHECK_API_KEY= .env | cut -d= -f2-)"
curl -s "https://api.marketcheck.com/v2/search/car/active?api_key=$MC_KEY&vin=WBS1H9C3XHV887640&nodedup=true&append_api_key=false" | python3 -m json.tool | head -60
curl -s "https://api.marketcheck.com/v2/search/car/active?api_key=$MC_KEY&vdp_url=https://www.carmax.com/car/70181882&append_api_key=false" | python3 -m json.tool | head -40
curl -s "https://api.marketcheck.com/v2/history/car/WBS1H9C3XHV887640?api_key=$MC_KEY" | python3 -m json.tool | head -60
```

Record for each lookup:

- whether the listing is found;
- the exact `vdp_url` format MarketCheck stores (with or without `www`, a trailing slash, query);
- whether `source` / `dealer` identify CarMax;
- whether `stock_no` matches the URL's stock number;
- `last_seen_at_date`;
- the price and miles against CarMax's own page.

Also check whether the free tier's "100 mile radius restriction" affects VIN and URL lookups at all, or
only location searches. If a `vdp_url` never matches, `licensed_records()` falls back to the stock
number; if neither matches, document it.

### 3. Measure coverage on the live corpus

Run the import harness with MarketCheck enabled, and search disabled so the two sources are measured
separately. Then run with both enabled:

The harness is a dry run until you add `--spend`, and prints the worst-case cost first. The full corpus
is 21 imports (up to 84 MarketCheck calls with the NeoVIN decode on). Ask the user before spending that much:

```sh
.venv/bin/python scripts/eval_imports.py --source marketcheck                 # dry run: prints the cost
.venv/bin/python scripts/eval_imports.py --source marketcheck --only carmax --spend
```

For each of the 21 cases, compare with the Tavily-only results already recorded (`.local/eval/`):

| Measure | Pass bar |
| --- | --- |
| Identity: VIN / year / make / model correct | 100%; a wrong car is worse than no car |
| Current price found (not only a past listing) | better than Tavily's CarMax rate |
| Mileage and location found | better than Tavily |
| Freshness: `last_seen_at_date` age | report the median; flag listings unseen for more than 7 days as possibly sold |
| Cost | calls used ÷ successful imports |

Record the per-site results in `docs/source-tests/marketcheck.md` and keep this plan's cost table current.

### 4. Map every useful field

`parse_listing()` in `vehicle_data.py` already maps these fields:

| MarketCheck field | Candidate field | Notes |
| --- | --- | --- |
| `vin` | evidence `vin` | must equal the bound VIN |
| `vdp_url` | observation `source_url` | validated like any URL; never fetched automatically |
| `price` | `price` (USD) | US market; label as the provider's last-seen price |
| `miles` | `mileage` (mi) | the odometer rule in `parsing-notes.md` still applies |
| `build.year/make/model/trim/transmission` | same fields | NHTSA decode cross-checks year/make/model |
| `dealer.city` + `dealer.state` | `location` | normalized to `City, ST`; `car_location` wins when present |
| `dealer.name/website/street/city/state/zip/phone` | `dealer` (DealerInfo) | the selling rooftop, business level only; see below |
| `carfax_1_owner`, `carfax_clean_title` | `history` (seller claim) | "if mentioned on dealer website": never verification |
| `last_seen_at_date` | observation `observed_at` | the only real freshness signal |
| `dom` / `dom_active`, `first_seen_at_date` | same fields | days on market, shown as context |

The dealer block is business-level identity and contact detail, never a rating: RevRank constructs a
keyless Google Maps search and BBB/DealerRater lookup URLs from the reported name and address and stops
there. It rides on the payload already fetched for the listing, so it costs no extra call. Only the
seller's own record supplies it, because a syndicated copy may name a marketplace instead of the
rooftop. Shape and rules: `docs/API_CONTRACT.md`, "DealerInfo".

Add these fields:

- `stock_no`, as evidence;
- `exterior_color` and `interior_color`, which need new Candidate fields.

### 5. Add History by VIN (not built yet)

`GET https://api.marketcheck.com/v2/history/car/{vin}` returns every past listing of the VIN: listing
id, price, miles, source, `vdp_url`, seller location, first/last-seen dates. It costs $0.006 per call.
Use it the way vininspect is used today, but licensed and dated:

1. Add `vin_history(settings, vin)` in `vehicle_data.py`, with the same bounded client, error handling
   and URL validation as `inventory_search()`.
2. In `recover_listing()`, call it once after the VIN is bound, and only if a current price is missing
   or the user asks for price history.
3. Store the entries as historical records: they appear in the source list and the price timeline, and
   never fill today's price or mileage.
4. Show a small "Price history" list on the review page, with the date and the seller.

### 6. Freshness and availability rules

- Show "Last seen by MarketCheck on <date>" next to licensed values. A last-seen date is not a live
  availability check.
- If `last_seen_at_date` is more than 7 days old, warn "possibly sold". Never call it sold.
- If the seller's page later shows a different price, the live page wins, and the licensed value stays
  as a dated observation.

### 7. Budget, rate limits, caching

- Done: `usage.py` counts calls per month in `.local/usage.json`, refuses them at the limit, and
  reports them on `/api/health`. In `auto` mode, a refused MarketCheck call falls back to search.
- Respect 5 calls/s on Free and Basic. Done: `401` (bad key), `403`, `422` (pagination / bad parameters)
  and `429` (rate limit) carry their meaning in the attempt message instead of a bare status code.
- The meter is not the remaining quota. It counts the calls this checkout sent, and on Render `.local/`
  is ephemeral, so a deploy resets it. Only the provider's refusal is authoritative.
- Cache responses per VIN for 24 hours, only if the license allows storage (step 8). The browser already
  caches whole imports for 24 hours by request.

### 8. Rights check before anyone else sees the data

The pricing page does not address display, storage, caching or attribution. Before RevRank shows
MarketCheck data to anyone but yourself:

1. Read MarketCheck's API terms and data license. Confirm in writing: display to end users, storage
   duration, caching, attribution wording, and resale limits.
2. Record the answers in `docs/PRODUCT_BRIEF.md` under data rights, and set the UI label to match.
   Until then, keep usage personal and local, as today.

### 9. Tests

- Offline: extend `backend/tests/test_licensed_recovery.py` with history records (never filling current
  values), stale last-seen warnings, budget cut-off, and 401/422/429 messages. Build fixtures from real
  response shapes captured in step 2, with synthetic VINs.
- Live: steps 2–3, repeated whenever the plan or the corpus changes.

### 10. Rollout order

1. Free-tier key, steps 1–3, decision recorded.
2. If it's worth it: steps 4–7 and 9, and the licensed badge in the UI.
3. Step 8 before any shared or public use.
4. Keep Tavily as the fallback for listings MarketCheck does not carry, or drop it if coverage makes it
   redundant.

## Sources

- MarketCheck pricing: https://www.marketcheck.com/apis/pricing
- MarketCheck inventory search: https://docs.marketcheck.com/docs/api/cars/inventory/inventory-search
- MarketCheck history by VIN: https://docs.marketcheck.com/docs/api/cars/vehicle-history/history-by-vin
- Tavily pricing: https://www.tavily.com/pricing
- Tavily search API: https://docs.tavily.com/documentation/api-reference/endpoint/search
