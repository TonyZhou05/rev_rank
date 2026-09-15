# Indie-dealer VDP browse — rights note (RevRank)

**Date:** 2026-09-15  
**Ask:** Tongli approved expanding headless browse beyond `MARKETPLACES` allowlist to **independent / franchise dealer VDPs** (buyer-pasted single URL).  
**Fail today:** `https://www.bmwbuffalo.com/inventory/new-2026-bmw-330i-awd-sedan-3mw89cw02t8g83036/` — host not in `MARKETPLACES`; `is_listing_url=None`.  
**Parent:** [listing-browse-rights-20260915.md](listing-browse-rights-20260915.md)  
**Status:** Product spike OK under guards below. **Not counsel clearance.** No paid API / no new MC spend for this note.

---

## Debug PR checklist (ship-gate)

**OK to ship (feature-flag):**

- [x] Allow browse when URL matches **VDP shape** (VIN-in-path or clear single-vehicle inventory path) — not only when host ∈ `MARKETPLACES`.
- [x] Still **1 URL per import**; navigate only that URL; no follow of related/similar/inventory index.
- [x] Provenance `user_vdp_browse` + evidence (URL, timestamp, status/outcome, field map, content hash).
- [x] Stop-on-challenge / 403 / CAPTCHA — surface miss → fall through (MC if available); **no** residential proxy / unlocker / stealth.
- [x] Keep review-host deny list; strip/ignore review widgets on dealer pages.
- [x] Unknown / ambiguous paths → refuse + paste hint (do not “guess crawl”).

**Refuse in same PR:**

- [x] SRP / search / homepage / `/inventory` with no vehicle id or VIN.
- [x] Sitemap, bulk inventory harvest, pagination, “similar vehicles.”
- [x] Review scrape/quote (DealerRater, BBB, Maps, Cars.com reviews, etc.).
- [x] Expanding a static franchise host list as the primary gate (unmaintainable; see §4).

---

## 1. URL patterns OK (dealer inventory + VIN / clear VDP)

Allow **buyer-pasted** HTTPS URLs that look like a **single vehicle detail page**, e.g.:

| Shape | Examples (pattern class) |
|-------|--------------------------|
| Path contains a **17-char VIN** (check-digit OK) | `/inventory/...-3MW89CW02T8G83036/`, `/vehicle/WBA…`, `?vin=…` |
| Dealer inventory **slug + id** | `/inventory/{new\|used}-…-{stock\|vin}`, `/VehicleDetails/…`, `/autos/…/{id}` |
| Common DMS/VDP paths with a vehicle token | `/inventory/…/{stock#}`, `/vdps/…`, `/new-inventory/…/{id}`, `/used-cars/…/{id}` |

**Minimum gate for indie/franchise hosts:** `is_listing_url`-equivalent for unknown hosts → **True only if** (a) VIN in URL with valid check digit, **or** (b) path matches a conservative VDP regex family **and** is not an SRP/index path. Prefer (a) when present (bmwbuffalo example).

Host may be any non-review, non-social dealer site — **do not** require membership in `MARKETPLACES`.

---

## 2. Refuse (hard)

| Refuse | Why |
|--------|-----|
| Homepage, `/`, contact, service, parts, finance | Not a VDP |
| `/inventory`, `/new-inventory`, `/used-vehicles`, search, `?q=`, filters, sort, pagination | SRP / index — bulk risk |
| Sitemap, XML feeds, JSON inventory endpoints as crawl targets | Bulk harvest |
| Review hosts / review bodies / star widgets as extract targets | Slice B + listing rights |
| Off-domain redirects to marketplaces’ SRPs or review sites | Scope creep |
| Multiple URLs, “open all in stock,” dealer sitewide crawl | Violates 1 URL/import |

Ambiguous path with **no VIN and no vehicle id token** → **refuse** (safer than false-positive SRP browse).

---

## 3. Risk vs marketplace hosts

| | Big marketplaces (CarMax, Carvana, Cars.com, …) | Indie / franchise dealer sites |
|--|--------------------------------------------------|--------------------------------|
| Bot wall | Often **high** (Akamai etc.); Render Chromium frequently **403** | Often **lower**; more likely to return HTML |
| ToS | Explicit anti-scrape / anti-bot common | Vary widely; many franchise sites silent or soft |
| Ops | Browse miss → **MC fallthrough** (accepted) | MC coverage uneven; browse may be the only free path |
| Product risk | Higher contractual narrative if automated | Lower bot friction; still **user-initiated single-URL only** — not a license |

**Takeaway:** Expanding to dealer VDPs is **ops-attractive** (pages more often render) and still **ToS-gray**. Same red lines: 1 URL, stop-on-challenge, no bulk, no reviews. Franchise stacks (DealerInspire, Dealer.com, etc.) differ — treat challenge the same: stop, don’t evade.

---

## 4. Allowlist approach — recommend **pattern-based VDP detector**

| Approach | Verdict |
|----------|---------|
| **Expand static host list** (`bmwbuffalo.com`, …) | **Reject as primary** — unbounded franchise/indie domains; constant miss like today’s fail |
| **Pattern-based VDP detector** on any non-denied host | **Recommend** — VIN-in-URL and/or inventory+id path; keep `MARKETPLACES` patterns for known listing-id schemes |
| Hybrid | Optional: soft denylist for known bad hosts; never rely on growing allowlist of dealer hostnames |

`browse_vdp_allowed`: review deny → VDP-shape True → allow; else refuse. `is_listing_url` should return **True/False for dealer VDP shapes**, not `None` forever for all non-marketplace hosts (or browse gate should call a sibling `is_dealer_vdp_url`).

---

## 5. OPS — Render 403 on big marketplaces still fail → MC

Live Render Chromium probes (2026-09-15): CarMax / Carvana / Cars.com / TrueCar / Edmunds browse → **HTTP 403**. Product path: Direct fail → browse blocked → **MarketCheck** recovers when licensed. **Accepted.** Keep `REVRANK_BROWSER_RECOVERY_ENABLED`; **no** proxy/unlocker.

Indie dealer VDPs are the complementary case: marketplace browse often empty; dealer VDP browse may succeed — still stop on challenge and keep MC as recovery when it applies.

---

## Constraints that MUST remain (unchanged)

1. **1 URL per import** — no SRP/sitemap/bulk crawl  
2. **Stop-on-challenge** — no residential proxy / unlocker / CAPTCHA solve  
3. **No review scrape/quote**  
4. **Evidence + provenance** `user_vdp_browse`  
5. **Not counsel clearance**

---

*Short rights / product guardrail only. Implementers: wire pattern gate in `browse_vdp_allowed` / `listing_url`; do not add paid APIs for this slice.*
