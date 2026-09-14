# Comparison and browsing ideas

Brainstormed 2026-09-13 from buyer discussions: AnandTech, Bogleheads and Hacker News threads, a buyer's
published comparison spreadsheet, and dealer/consumer guides. Reddit could not be read: it blocks this
research tool. These are proposals, not commitments. Each one notes what RevRank already has, and
whether it needs a paid call (see "Paid API budget" in `AGENTS.md`).

## What buyers actually do today

| Pattern | What they do | Where it breaks |
| --- | --- | --- |
| Normalize price against miles | "Cost per mile driven" (price ÷ miles), or pairwise: $100 more for 2,360 fewer miles = $0.04 a mile | Done by hand in a spreadsheet, per pair |
| Think in ownership horizon | If you drive 12k mi/yr for 6 years, both cars add 72k; paying for low miles may buy little | Needs annual mileage and years held, which listings never ask for |
| Total cost, not sticker | Price + insurance + fuel + maintenance + depreciation (Edmunds TCO, Bogleheads threads) | Scattered across sites; insurance needs a quote per car |
| Out-the-door price | Email dealers for an OTD quote, track quotes in a spreadsheet; doc fees and add-ons hide in the final price | Advertised price ≠ what you pay |
| Weighted scorecard | Excel with weighted criteria (price, TCO, power, MPG, cargo); then test-drive the top 2–3 | Subjective factors (comfort, looks, feel) don't fit the sheet |
| Model and history over mileage | Reliability of the model, maintenance records, accident/title history, mileage pattern per year | Mostly "unknown" in listings |
| Watch the market | Daily searches or meta-search (AutoTempest, Autolist); days on market and price drops signal leverage | Tedious; alerts need a service |

## A. Analysis ideas that save time

Ordered from most value per effort.

1. **Differences-only table.** Hide rows where every car is equal. Lead with the three biggest
   differences ("$3,100 cheaper · 9,000 fewer miles · 2 years older"). *Have:* CompareTable rows. *Cost:* none.
2. **Pairwise trade-off line.** For each pair: "Car B costs $1,200 more for 14,000 fewer miles, $0.09 a
   mile" and "1 model year newer for $2,000". This replaces the buyer's spreadsheet step. *Have:* price,
   mileage, year. *Cost:* none.
3. **Ownership-horizon lens.** Use the existing `annual_mileage` and `ownership_years` preferences to
   show each car's mileage at resale ("both about 110k when you sell"). An optional cost per ownership
   mile uses the buyer's own assumed lifespan, labeled as an assumption. *Cost:* none.
4. **Must-have knockout.** Check each car against `must_haves` (already a preference): met / not
   mentioned / missing. "Not mentioned" must never read as "missing". *Cost:* none.
5. **Recalls and complaints without an LLM.** The NHTSA recall, complaint and rating lookups already
   exist as analyst tools. Run them deterministically at compare time: "N recalls for this model
   year; most complaints: <component>". These are model-year records, labeled as not this VIN.
   *Cost:* free API.
6. **Days on market and price history.** MarketCheck's inventory response already includes `dom`,
   `dom_active` and `first_seen_at_date`. The M2 showed 144 active days, which is negotiation leverage.
   Mapping them costs **no extra call**. Price history (the M2 had 14 dated listings) costs 1 call per
   VIN: offer it as an opt-in button that shows the cost.
7. **Out-the-door estimate.** Price + the buyer's sales tax rate + doc fee + transfer or delivery fee
   (TrueCar excerpts already carry "$149 transfer"). The buyer enters the rates; the result is labeled as
   an estimate, and the comparison uses OTD instead of sticker.
8. **Weighted scorecard with sensitivity.** Turn `priorities` into weights with sliders. Add
   buyer-rated rows for test-drive feel and looks (1–5). Say when the winner flips: "B wins unless price
   matters more than 40%". Scores stay deterministic; the LLM only explains.
