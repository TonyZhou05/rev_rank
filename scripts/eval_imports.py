"""Live import harness: run a corpus of real pasted URLs through the API, repeatedly, and audit results.

Each case is imported --repeat times (default 2) because search excerpts vary between calls. A run
FAILS on a pipeline error (wrong or missing identity, a field NHTSA decoded but not shown, placeholder
title, implausible numbers, an unexpected candidate). Honest unknowns (no price anywhere, unconfirmed
currency) are NOTES. Values that change between repeats are reported as UNSTABLE.

Uses the local .env and the paid-provider quotas (see AGENTS.md, "Paid API budget"). Without --spend
it only prints the worst-case cost and exits: a full corpus run with --repeat 2 can use about 340 Tavily
credits. Prefer --only and --repeat 1, and --source to pick one provider.

    .venv/bin/python scripts/eval_imports.py [--repeat N] [--only TEXT] [--source auto|marketcheck|search] [--spend] [URL ...]
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main, usage  # noqa: E402

BUILD = ("trim", "transmission", "engine", "drivetrain", "body", "fuel_type")
IDENTITY = ("year", "make", "model")
STABLE = ("vin", "year", "make", "model", "price", "mileage")
PLACEHOLDER = "Recovered vehicle — review details"


def same(expected, actual) -> bool:
    a, b = (re.sub(r"[^a-z0-9]", "", str(v).casefold()) for v in (expected, actual))
    return a == b or (bool(a) and bool(b) and (a.startswith(b) or b.startswith(a)))


def summarize(body: dict) -> dict:
    c = body.get("candidate") or {}
    return {"status": body.get("status"), "recovery": body.get("recovery_status"), "message": body.get("message", "")[:800],
            "vin": (c.get("evidence", {}).get("vin") or {}).get("value"), **{k: c.get(k) for k in
            ("title", "year", "make", "model", "trim", "price", "currency", "mileage", "mileage_unit", "transmission",
             "engine", "drivetrain", "body", "fuel_type", "location")},
            "conflicts": c.get("conflicts", []), "retrieval": c.get("retrieval_method"),
            "registry": {o["field"]: o["value"] for o in c.get("observations", []) if o["method"] == "registry"}}


def audit(run: dict, expect: dict) -> tuple[list[str], list[str]]:
    problems, notes = [], []
    if expect.get("no_candidate"):
        return ([f"expected no car, got '{run['title']}'"] if run["title"] else []), []
    if not run["title"]:
        # No car is honest when the data is not there; it is a pipeline error only without such a reason.
        for signal, reason in (("no longer available", "REMOVED: seller page says sold"),
                               ("redirected to a different page", "REMOVED: listing redirects to search results"),
                               ("no page about this listing", "NO DATA: listing not in the search index")):
            if signal in run["message"]:
                return [], [reason]
        return ([] if expect.get("removed") else [f"no car: {run['recovery']} — {run['message'][-160:]}"]), (
            ["listing already reported sold/removed"] if expect.get("removed") else [])
    if expect.get("vin") and run["vin"] != expect["vin"]:
        problems.append(f"VIN {run['vin']} != expected {expect['vin']}")
    for field in IDENTITY:
        if field in expect and not same(expect[field], run[field]):
            problems.append(f"{field} {run[field]!r} != expected {expect[field]!r}")
    registry = run["registry"]
    for field in IDENTITY:
        if field in registry and not same(registry[field], run[field]):
            problems.append(f"{field} {run[field]!r} withheld or differs from NHTSA {registry[field]!r}")
    problems += [f"NHTSA returned {f} but it is not shown" for f in BUILD if f in registry and run[f] is None]
    if run["title"] == PLACEHOLDER:
        problems.append("placeholder title")
    if run["price"] is not None and not 1000 <= run["price"] <= 500000:
        problems.append(f"implausible price {run['price']}")
    if run["mileage"] is not None and not 0 <= run["mileage"] <= 500000:
        problems.append(f"implausible mileage {run['mileage']}")
    if run["mileage"] is not None and run["mileage"] < 100 and (run["year"] or 0) < datetime.now().year - 1:
        problems.append(f"implausible mileage {run['mileage']} for a {run['year']}")
    for field in ("price", "mileage"):
        if run[field] is None:
            notes.append(f"{field} {'withheld: sources disagree' if field in run['conflicts'] else 'not found'}")
    if run["location"] is None:
        notes.append(f"location {'withheld: sources disagree' if 'location' in run['conflicts'] else 'not found'}")
    if run["price"] is not None and run["currency"] == "UNK":
        notes.append("currency unconfirmed")
    return problems, notes


def main_() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", default="")
    parser.add_argument("--corpus", default=str(ROOT / "scripts/url_corpus.json"))
    parser.add_argument("--source", choices=("auto", "marketcheck", "search"), default="auto")
    parser.add_argument("--spend", action="store_true", help="actually call the paid providers")
    args = parser.parse_args()
    cases = ([{"label": u, "input": u, "expect": {}} for u in args.urls] if args.urls
             else json.loads(Path(args.corpus).read_text())["cases"])
    cases = [c for c in cases if args.only.lower() in c["label"].lower()]
    settings = main.settings
    imports = len(cases) * max(1, args.repeat)
    # Worst case per import: 3 MarketCheck calls; 4 searches (8 Tavily credits). Blocked pages only.
    worst = {"marketcheck": 3 * imports if settings.marketcheck_enabled and args.source != "search" else 0,
             settings.search_provider: 4 * usage.COST.get(settings.search_provider, 1) * imports
             if settings.search_enabled and args.source != "marketcheck" else 0}
    left = {p: usage.limit(settings, p) - usage.used(settings, p) for p in worst if worst[p]}
    print(f"{imports} imports; worst case " + ", ".join(f"{p} {n} {usage.UNIT.get(p, 'units')} ({left.get(p, 0)} left this month)"
                                                          for p, n in worst.items() if n))
    if not args.spend:
        print("Dry run: nothing was called. Add --spend to run (narrow it with --only and --source first).")
        return 0
    client = TestClient(main.app)
    body_extra = {} if args.source == "auto" else {"recovery_source": args.source}
    report, failed = [], 0
    for case in cases:
        runs = [summarize(client.post("/api/import", json={"url": case["input"], **body_extra}).json()) for _ in range(max(1, args.repeat))]
        audits = [audit(run, case["expect"]) for run in runs]
        unstable = sorted({f for f in STABLE for run in runs if run[f] != runs[0][f]})
        problems = sorted({p for a in audits for p in a[0]})
        notes = sorted({n for a in audits for n in a[1]})
        failed += bool(problems)
        first = runs[0]
        verdict = ("FAIL" if problems else "UNSTABLE" if unstable
                   else "NO DATA" if any(n.startswith(("NO DATA", "REMOVED")) for n in notes) else "ok")
        print(f"\n[{verdict:8}] {case['label']}\n           {first['title'] or '(no car)'} | VIN {first['vin'] or '—'} | "
              f"price {first['price']} {first['currency'] or ''} | mileage {first['mileage']} | location {first['location']} | "
              f"via {first['retrieval'] or first['recovery']}")
        for line in problems:
            print("           ✗", line)
        if unstable:
            print("           ~ changes between runs:", ", ".join(f"{f}: " + " / ".join(str(r[f]) for r in runs) for f in unstable))
        if notes:
            print("           ·", "; ".join(notes))
        report.append({"case": case, "runs": runs, "problems": problems, "unstable": unstable, "notes": notes})
    out = ROOT / ".local" / "eval" / f"imports-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    unstable_count = sum(bool(r["unstable"]) and not r["problems"] for r in report)
    no_data = sum(any(n.startswith(("NO DATA", "REMOVED")) for n in r["notes"]) and not r["problems"] for r in report)
    print(f"\n{len(report) - failed}/{len(report)} cases without pipeline errors ({no_data} with no data available); "
          f"{unstable_count} unstable. Details: {out}")
    print("Usage this month:", usage.summary(settings))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main_())
