# Listing browse rights — user-supplied VDP import (RevRank)

**Date:** 2026-09-15  
**Ask:** Tongli via Lead — prefer private browse / page-inspect of buyer-provided listing URLs when Direct is blocked, before heavy MarketCheck/Tavily.  
**Scope:** Public ToS / robots / observed fetch posture. **Not counsel clearance.**  
**Paid APIs:** Parked (no new MarketCheck/Tavily spend for this spike).

---

## PR checklist for Debug (ship-gate)

**OK to build (feature-flag spike):**

- [ ] Headless / Codex-style browse **only** of a **buyer-pasted or buyer-opened VDP URL** (single page).
- [ ] Extract **structured listing fields only**: price, miles/odometer, VIN, year/make/model/trim, dealer name/location, stock # if present.
- [ ] Trigger **only after** Direct fetch failed (403/block/empty) **and** MarketCheck miss/unavailable for that VIN/URL — **do not** replace MC when MC already returns the row.
- [ ] Persist **evidence**: source URL, fetch timestamp, HTTP/status or browse outcome, extracted field map, hash of raw snippet (not full HTML dump in product logs if avoidable).
- [ ] Label provenance: `source=user_vdp_browse` vs `source=marketcheck` vs `source=direct`.
- [ ] Rate-limit: **1 URL per user import action**; no queue/follow of related inventory, SRP, or sitemap.
- [ ] Host allowlist starts narrow (known VDP patterns); unknown hosts → hold / manual confirm.

**Refuse in the same PR / path:**

- [ ] Review sites & review bodies (DealerRater, BBB reviews, Google Maps reviews, Cars.com reviews, Yelp, Reddit car threads, etc.) — **link-out only**, never scrape/quote (aligns Slice B).
- [ ] Dealer-signal / reputation boards used as review substitutes; AG/board **news** stays Tavily-cited path, not VDP browse.
- [ ] Bulk marketplace crawl, SRP pagination, “similar vehicles,” sitemap harvest, inventory index rebuild.
- [ ] Bypass / evade bot walls (residential proxy farms, CAPTCHA farms, cookie stuffing) — if browse fails, **stop and surface miss**, don’t escalate.
- [ ] Training / redistrib of scraped HTML corpora; no “we have a license because user pasted URL.”
- [ ] CarMax (and similar) **Direct HTTP** when already 403 — don’t hammer; one browse attempt max per import if flagged on.

**CarMax / robots constraints (observed + ToS):**

- Direct `carmax.com` fetch from box: **403 Access Denied** (terms page + `robots.txt` both denied from this environment — Akamai). Treat Direct as **already blocked**.
- CarMax ToS (public): personal noncommercial license; **excludes** collection/use of product listings, descriptions, or prices; **prohibits** robot/spider/scrape/data-mine without prior written consent.  
  Cite: https://www.carmax.com/terms
- Spike OK as **user-initiated single-VDP fallback**, but treat CarMax as **high ToS / high bot-wall** — prefer MC when it works; browse is last resort, not primary.

---

## Bottom-line recommendation

- **Primary path stays:** Direct (when it works) → **MarketCheck when Direct blocked or thin** → **browser fallback only on user-supplied VDP** after Direct fail **+** MC miss.
- **Do not** make headless browse the default for marketplace hosts; **do not** replace MC when MC succeeds.
- **Clearly-out stays banned:** review-site scrape, bulk SRP/inventory crawl, bot-wall evasion. User-initiated single-VDP paste is the **narrow, feature-flaggable** gray zone — ship spike with guards; don’t wait for counsel-perfect ToS.

---

## Q1 — Buyer pastes/opens a VDP URL: headless browse + extract OK?

**Answer:** **Conditionally OK for product spike** as *personal-use import assist* on **that one URL** (price / miles / VIN / dealer / YMMT), **not** as a license to scrape the publisher’s catalog or any review surface.

