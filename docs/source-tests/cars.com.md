# cars.com

Checked: 2026-09-13T02:48:29.406987+00:00

- URL: https://www.cars.com/shopping/
- Page type: inventory
- Result: **blocked** — robots.txt could not be checked; collection is blocked conservatively.
- Enabled in local configuration; runtime access checks remain enforced.
- A single probe does not establish domain-wide coverage or reuse rights.

```json
{
  "domain": "cars.com",
  "url": "https://www.cars.com/shopping/",
  "page_type": "inventory",
  "checked_at": "2026-09-13T02:48:29.406987+00:00",
  "requests": [
    {
      "url": "https://www.cars.com/robots.txt",
      "http_status": 403,
      "bytes": 0
    }
  ],
  "status": "blocked",
  "message": "robots.txt could not be checked; collection is blocked conservatively.",
  "elapsed_seconds": 0.1
}
```
