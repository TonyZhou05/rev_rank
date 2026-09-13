# Independent source and crawler test brief

## Status

Completed the offline source-policy, guarded-URL, and representative JSON-LD
extraction tests on 2026-09-13. No live marketplace crawling was run because
`REVRANK_LIVE_FETCH_ENABLED` is false by default and no source-specific rights or
allowlist were configured.

## Major sources

| Domain | Default result | Why |
| --- | --- | --- |
| caredge.com | restricted | Published terms require authorization for automated extraction and commercial reuse |
| cargurus.com | restricted | Published terms restrict scraping/data mining and reuse |
| autotrader.com | unreviewed | No adapter or rights review configured |
| cars.com | unreviewed | No adapter or rights review configured |
| carfax.com | unreviewed | No approved vehicle-history integration |
| truecar.com | unreviewed | No adapter or rights review configured |
| classic.com | unreviewed | Licensed API may be evaluated separately; no local approval configured |

`restricted`, `unreviewed`, and `unsupported` are policy/operational statuses; none
means the site was successfully crawled. Enabling a host locally is an operator
configuration and is not legal clearance.

## Tests

`tests/test_sources_and_extraction.py` verifies the source matrix, JSON-LD parsing
without network access, rejection of loopback/credential/nonstandard-port URLs,
and the opt-in live-fetch default. The backend API suite separately exercises
pasted-text import, comparison, report persistence, and restricted URL behavior.

Run: `REVRANK_LIVE_FETCH_ENABLED=false .venv/bin/python -m pytest backend/tests tests -q`.

## Live test procedure for a later authorized run

After a source-specific rights review, enable only exact hosts in
`REVRANK_ALLOWED_DOMAINS`, use the guarded fetcher, run low-rate GET requests, and
record HTTP/robots/access-challenge outcomes. Never use credentials, proxies,
cookies, CAPTCHA bypass, stealth behavior, or arbitrary marketplace crawling.
Record the date, URL pattern, response status, extraction completeness, and terms
of any resulting license. A blocked or incomplete page is a failed import with a
pasted-text/manual fallback, not a successful test.
# Live-source follow-up

The user requested ten US shopping domains be enabled and tested. Actual network
results, one brief per site, and a repeatable probe script are now documented in
`docs/source-tests/README.md`. This supersedes earlier policy-only checks as the
live-access evidence. Two listings produced partial extraction; none was validated
as fully accurate. Ordinary tests remain offline even when local live fetching is enabled.
