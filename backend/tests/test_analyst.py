"""Offline regressions for the tool-calling analyst's credibility gate. The model is scripted."""
import json
import socket

import pytest

from backend.app import analyst
from backend.app.comparison import create_report
from backend.app.config import Settings
from backend.app.models import Candidate, Evidence, Preferences

SETTINGS = Settings(llm_api_key="test", llm_model="scripted")


def car(title, make, model, year, price, mileage, **extra):
    c = Candidate(id=title.replace(" ", "-").lower(), title=title, make=make, model=model, year=year, price=price,
                  currency="USD", mileage=mileage, mileage_unit="mi", source_kind="user", **extra)
    for field in ("make", "model", "year", "price", "currency", "mileage", "mileage_unit"):
        c.evidence[field] = Evidence(value=str(getattr(c, field)), source="User-pasted listing text", status="extracted")
    return c


@pytest.fixture
def report(monkeypatch):
    def offline(*args, **kwargs):
        raise AssertionError("offline test")
    monkeypatch.setattr(socket, "getaddrinfo", offline)
    cars = [car("2021 Chevrolet Corvette", "Chevrolet", "Corvette", 2021, 67494, 16151),
            car("2022 BMW M4", "BMW", "M4", 2022, 63998, 29995)]
    return create_report(cars, Preferences(budget=70000), SETTINGS)


def call(name, **args):
    return {"id": f"c-{name}-{len(json.dumps(args))}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def scripted(turns):
    """Replays one assistant message per turn and records the tool results the model received."""
    seen = []

    def chat(settings, messages, tools, timeout):
        seen.append([json.loads(m["content"]) for m in messages if m["role"] == "tool"])
        turn = turns[len(seen) - 1] if len(seen) <= len(turns) else []
        return {"role": "assistant", "content": "", "tool_calls": turn}
    return chat, seen


def test_only_cited_numbers_survive(report, monkeypatch):
    chat, seen = scripted([
        [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"), call("get_comparison_metrics")],
        [call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB", "P.buyer"],
              text="Car B is 3,496 USD cheaper than Car A and both fit the 70,000 budget."),
         call("add_finding", kind="strength", car="A", citations=["A.mileage"], text="Car A has only 16,151 mi."),
         call("add_finding", kind="strength", car="B", citations=["B.price"], text="Car B costs 59,000 USD."),
         call("add_finding", kind="risk", car="B", citations=["B.recall.99V999000"], text="Car B has an open recall."),
         call("add_finding", kind="strength", car="B", citations=["A.price"], text="Car B is priced at 67,494 USD."),
         call("add_finding", kind="comparison", car="all", topic="mileage", favors="A",
              citations="['M.mileage_gap.AB']", text="Car A has 13,844 mi fewer than Car B."),
         call("add_finding", kind="question", car="B", text="Why is the price 1,000 lower online?"),
         call("add_finding", kind="question", car="B", text="Can you share the service records?"),
         call("finish")],
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    add_results, original = [], analyst.Workspace.add_finding
    monkeypatch.setattr(analyst.Workspace, "add_finding", lambda self, args: add_results.append(original(self, args)) or add_results[-1])
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "complete"
    assert analysis.verdict.text.startswith("2022 BMW M4 is 3,496 USD cheaper than 2021 Chevrolet Corvette")
    corvette, bmw = analysis.vehicles
    assert [c.text for c in corvette.strengths] == ["2021 Chevrolet Corvette has only 16,151 mi."]
    # Invented price, unfetched recall id, and Car B's claim citing Car A's price are all rejected.
    assert bmw.strengths == [] and bmw.risks == []
    assert analysis.comparisons[0].favors == corvette.candidate_id and analysis.comparisons[0].topic == "mileage"
    assert [q.text for q in analysis.questions] == ["Can you share the service records?"]
    assert analysis.dropped_claims == 4
    assert {s.id for s in analysis.sources} == {"M.price_gap.AB", "P.buyer", "A.mileage", "M.mileage_gap.AB"}
    assert [r["ok"] for r in add_results] == [True, True, False, False, False, True, False, True]
    assert "59000" in add_results[2]["reason"] or "59,000" in add_results[2]["reason"]


def test_findings_need_fetched_evidence_first(report, monkeypatch):
    chat, seen = scripted([[call("add_finding", kind="verdict", car="all", citations=["A.price"], text="Car A is best.")],
                           []])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "unavailable"
    assert seen[1][0]["ok"] is False


def test_finish_requires_a_verdict_once(report, monkeypatch):
    chat, seen = scripted([[call("get_vehicle_facts", car="A"), call("finish")], []])
    monkeypatch.setattr(analyst, "chat", chat)
    analyst.analyze(report, SETTINGS)
    assert seen[1][-1] == {"ok": False, "reason": "Record an overall verdict with add_finding first."}


def test_recall_tool_scopes_and_cites_model_year(report, monkeypatch):
    monkeypatch.setattr(analyst, "nhtsa", lambda url, params, limit=0: {"results": [
        {"NHTSACampaignNumber": "21V421000", "Component": "AIR BAGS", "Summary": "Warning lamp may fail.",
         "Remedy": "Software update.", "ReportReceivedDate": "10/06/2021", "overTheAirUpdate": "True"}]})
    ws = analyst.Workspace(report)
    result = ws.run("get_recalls", {"car": "A"})
    assert result["count"] == 1 and result["recalls"][0]["id"] == "A.recall.21V421000"
    assert "checked by VIN" in ws.sources["A.recalls"].detail
    assert ws.run("get_recalls", {"car": "Z"})["error"].startswith("Unknown tool or car")


def test_unconfigured_model_is_unavailable(report):
    assert analyst.analyze(report, Settings()).status == "unavailable"