| Surface | Verdict |
|--------|---------|
| Buyer-pasted **vehicle detail page (VDP)** | **Allow (flagged)** — extract listing facts for *this* candidate only |
| Marketplace **SRP / search / inventory index** | **Hold / ban** |
| **Review sites** / review widgets on VDPs | **Still no** — do not extract review text/scores for product; Strip or ignore |
| Dealer site VDP (non-review) | **Same as VDP allow**, still single-URL, no sitewide crawl |

**Why the distinction:** Pasting a URL the buyer already chose looks like assisting *their* viewing of a public listing (closer to “user asked us to open this page”), vs RevRank independently harvesting review corpora or market inventories. That distinction **reduces product/reputational risk**; it does **not** erase host ToS that forbid automated retrieval.

**Hard truth:** User-submitted URL **≠** publisher license for redistribution, training, or building a competitive inventory DB.

---

## Q2 — CarMax / Carvana ToS risk for automated browse of that single user-asked URL

**Honest:** Both publish **broad anti-bot / anti-scrape** terms. A headless agent opening one VDP is still “automated access” under those texts. User initiation **mitigates narrative/product risk**, not contractual text.

### CarMax
- License: personal, **noncommercial**; does **not** include collection/use of listings, descriptions, or prices; no data mining/robots/extraction tools.  
- Prohibited: robot, spider, site search/retrieval app, or other manual/automatic device to retrieve, index, scrape, data-mine, or gather Content without **express prior written consent**.  
- Cite: https://www.carmax.com/terms  
- Ops: Direct already **403** from non-browser clients here; expect browse friction / challenges.

### Carvana
- Agreement binds entities that harvest/crawl/index/scrape by automated **or manual** process.  
- Prohibits bots/scripts/automated process; prohibits copy/harvest/crawl/index/scrape/spider/mine/extract/aggregate/store Content unless **explicit written** agreement.  
- robots.txt disallows broad inventory/search paths (`/search/*`, `/inventory/`, `/browse/*`, etc.).  
- Cite: https://www.carvana.com/terms-of-use ; https://www.carvana.com/robots.txt  

**Risk take:** Single user-asked VDP import = **lower** than bulk CarMax/Carvana crawl, still **medium–high contractual** if automated. Prefer MC licensed feed; browse = fallback only.

---

## Q3 — Recommend: browser-fallback after Direct blocked + MC miss, or primary?

**Recommend: fallback only — after Direct blocked *and* MC miss.**

| Order | Path | Role |
|------|------|------|
| 1 | Direct fetch | Cheap; honor 403/robots — no retry storms |
| 2 | **MarketCheck** | Keep when it works; **do not replace** |
| 3 | **Browser fallback** | User-supplied VDP only; feature-flag; extract fields; stop on challenge |
| — | Tavily | Not for VDP field fill; keep for diligence/news (existing) |

**Product:** Feature-flag spike OK. Focus **clearly-out vs user-initiated VDP paste**. Don’t block the spike on counsel-perfect ToS; document host red lines and refuse bulk/review.

---

## PM — ToS / scraping risk by major US hosts (public reading)

| Host | Public red line (summary) | robots / ops note | User-paste VDP browse | Stance for RevRank |
|------|---------------------------|-------------------|----------------------|--------------------|
| **CarMax** | No robots/scrape/data-mine; no collection of listings/prices under personal license | Direct often **403**; ToS page blocked to simple clients | Medium–high | Fallback only; prefer MC |
| **Carvana** | Broad ban on bots + scrape/harvest/store | robots blocks search/inventory paths | Medium–high | Fallback only; prefer MC |
| **Cars.com** | No automated mechanism (robots/crawlers/spiders) to access/query/scrape | robots disallows many shopping/review paths | Medium–high | Fallback only; **never** scrape `/reviews/` |
| **Autotrader / Cox** | No automated collect/index; no systematic extraction (Cox Visitor Agreement; Autotrader B2B ToS similar) | robots has many Disallows; REP mentioned in Cox systematic-extraction carve for *conforming* crawlers — **does not** greenlight commercial scrape | Medium | Fallback only; prefer MC |
| **Dealer.com** (dealer sites) | Corporate ToS: no materials via means not intentionally made available; Cox/DDC integration terms ban scraping DDC products | Dealer-hosted VDPs vary | Medium (site-dependent) | Single buyer VDP OK for spike; no sitewide crawl |
| **Independent dealer sites** | Often thin/generic ToS; still copyright + CFAA-ish access norms | Highly variable | Low–medium | Prefer; still single-URL only |

