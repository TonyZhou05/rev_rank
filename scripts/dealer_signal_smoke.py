"""One frugal live check of the dealer-signal search. Deliberately hard to run in a loop.

The dealer-signal pass has only ever run against stubs (`backend/tests/test_dealer_signals.py`). This
script exists so its first real call is a single, priced, recorded one rather than an exploratory
session: it runs the search for exactly one dealer, prints what each result was classified as, and
stops. It never calls the model, never fetches a page, and takes no corpus.

Cost, at the repo's Tavily pricing of 2 credits per advanced search: `--searches 1` is 2 credits and
is the recommended smoke. It is a dry run until you pass --spend, like scripts/eval_imports.py, and
it refuses to run more than 3 searches. The usual meter applies: usage.py counts the calls and
refuses them once REVRANK_SEARCH_MONTHLY_CREDITS is reached.

    .venv/bin/python scripts/dealer_signal_smoke.py "Dealer Name" --city Austin --state TX [--searches 1] [--spend]

Record the outcome in docs/dealer-report-section.md under "One frugal live smoke" and do not repeat
the run to see whether the results change.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import dealer_signals, usage  # noqa: E402
from backend.app.config import Settings  # noqa: E402
from backend.app.models import DealerInfo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="dealer name, exactly as the listing record reported it")
    parser.add_argument("--city", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--searches", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--spend", action="store_true", help="actually call the search provider")
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.search_enabled:
        print("No search provider configured (REVRANK_SEARCH_PROVIDER and REVRANK_SEARCH_API_KEY). Nothing to do.")
        return 1
    # The feature flag gates reports, not this script: the point here is to price and check the search.
    settings = replace(settings, dealer_signals_enabled=True, dealer_signal_searches=args.searches)
    dealer = DealerInfo(name=args.name, city=args.city or None, state=args.state or None)
    provider = settings.search_provider
    cost = dealer_signals.credits_for(args.searches, settings)
    left = usage.limit(settings, provider) - usage.used(settings, provider)
    place = " ".join(part for part in (args.city, args.state) if part) or "no city or state given"
    print(f"{args.searches} search(es) for {args.name!r} ({place}) -> "
          f"{cost} {usage.UNIT.get(provider, 'units')} on {provider} ({left} left this month)")
    for i, query in enumerate(dealer_signals.queries(dealer, args.searches), start=1):
        print(f"  query {i}: {query}")
    if not args.spend:
        print("Dry run: nothing was called. Add --spend to make the one live call.")
        return 0

    signals, spent, problem = dealer_signals.collect(dealer, settings)
    print(f"\nspent {spent} search(es); kept {len(signals)} excerpt(s)" + (f"; {problem}" if problem else ""))
    for signal in signals:
        print(f"\n[{signal.id}] {signal.category} · {signal.nature} · {signal.host} · {signal.published or 'undated'}")
        print(f"      {signal.label}")
        print(f"      {signal.url}")
        print(f"      “{signal.excerpt}”")
    if not signals:
        print("\n" + dealer_signals.NOTHING_FOUND)
    print("\nNo model call was made and no page was fetched. Record this outcome in "
          "docs/dealer-report-section.md rather than re-running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