9. **Seller outreach kit.** Per car, a copyable email asking for the out-the-door price, fees and
   service records, pre-filled with VIN, stock number and the questions RevRank already generates.
   Buyers already do this by hand.
10. **History checklist.** Accidents, owners, title and service records per car as *unknown / seller
    claim / verified*, with where to get each one. Missing history never means clean history.

## B. Browsing a set of cars

1. **Shortlist beyond three.** Save up to about 10 cars and compare any 2–3. Keep the three-car
   report, but let the shortlist be longer.
2. **Benchmark car.** Pin one car; every other card shows deltas against it ("+$2,100, −8k mi, same
   year").
3. **Sort and filter the shortlist** by price, mileage, $/mile, OTD, distance or score, in one click.
4. **Bulk paste.** Paste several links at once; they import in a queue, each hitting the 24 h cache first.
5. **"Send to RevRank" bookmarklet.** From the listing page open in the buyer's own browser, send the
   page text the buyer can already see. This is user-initiated, like pasting, not a bot. It also covers
   CarMax and Carvana for free.
6. **Refresh saved cars on demand.** One MarketCheck call per car. Show "price dropped $1,000 since you
   saved it" or "not seen for 9 days: possibly sold", with the call count shown before running.
7. **Notes, photos and test-drive ratings** per car, kept in the browser draft.
8. **Export.** CSV / Google Sheets export (spreadsheet users) and a print-friendly one-pager (exists:
   Print report). A shareable read-only link needs hosting and data-rights review first.
9. **Distance view.** Distance from the buyer's location (preference exists) and whether the car needs a
   transfer or trip.
10. **Keyboard and mobile.** A sticky header table with ←/→ to page through cars, and swipe on mobile.

## First slice (built 2026-09-14)

The report's side-by-side table (`frontend/src/ReportView.tsx`, logic in `frontend/src/compare.ts`) now has:

- **Pinned benchmark (B2):** "Compare against" picks the car every other column is measured against; it
  leads the table. Green chips are better for the buyer and amber chips are worse.
- **Differences only (A1):** rows identical for every car are hidden and counted (on by default).
- **Trade-off row (A2):** price gap against mileage gap relative to the benchmark: "$1,200 more for
  14,000 mi fewer ($0.09 per mi avoided, about 14 months of your driving)", or "better on both" /
  "worse on both". It is computed only when both prices share a currency and both mileages share a
  confirmed unit.
- **Mileage when you sell (A3):** the backend's projected odometer (annual mileage × years), shown only
  when every car's mileage unit is confirmed and shared.
- **Must-have rows (A4):** the backend's conservative match: "Listed" or "Not mentioned", never "no".

No paid calls. Next: A6 days on market, free inside the MarketCheck response already fetched.

## Sources

- AnandTech forum, how members compare cars: https://forums.anandtech.com/threads/how-do-you-compare-cars-when-deciding-what-to-buy.2491333/
- Money@30, used-car evaluation spreadsheet (cost per mile): https://moneyat30.com/used-car-evaluation-spreadsheet/
- Bogleheads, cost of ownership threads: https://www.bogleheads.org/forum/viewtopic.php?t=284407, https://www.bogleheads.org/forum/viewtopic.php?t=442311
- Hacker News, AI tool to watch used-car inventory: https://news.ycombinator.com/item?id=42662347
- Hacker News, car buying "death march" (fees, OTD quotes by email): https://news.ycombinator.com/item?id=40922902
- Hacker News, new car buying algorithm: https://news.ycombinator.com/item?id=39507402
- Nalley, comparing two used cars with different mileage (ownership horizon): https://www.nalleycars.com/blog/how-to-compare-two-used-cars-with-different-mileage
- CNBC, cost per remaining mile: https://www.cnbc.com/2022/12/27/how-to-find-the-best-used-car-for-the-money.html
- Edmunds True Cost to Own: https://www.edmunds.com/car-buying/true-cost-to-own-tco.html
- NerdWallet, out-the-door price: https://www.nerdwallet.com/auto-loans/learn/what-is-out-the-door-price
