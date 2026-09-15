"""Offline regressions for the constraint-fit shortlist and the citation-gated re-rank."""
import json
import re
import socket

import pytest

from backend.app import analyst
from backend.app.comparison import (CONDITION_CAVEAT, DEPRECIATION_CAVEAT, constraint_checks, create_report,
                                    normalize)
from backend.app.config import Settings
from backend.app.models import Candidate, Evidence, Preferences

SETTINGS = Settings(llm_api_key="test", llm_model="deepseek-flash")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("offline test")
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def car(title, make, model, year, price, mileage, **extra):
    c = Candidate(id=title.replace(" ", "-").lower(), title=title, make=make, model=model, year=year, price=price,
                  currency="USD", mileage=mileage, mileage_unit="mi", source_kind="user", **extra)
    for field in ("make", "model", "year", "price", "currency", "mileage", "mileage_unit", "transmission"):
        if getattr(c, field) is not None:
            c.evidence[field] = Evidence(value=str(getattr(c, field)), source="User-pasted listing text", status="extracted")
    return c


def statuses(c, prefs):
    # normalize() is what stamps price_type; compare never sees a candidate without it.
    return {check.field: check.status for check in constraint_checks(normalize(c), prefs)}


def test_each_constraint_reads_against_reviewed_evidence():
    cheap = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000, transmission="6-speed manual",
                features=["Apple CarPlay"])
    prefs = Preferences(budget=26000, max_mileage=40000, transmission="manual", must_haves=["apple carplay"])
    assert statuses(cheap, prefs) == {"budget": "meets", "max_mileage": "meets", "transmission": "meets",
                                      "must_haves": "meets"}
    dear = car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000, transmission="automatic")
    assert statuses(dear, prefs) == {"budget": "conflicts", "max_mileage": "conflicts",
                                     "transmission": "conflicts", "must_haves": "not_established"}


def test_an_unknown_field_is_unknown_not_a_failure():
    unpriced = Candidate(id="x", title="2020 Honda Civic", make="Honda", model="Civic", year=2020,
                         source_kind="user")
    checks = statuses(unpriced, Preferences(budget=20000, max_mileage=50000, transmission="manual"))
    assert checks == {"budget": "unknown", "max_mileage": "unknown", "transmission": "unknown"}


def test_silence_about_an_exclusion_is_never_a_pass():
    quiet = car("2019 Subaru Outback", "Subaru", "Outback", 2019, 22000, 60000)
    check = constraint_checks(quiet, Preferences(excludes=["salvage title"]))[0]
    assert check.status == "not_established"
    assert "not proof" in check.detail
    branded = car("2019 Subaru Outback", "Subaru", "Outback", 2019, 15000, 60000,
                  history="Salvage title, rebuilt after collision")
    assert constraint_checks(branded, Preferences(excludes=["salvage title"]))[0].status == "conflicts"
    # A listing that explicitly denies it is a seller claim, and is labelled as one.
    denied = car("2019 Subaru Outback", "Subaru", "Outback", 2019, 22000, 60000, history="No accident history reported")
    denial = constraint_checks(denied, Preferences(excludes=["accident history"]))[0]
    assert denial.status == "meets" and "seller claim" in denial.detail


def test_a_price_with_no_recorded_price_type_is_not_a_budget_pass():
    # asking() is the guard: an unlabelled figure is never measured against the buyer's budget.
    raw = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000)
    assert constraint_checks(raw, Preferences(budget=26000))[0].status == "unknown"
    assert constraint_checks(normalize(raw), Preferences(budget=26000))[0].status == "meets"


def test_shortlist_orders_by_constraint_fit_and_explains_itself():
    fits = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000, transmission="manual", features=["Apple CarPlay"])
    misses = car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000, transmission="automatic")
    prefs = Preferences(budget=26000, max_mileage=40000, transmission="manual", must_haves=["apple carplay"])
    report = create_report([misses, fits], prefs, Settings())
    assert [entry.candidate_id for entry in report.shortlist] == [fits.id, misses.id]
    first, second = report.shortlist
    assert (first.position, first.meets, first.conflicts) == (1, 4, 0)
    assert (second.position, second.meets, second.conflicts) == (2, 0, 3)
    assert "not a value, condition or reliability judgement" in first.rationale
    # No composite score is published anywhere in the entry.
    assert not re.search(r"score|/100|points", json.dumps(first.model_dump()), re.I)


