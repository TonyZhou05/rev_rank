# carfax.com

Checked: 2026-09-13T02:48:30.771655+00:00

- URL: https://www.carfax.com/cars-for-sale
- Page type: inventory
- Result: **blocked** — Source denied access or rate-limited the request; no bypass attempted.
- Enabled in local configuration; runtime access checks remain enforced.
- A single probe does not establish domain-wide coverage or reuse rights.

```json
{
  "domain": "carfax.com",
  "url": "https://www.carfax.com/cars-for-sale",
  "page_type": "inventory",
  "checked_at": "2026-09-13T02:48:30.771655+00:00",
  "requests": [
    {
      "url": "https://www.carfax.com/robots.txt",
      "http_status": 200,
      "bytes": 1344
    },
    {
      "url": "https://www.carfax.com/cars-for-sale",
      "http_status": 403,
      "bytes": 0
    }
  ],
  "status": "blocked",
  "message": "Source denied access or rate-limited the request; no bypass attempted.",
  "elapsed_seconds": 0.34
}
```
