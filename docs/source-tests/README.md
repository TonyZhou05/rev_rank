# US shopping-source live checks

Tested September 13, 2026 UTC, from the developer's local machine using RevRank's
production HTTP fetcher. This is a practical ten-site US shopping shortlist, not
an independently established traffic top ten. Selection informed by
[Semrush's US automotive ranking](https://www.semrush.com/trending-websites/us/automotive)
and the user's CarMax/Carvana examples; broad automotive rankings also include
manufacturers and parts retailers.

## Configuration

The user explicitly requested enabling these ten sites. Local `.env` now has live
fetching enabled and exact apex + `www` hosts for all ten. `.env.example` retains
opt-in defaults and includes the copyable profile. Restart an already-running API
to load changed environment values. Configuration is authorization to attempt a
fetch; it does not establish technical coverage or data-reuse rights. Existing
registry notes remain visible. No robots or access-denial protections were removed.

## Results

| Site | Observed result | Listing extraction |
| --- | --- | --- |
| [CarMax](carmax.com.md) | Robots 200; user's listing 403 | Blocked |
| [Carvana](carvana.com.md) | Robots 200; user's listing 403 | Blocked |
| [CarGurus](cargurus.com.md) | Robots disallows tested inventory path | Not attempted |
| [Cars.com](cars.com.md) | Robots endpoint 403 | Not attempted |
| [Autotrader](autotrader.com.md) | Inventory page 200 | No matching individual listing link found |
| [CARFAX](carfax.com.md) | Inventory page 403 | Blocked |
| [TrueCar](truecar.com.md) | Inventory and linked listing 200 | Partial; identity/price/mileage extracted, units/conflicts need review |
| [Edmunds](edmunds.com.md) | Inventory page 403 | Blocked |
| [Kelley Blue Book](kbb.com.md) | Inventory and linked listing 200 | Poor: identity missing and conflicting prices; do not trust without correction |
| [Autolist](autolist.com.md) | Homepage 200 | No matching individual listing link found |

These are single-path observations, not domain-wide availability claims. Neither
partial import is independently validated for factual accuracy. No complete,
validated listing import was demonstrated. The remaining eight sites were tested
at the access layer; do not count those as listing extraction tests.

The first run failed for all sites due to missing local Python CA roots. The fetcher
now adds certifi's public roots to the default TLS context, retaining certificate
and hostname verification. The recorded results are from the corrected run.

## Repeat

```sh
.venv/bin/python scripts/check_sources.py --live
# Rerun selected sites while preserving the other recorded results:
.venv/bin/python scripts/check_sources.py --live --domain truecar.com
.venv/bin/python -m pytest backend/tests tests -q
```

The script uses configured exact hosts, bounded requests, robots checks, and no
LLM. It follows at most one matching listing link per accessible entry page. Each
site gets a brief Markdown file; `results.json` holds timestamps and request
statuses. Raw source pages are not saved. Ordinary unit tests use isolated
configuration and do not make these live requests.

Next integration work: a TrueCar adapter with field verification and a KBB adapter
that scopes prices to the selected vehicle. Access-denied sites require an
authorized access method or pasted text; configuration alone cannot make them work.
