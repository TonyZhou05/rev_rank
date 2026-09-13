# truecar.com

Checked: 2026-09-13T02:49:16.226084+00:00

- URL: https://www.truecar.com/used-cars-for-sale/listings/
- Page type: listing
- Result: **partial** — Automated extraction only; field accuracy not independently verified.
- Enabled in local configuration; runtime access checks remain enforced.
- A single probe does not establish domain-wide coverage or reuse rights.

```json
{
  "domain": "truecar.com",
  "url": "https://www.truecar.com/used-cars-for-sale/listings/",
  "page_type": "inventory",
  "checked_at": "2026-09-13T02:49:16.226084+00:00",
  "requests": [
    {
      "url": "https://www.truecar.com/robots.txt",
      "http_status": 200,
      "bytes": 1172
    },
    {
      "url": "https://www.truecar.com/used-cars-for-sale/listings/",
      "http_status": 200,
      "bytes": 985623
    },
    {
      "url": "https://www.truecar.com/robots.txt",
      "http_status": 200,
      "bytes": 1172
    },
    {
      "url": "https://www.truecar.com/used-cars-for-sale/listing/1C6JJTAG8LL117141/2020-jeep-gladiator/?position=0&returnTo=%2Fused-cars-for-sale%2Flistings%2F&sourceType=marketplace&sponsored=true",
      "http_status": 200,
      "bytes": 480076
    }
  ],
  "status": "partial",
  "message": "Automated extraction only; field accuracy not independently verified.",
  "discovered_listing_url": "https://www.truecar.com/used-cars-for-sale/listing/1C6JJTAG8LL117141/2020-jeep-gladiator/?position=0&returnTo=%2Fused-cars-for-sale%2Flistings%2F&sourceType=marketplace&sponsored=true",
  "extracted_fields": [
    "make",
    "model",
    "year",
    "price",
    "currency",
    "mileage"
  ],
  "warnings": [
    "Multiple structured products found; fields may conflict. Review that this page describes one vehicle.",
    "Conflicting transmission: Automatic versus 8 Speed Automatic (850re); first value retained for review.",
    "Missing location; confirm with the seller or enter it manually.",
    "Missing history; confirm with the seller or enter it manually.",
    "Mileage unit is unconfirmed; mi is only the editor default. Mileage calculations are withheld until confirmed.",
    "Generation/variant matching is unverified; no external specifications were inferred.",
    "Extracted listing text and seller disclosures are not independent vehicle-history verification.",
    "Source page content is not retained; only extracted fields and short evidence references enter a saved report."
  ],
  "elapsed_seconds": 5.66
}
```