def test_shortlist_without_constraints_keeps_the_import_order():
    a = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000)
    b = car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000)
    report = create_report([b, a], Preferences(), Settings())
    assert [entry.candidate_id for entry in report.shortlist] == [b.id, a.id]
    assert all(not entry.checks for entry in report.shortlist)
    assert "have not stated any constraints" in report.shortlist[0].rationale
    assert not any(m.label == "Constraint fit" for m in report.metrics)


def test_constraint_metrics_reach_the_report():
    fits = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000, transmission="manual")
    misses = car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000, transmission="automatic")
    prefs = Preferences(budget=26000, max_mileage=40000, transmission="manual", excludes=["salvage title"])
    report = create_report([fits, misses], prefs, Settings())
    labels = {m.label: m.values for m in report.metrics}
    assert labels["Mileage ceiling: 40,000"] == ["within", "over"]
    assert labels["Transmission wanted: manual"] == ["matches", "does not match"]
    assert labels["Exclude: salvage title"] == ["not established", "not established"]
    # The exclusion is unestablished for both cars, so neither car can bank it as met.
    assert labels["Constraint fit"] == ["3 met · 1 open · 0 conflicting", "0 met · 1 open · 3 conflicting"]


def test_the_two_empty_sections_name_their_evidence_and_state_no_figure():
    a = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000)
    b = car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000)
    warnings = create_report([a, b], Preferences(), Settings()).warnings
    assert DEPRECIATION_CAVEAT in warnings and CONDITION_CAVEAT in warnings
    for caveat in (DEPRECIATION_CAVEAT, CONDITION_CAVEAT):
        assert "needs" in caveat
        # No currency amount, percentage or star rating may appear in a placeholder caveat.
        assert not re.search(r"[$€£]|\d+\s*%|\d+(\.\d+)?\s*(stars?|/5|out of)", caveat)


# ReportView.tsx picks each empty section's caveats out of report.warnings by topic. Keep the two
# caveats routing to one section each, and keep the shortlist caveat out of both.
DEPRECIATION_FILTER = re.compile(r"depreciat|resale|ownership|years kept|mileage when", re.I)
CONDITION_FILTER = re.compile(r"condition|feature|history|accident|title|option", re.I)


def test_each_caveat_reaches_exactly_the_section_it_is_about():
    assert DEPRECIATION_FILTER.search(DEPRECIATION_CAVEAT) and not CONDITION_FILTER.search(DEPRECIATION_CAVEAT)
    assert CONDITION_FILTER.search(CONDITION_CAVEAT) and not DEPRECIATION_FILTER.search(CONDITION_CAVEAT)
    fits = car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000, transmission="manual")
    misses = car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000, transmission="automatic")
    report = create_report([fits, misses], Preferences(budget=26000), Settings())
    shortlist_caveat = next(w for w in report.warnings if w.startswith("The shortlist order counts"))
    assert not DEPRECIATION_FILTER.search(shortlist_caveat) and not CONDITION_FILTER.search(shortlist_caveat)


# ---- cited re-rank ---------------------------------------------------------------------------
@pytest.fixture
def report():
    cars = [car("2021 Mazda 3", "Mazda", "3", 2021, 24000, 30000, transmission="manual"),
            car("2022 BMW M240i", "BMW", "M240i", 2022, 48000, 52000, transmission="automatic")]
    return create_report(cars, Preferences(budget=26000, transmission="manual"), Settings())