**Allowed surfaces (spike):** buyer-chosen **VDP HTML** → listing facts for one candidate.  
**Hold:** any host that serves only behind login, CAPTCHA loop, or explicit “no automated access” challenge after one try → record miss, don’t escalate.  
**Park paid APIs** for this spike; reuse existing MC when already wired.

---

## Risk ladder (low → high)

1. **Low:** Buyer pastes fields manually; or MC/licensed feed fills candidate.  
2. **Low–medium:** Direct GET of public VDP that returns 200 and is not robots-disallowed for that path.  
3. **Medium:** Headless browse of **one user-pasted VDP** to extract listing facts (no reviews, no follow links) — **spike zone**.  
4. **Medium–high:** Same on CarMax/Carvana/Cars.com despite ToS anti-bot language.  
5. **High:** Retry storms, proxy/CAPTCHA evasion, storing full HTML corpora, redistrib/training.  
6. **Clearly out / banned:** Review-site scrape; bulk SRP/inventory crawl; dealer reputation harvest; marketplace mirroring.

---

## Distinguishing personal-use import vs bulk marketplace crawl

| | Personal-use import (allow path) | Bulk marketplace crawl (ban) |
|--|----------------------------------|------------------------------|
| Trigger | Buyer pastes/opens **one** URL | Scheduler / search harvest / sitemap |
| Volume | 1 page / import action | Many URLs, pagination, inventory |
| Purpose | Fill *this* candidate for *this* user | Build/refresh RevRank catalog or comps DB |
| Retention | Field map + URL + timestamp (+ short evidence) | Full pages / corpora / training sets |
| Reviews | Never | Never (still) |

---

## Evidence retention (brief)

- Keep: URL, UTC time, outcome code, extracted fields, content hash / short quote of price+VIN line if needed for audit.  
- Avoid: long-term raw HTML lakes; no reuse for model training or public redistrib.  
- TTL: align with candidate lifetime; purge browse artifacts with candidate delete.  
- User paste ≠ license — retention is **operational evidence**, not a content license grant.

---

## What stays banned

- Review-site scrape / in-app review quotes (DealerRater, BBB review bodies, Maps, Cars.com reviews, Yelp, etc.) — **link-out only** (see Slice B rights).  
- Bulk marketplace crawl, SRP pagination, “all inventory at dealer,” sitemap harvest.  
- Bot-wall evasion and credentialed session hijack.  
- Using browse output for ML training or third-party redistrib.  
- Treating user URL paste as publisher permission.

---

## Open decisions for Tongli / Lead

1. **Host allowlist v1:** CarMax/Carvana in flag from day one, or **independent dealers + Cars.com/AT only** until MC coverage reviewed?  
2. **Counsel touch:** spike without counsel vs 30-min read of CarMax/Carvana clauses before production flag-on? (Product: don’t block spike; may block **default-on**.)  
3. **Failure UX:** when browse challenged, show “paste price/miles/VIN” manual form vs silent miss?  
4. **Evidence TTL** and whether raw HTML ever leaves the worker (recommend: fields + hash only).  
5. **MC billing:** confirm fallback order so browse never races MC when MC would hit.

---

## Cites (public)

- CarMax Terms of Use — https://www.carmax.com/terms  
- Carvana Terms of Use — https://www.carvana.com/terms-of-use  
- Carvana robots.txt — https://www.carvana.com/robots.txt  
- Cars.com Terms — https://www.cars.com/about/terms/  
- Cox Automotive Visitor Agreement — https://www.coxautoinc.com/visitor-agreement/  
- Autotrader B2B ToS (automated means) — https://b2b.autotrader.com/terms-of-service/  
- Dealer.com Terms of Use — https://www.dealer.com/company/terms-of-use/  

*Research reading of public ToS/docs and observed HTTP posture — not legal advice / not counsel clearance.*
