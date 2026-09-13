# kbb.com

Checked: 2026-09-13T02:49:21.889995+00:00

- URL: https://www.kbb.com/cars-for-sale/
- Page type: listing
- Result: **partial** — Automated extraction only; field accuracy not independently verified.
- Enabled in local configuration; runtime access checks remain enforced.
- A single probe does not establish domain-wide coverage or reuse rights.

```json
{
  "domain": "kbb.com",
  "url": "https://www.kbb.com/cars-for-sale/",
  "page_type": "inventory",
  "checked_at": "2026-09-13T02:49:21.889995+00:00",
  "requests": [
    {
      "url": "https://www.kbb.com/robots.txt",
      "http_status": 200,
      "bytes": 4581
    },
    {
      "url": "https://www.kbb.com/cars-for-sale/",
      "http_status": 301,
      "bytes": 0
    },
    {
      "url": "https://www.kbb.com/robots.txt",
      "http_status": 200,
      "bytes": 4581
    },
    {
      "url": "https://www.kbb.com/cars-for-sale/all/",
      "http_status": 308,
      "bytes": 0
    },
    {
      "url": "https://www.kbb.com/robots.txt",
      "http_status": 200,
      "bytes": 4581
    },
    {
      "url": "https://www.kbb.com/cars-for-sale/all",
      "http_status": 200,
      "bytes": 1306275
    },
    {
      "url": "https://www.kbb.com/robots.txt",
      "http_status": 200,
      "bytes": 4581
    },
    {
      "url": "https://www.kbb.com/cars-for-sale/vehicle/789754790?allListingType=all&clickType=spotlight",
      "http_status": 200,
      "bytes": 566357
    }
  ],
  "status": "partial",
  "message": "Automated extraction only; field accuracy not independently verified.",
  "discovered_listing_url": "https://www.kbb.com/cars-for-sale/vehicle/789754790?allListingType=all&clickType=spotlight",
  "extracted_fields": [
    "price",
    "currency",
    "mileage"
  ],
  "warnings": [
    "Conflicting price: 2065.0 versus 23955.0; first value retained for review.",
    "Conflicting price: 2065.0 versus 23780.0; first value retained for review.",
    "Missing make; confirm with the seller or enter it manually.",
    "Missing model; confirm with the seller or enter it manually.",
    "Missing year; confirm with the seller or enter it manually.",
    "Missing transmission; confirm with the seller or enter it manually.",
    "Missing location; confirm with the seller or enter it manually.",
    "Missing history; confirm with the seller or enter it manually.",
    "Currency is unknown; a bare $ does not establish USD or CAD. Price comparisons are withheld.",
    "Generation/variant matching is unverified; no external specifications were inferred.",
    "Extracted listing text and seller disclosures are not independent vehicle-history verification.",
    "Source page content is not retained; only extracted fields and short evidence references enter a saved report."
  ],
  "elapsed_seconds": 1.41
}
```
