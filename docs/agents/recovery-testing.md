# Search recovery regression tests

Owned files: `backend/tests/test_search_recovery.py` and this note. Production and
frontend changes belong to the parent implementation task.

All listings and VIN/stock pairings are synthetic. The suite patches
`backend.app.retrieval.search` with `SearchResult` fixtures and patches
`backend.app.main.fetch_listing` for HTTP 403, partial, and complete responses.
Socket connection and DNS guards prevent accidental external requests; no provider
key, live listing, paid API, or LLM is used. The configured key is the literal `test`.

Run from `/Users/tonyzhou/Desktop/rev_rank`:

```sh
REVRANK_LIVE_FETCH_ENABLED=false .venv/bin/python -m pytest backend/tests/test_search_recovery.py -q
REVRANK_LIVE_FETCH_ENABLED=false .venv/bin/python -m pytest backend/tests tests -q
```

Coverage includes CarMax and Carvana stock URLs; URL-only VIN recovery; bounded
stock/seller, exact-URL and VIN searches; matching VIN across sources; wrong and
multiple unique VIN rejection; repeated identical VIN acceptance; unrelated stock
rejection; unsafe result URLs; conflicting price/mileage with null values and
retained observations; duplicate agreeing results; provider failure; invalid VIN
422 responses; disabled and unconfigured search; pasted text with and without a
reference URL; and partial versus complete direct-import routing. API attempts
must retain method/status/detail and the initial 403 diagnostic.

The tests assert the supplied recovery contract rather than internal helper names.
Recovery returns `ImportResponse`; candidate observations expose `field` and
`value`; numeric conflicts must not silently pick one source. Search adapter HTTP
transport itself is outside this suite: provider responses are replaced at the
retrieval boundary. No claim about live provider coverage or listing accuracy is
made by these offline regressions.

`backend/tests/test_licensed_recovery.py` covers the licensed-inventory and VIN-decode
paths the same way, patching `retrieval.inventory_search` and `retrieval.decode_vin`
and using `httpx.MockTransport` for adapter parsing. It covers seller-scoped URL/stock
binding, VIN conflicts, primary-listing precedence, syndicated-only conflicts,
licensed-then-search fallback, registry agreement/disagreement/fill-in and
check-digit warnings, and keeping the API key out of errors and returned URLs.
Both suites pass against the implemented modules; live provider coverage remains
unmeasured.
