# carvana.com

Checked: 2026-09-13T02:48:28.676764+00:00

- URL: https://www.carvana.com/vehicle/4711856?refSource=home
- Page type: listing
- Result: **blocked** — Source denied access or rate-limited the request; no bypass attempted.
- Enabled in local configuration; runtime access checks remain enforced.
- A single probe does not establish domain-wide coverage or reuse rights.

```json
{
  "domain": "carvana.com",
  "url": "https://www.carvana.com/vehicle/4711856?refSource=home",
  "page_type": "listing",
  "checked_at": "2026-09-13T02:48:28.676764+00:00",
  "requests": [
    {
      "url": "https://www.carvana.com/robots.txt",
      "http_status": 200,
      "bytes": 636
    },
    {
      "url": "https://www.carvana.com/vehicle/4711856?refSource=home",
      "http_status": 403,
      "bytes": 0
    }
  ],
  "status": "blocked",
  "message": "Source denied access or rate-limited the request; no bypass attempted.",
  "elapsed_seconds": 0.55
}
```
