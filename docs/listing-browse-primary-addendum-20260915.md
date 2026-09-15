# Addendum: browse PRIMARY for buyer-pasted VDP extract

**Date:** 2026-09-15  
**Parent:** [listing-browse-rights-20260915.md](listing-browse-rights-20260915.md)

## Product override (Tongli)

For **buyer-pasted VDP field extract** (price, miles, VIN, dealer, YMMT), **headless browse is PRIMARY** — not fallback-after-MC.

| Job | Order |
|-----|--------|
| Extract fields from URL buyer pasted | **Browse that VDP first** (feature-flag) |
| Licensed recovery / other enrichment | MC / Direct / Tavily as appropriate — **not** first for this extract job |
| Dealer diligence | Slice B path — **not** VDP browse |

## Unchanged rights red lines

- No review scrape/quote; no bulk SRP/sitemap; no bot-wall evasion
- Host allowlist; 1 URL/import; provenance `user_vdp_browse`; evidence rules
- Not counsel clearance — primary browse **raises** hit rate on high-ToS hosts → keep **default-off** until Tongli opts in; stop on challenge