def call(name, **args):
    return {"id": f"c-{name}-{len(json.dumps(args))}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def scripted(turns):
    seen = []

    def chat(settings, messages, tools, timeout):
        seen.append([json.loads(m["content"]) for m in messages if m["role"] == "tool"])
        turn = turns[len(seen) - 1] if len(seen) <= len(turns) else []
        return {"role": "assistant", "content": "", "tool_calls": turn}
    return chat, seen


EVIDENCE = [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"), call("get_comparison_metrics")]
VERDICT = call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB"],
               text="Car A is 24,000 USD cheaper than Car B.")


def test_constraint_fit_is_a_citable_metric(report, monkeypatch):
    chat, seen = scripted([EVIDENCE, [call("finish")]])
    monkeypatch.setattr(analyst, "chat", chat)
    ws = analyst.Workspace(report)
    ws.run("get_comparison_metrics", {})
    assert "M.A.fit" in ws.sources and "M.B.fit" in ws.sources
    assert "meets 2 of the buyer's 2 stated constraints" in ws.sources["M.A.fit"].detail
    assert ws.buyer["transmission"] == "manual" and ws.buyer["budget"] == 26000


def test_a_fully_cited_ranking_is_kept(report, monkeypatch):
    chat, seen = scripted([
        EVIDENCE,
        [VERDICT, call("set_ranking", order=["A", "B"], reasons=[
            {"car": "A", "text": "Car A meets 2 of the buyer's 2 stated constraints.", "citations": ["M.A.fit"]},
            {"car": "B", "text": "Car B is 48,000 USD and its transmission is automatic.", "citations": ["B.price", "B.transmission"]}]),
         call("finish")],
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert [entry.position for entry in analysis.ranking] == [1, 2]
    assert [entry.candidate_id for entry in analysis.ranking] == [c.id for c in report.candidates]
    assert analysis.ranking[0].claim.citations == ["M.A.fit"]
    assert analysis.ranking[0].claim.text.startswith("2021 Mazda 3 meets 2")
    assert "each position cites its evidence" in analysis.message
    # Ranking citations are listed as sources, so every position is traceable in the report.
    assert {"M.A.fit", "B.price", "B.transmission"} <= {s.id for s in analysis.sources}


@pytest.mark.parametrize("bad, expected", [
    ({"order": ["A"], "reasons": []}, "each car exactly once"),
    ({"order": ["A", "B"], "reasons": [{"car": "A", "text": "Best.", "citations": ["M.A.fit"]}]}, "has no reason"),
    ({"order": ["A", "B"], "reasons": [
        {"car": "A", "text": "Car A is the best value.", "citations": ["nope.1"]},
        {"car": "B", "text": "Second.", "citations": ["B.price"]}]}, "rejected"),
    ({"order": ["A", "B"], "reasons": [
        {"car": "A", "text": "Car A saves 9,999 USD.", "citations": ["M.A.fit"]},
        {"car": "B", "text": "Second.", "citations": ["B.price"]}]}, "rejected"),
    ({"order": ["A", "B"], "reasons": [
        {"car": "A", "text": "A better buy overall.", "citations": ["B.price"]},
        {"car": "B", "text": "Second.", "citations": ["B.price"]}]}, "own evidence"),
])
def test_an_unsupported_ranking_is_discarded_whole(report, monkeypatch, bad, expected):
    chat, seen = scripted([EVIDENCE, [VERDICT, call("set_ranking", **bad)], [call("finish")]])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.ranking == []
    # The rejection reason goes back to the model, so it can fix the ranking and retry.
    assert expected in seen[2][-1]["reason"]
    # The deterministic constraint-fit order is still there for the report to show.
    assert [entry.position for entry in report.shortlist] == [1, 2]
    assert "keeps its computed constraint-fit order" in analysis.message


def test_an_unavailable_model_leaves_the_deterministic_order_alone(report, monkeypatch):
    def unavailable(*args, **kwargs):
        raise analyst.LLMUnavailable("Model response unavailable or invalid.")
    monkeypatch.setattr(analyst, "chat", unavailable)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "unavailable" and analysis.ranking == []
    assert [entry.candidate_id for entry in report.shortlist] == [c.id for c in report.candidates]
