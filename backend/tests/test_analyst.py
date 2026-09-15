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

    def chat(settings, messages, tools, timeout, token=None):
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


def test_finish_is_refused_until_a_verdict_is_recorded(report, monkeypatch):
    chat, seen = scripted([[call("get_vehicle_facts", car="A"), call("finish")], []])
    monkeypatch.setattr(analyst, "chat", chat)
    analyst.analyze(report, SETTINGS)
    refusal = seen[1][-1]
    assert refusal["ok"] is False and "add_finding with kind 'verdict'" in refusal["reason"]


def test_finish_before_any_fetch_names_the_tools_to_call(report, monkeypatch):
    chat, seen = scripted([[call("finish")], []])
    monkeypatch.setattr(analyst, "chat", chat)
    analyst.analyze(report, SETTINGS)
    assert "get_vehicle_facts" in seen[1][-1]["reason"]


def test_finish_appended_to_every_batch_does_not_end_the_run_early(report, monkeypatch):
    # A model that ends each batch with finish reaches the second one still fetching evidence.
    # Refusing finish must not spend the same flag as the no-tool-call nudge, or the run stops
    # before a single statement has been offered and the report shows an empty analysis.
    chat, _ = scripted([
        [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"), call("finish")],
        [call("get_comparison_metrics"), call("finish")],
        [call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB"],
              text="Car B is 3,496 USD cheaper than Car A."), call("finish")],
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "complete"
    assert analysis.verdict.text.startswith("2022 BMW M4 is 3,496 USD cheaper")


def test_a_model_that_only_calls_finish_still_stops(report, monkeypatch):
    turns = analyst.MAX_FINISH_REFUSALS + 1
    chat, seen = scripted([[call("finish")]] * (turns + 4))
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    # Refused while nothing is recorded, then honoured, rather than spending every remaining turn.
    assert len(seen) == turns and analysis.status == "unavailable"


def test_nine_evidence_tools_then_finish_is_nudged_to_record_a_verdict(report, monkeypatch):
    """Live residual after #24: ~9 evidence tools, then finish, empty analysis.

    Finish tacked onto gathering batches used to spend MAX_FINISH_REFUSALS, so the next
    finish-only turns ended the run before add_finding. The model must be told to record
    the verdict instead, and that later add_finding must still be reached.
    """
    monkeypatch.setattr(analyst, "nhtsa", lambda *args, **kwargs: {"results": [], "Results": []})
    inner, seen = scripted([
        [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"),
         call("get_recalls", car="A"), call("get_recalls", car="B"),
         call("get_complaints", car="A"), call("get_complaints", car="B"),
         call("get_safety_rating", car="A"), call("get_safety_rating", car="B"),
         call("get_comparison_metrics"), call("finish")],
        [call("finish")],
        [call("finish")],
        [call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB"],
              text="Car B is 3,496 USD cheaper than Car A."), call("finish")],
    ])
    users = []

    def chat(settings, messages, tools, timeout, token=None):
        users.append([m["content"] for m in messages if m["role"] == "user"])
        return inner(settings, messages, tools, timeout, token)
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "complete"
    assert analysis.verdict.text.startswith("2022 BMW M4 is 3,496 USD cheaper")
    # 9 evidence fetches, then the add_finding the live run never made.
    assert analysis.tool_calls == 10 and analysis.dropped_claims == 0
    # Gathering+finish is refused, and a user turn names add_finding rather than honouring finish.
    assert seen[1][-1]["ok"] is False and "add_finding with kind 'verdict'" in seen[1][-1]["reason"]
    assert seen[2][-1]["ok"] is False and seen[3][-1]["ok"] is False
    assert any(analyst.RECORD_FINDINGS in text for turn in users for text in turn)


def test_finish_only_after_evidence_still_stops(report, monkeypatch):
    # The recording nudge cannot loop until MAX_TURNS: finish-only turns after a fetch still
    # hit a ceiling and the empty analysis stays honest.
    chat, seen = scripted([
        [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"),
         call("get_comparison_metrics"), call("finish")],
        *[[call("finish")]] * (analyst.MAX_RECORDING_REFUSALS + 4),
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert len(seen) == 1 + analyst.MAX_RECORDING_REFUSALS + 1
    assert len(seen) < analyst.MAX_TURNS
    assert analysis.status == "unavailable" and analysis.dropped_claims == 0
    assert analysis.message == "The model recorded no statement, so there was nothing to check."


def test_an_analysis_with_nothing_recorded_says_so_instead_of_blaming_the_checks(report, monkeypatch):
    chat, _ = scripted([[call("get_vehicle_facts", car="A")], []])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "unavailable" and analysis.dropped_claims == 0
    assert analysis.message == "The model recorded no statement, so there was nothing to check."


def test_malformed_findings_are_counted_as_dropped_claims(report, monkeypatch):
    # kind/car refusals used to be silent, so an all-rejected run read as one that never tried.
    chat, _ = scripted([
        [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"), call("get_comparison_metrics")],
        [call("add_finding", kind="pro", car="A", citations=["A.price"], text="Car A asks 67,494 USD."),
         call("add_finding", kind="green_flag", car="2021 Chevrolet Corvette", citations=["A.price"],
              text="Car A asks 67,494 USD."),
         call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB"]),
         call("finish"), call("finish"), call("finish")],
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analysis.status == "unavailable" and analysis.dropped_claims == 3
    assert analysis.message.startswith("No statement passed the evidence checks. 3 unsupported statement(s)")


def test_a_full_flag_slot_is_not_counted_as_a_rejected_claim(report):
    ws = analyst.Workspace(report)
    ws.run("get_vehicle_facts", {"car": "A"})
    kept = ws.add_finding({"kind": "green_flag", "car": "A", "text": "Car A asks 67,494 USD.", "citations": ["A.price"]})
    over = [ws.add_finding({"kind": "green_flag", "car": "A", "text": f"Car A asks 67,494 USD ({word}).",
                            "citations": ["A.price"]})
            for word in ("first", "second", "third", "fourth", "fifth", "sixth")]
    assert kept == {"ok": True} and over[-1]["ok"] is False and "Limit reached" in over[-1]["reason"]
    assert ws.rejected == 0


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


def test_green_and_red_flags_store_as_strengths_and_risks(report, monkeypatch):
    # The prompt speaks in flags; the wire contract keeps strengths and risks.
    chat, _ = scripted([
        [call("get_vehicle_facts", car="A"), call("get_vehicle_facts", car="B"), call("get_comparison_metrics")],
        [call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB"],
              text="Car B is 3,496 USD cheaper than Car A."),
         call("add_finding", kind="green_flag", car="A", citations=["M.A.mileage_per_year"],
              text="Car A covers 16,151 mi over 5 years, about 3,230 mi per year."),
         call("add_finding", kind="red_flag", car="A", citations=["M.A.budget"],
              text="Car A leaves only 2,506 USD of the 70,000 budget for taxes and fees."),
         # The older spelling still works, so a model that reaches for it is not punished.
         call("add_finding", kind="strength", car="B", citations=["M.B.budget"],
              text="Car B leaves 6,002 USD of the 70,000 budget."),
         call("finish")],
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    corvette, bmw = analysis.vehicles
    assert [c.text for c in corvette.strengths] == ["2021 Chevrolet Corvette covers 16,151 mi over 5 years, about 3,230 mi per year."]
    assert [c.text for c in corvette.risks] == ["2021 Chevrolet Corvette leaves only 2,506 USD of the 70,000 budget for taxes and fees."]
    assert len(bmw.strengths) == 1 and analysis.dropped_claims == 0


def test_five_flags_fit_and_the_sixth_is_named_in_the_refusal(report, monkeypatch):
    # Distinct wording, same cited figures: a flag may only use numbers from the result it cites.
    flags = [call("add_finding", kind="green_flag", car="A", citations=["M.A.budget"],
                  text=f"Car A leaves 2,506 USD of the 70,000 budget ({word}).")
             for word in ("first", "second", "third", "fourth", "fifth", "sixth")]
    chat, seen = scripted([
        [call("get_vehicle_facts", car="A"), call("get_comparison_metrics")],
        [call("add_finding", kind="verdict", car="all", citations=["M.A.budget"],
              text="Car A fits the 70,000 budget."), *flags],
        [call("finish")],
    ])
    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(report, SETTINGS)
    assert analyst.LIMITS["strength"] == 5 and analyst.LIMITS["risk"] == 5
    assert len(analysis.vehicles[0].strengths) == 5
    refusal = seen[2][-1]
    assert refusal["ok"] is False and "green_flag" in refusal["reason"]


def test_unknown_kinds_name_the_flag_vocabulary(report):
    ws = analyst.Workspace(report)
    assert "green_flag" in ws.add_finding({"kind": "pro", "car": "A", "text": "x", "citations": []})["reason"]


def test_price_against_msrp_and_days_on_market_are_citable(monkeypatch):
    def offline(*args, **kwargs):
        raise AssertionError("offline test")
    monkeypatch.setattr(socket, "getaddrinfo", offline)
    priced = car("2021 Chevrolet Corvette", "Chevrolet", "Corvette", 2021, 67494, 16151, msrp=74000,
                 dom=45, dom_active=12, first_seen_at="2026-08-01")
    priced.verified_fields = ["msrp"]
    plain = car("2022 BMW M4", "BMW", "M4", 2022, 63998, 29995)
    ws = analyst.Workspace(create_report([priced, plain], Preferences(), SETTINGS))
    ws.run("get_comparison_metrics", {})
    assert "91.2% of its original MSRP" in ws.sources["M.A.msrp_pct"].detail
    assert "45 days on market, 12 of them active" in ws.sources["M.A.dom"].detail
    assert "not by itself evidence" in ws.sources["M.A.dom"].detail
    # Neither metric is invented for a car that has no sourced MSRP or inventory dates.
    assert "M.B.msrp_pct" not in ws.sources and "M.B.dom" not in ws.sources
