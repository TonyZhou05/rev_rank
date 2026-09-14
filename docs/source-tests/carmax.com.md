# carmax.com

Checked: 2026-09-13T02:48:28.285824+00:00

- URL: https://www.carmax.com/car/70108828
- Page type: listing
- Result: **blocked** — Source denied access or rate-limited the request; no bypass attempted.
- Enabled in local configuration; runtime access checks remain enforced.
- A single probe does not establish domain-wide coverage or reuse rights.

```json
{
  "domain": "carmax.com",
  "url": "https://www.carmax.com/car/70108828",
  "page_type": "listing",
  "checked_at": "2026-09-13T02:48:28.285824+00:00",
  "requests": [
    {
      "url": "https://www.carmax.com/robots.txt",
      "http_status": 200,
      "bytes": 1456
    },
    {
      "url": "https://www.carmax.com/car/70108828",
      "http_status": 403,
      "bytes": 0
    }
  ],
  "status": "blocked",
  "message": "Source denied access or rate-limited the request; no bypass attempted.",
  "elapsed_seconds": 0.39
}
```
