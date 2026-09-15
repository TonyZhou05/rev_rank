"""Offline regressions for the constraint chat. The model is scripted; no provider is called."""
import socket

import pytest
from fastapi.testclient import TestClient

from backend.app import constraints as module
from backend.app.config import Settings
from backend.app.constraints import parse_constraints, rule_constraints
from backend.app.main import app
from backend.app.models import Preferences

LLM = Settings(llm_api_key="test", llm_model="deepseek-flash")
SENTENCE = ("About 30k budget, keeping it 5 years, I drive 15,000 miles a year, needs AWD and Apple CarPlay, "
            "no salvage titles, has to be a manual. I'm in Austin, TX and reliability matters most.")
client = TestClient(app)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("constraint parsing must not open a socket")
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def scripted(payload):
    def request_json(settings, system, body):
        assert "preference" in system.lower() and body["message"]
        return payload
    return request_json


def values(result, field):
    return [c.value for c in result.constraints if c.field == field]


def test_rules_read_every_field_from_one_sentence():
    result = parse_constraints(SENTENCE, Preferences(), Settings())
    prefs = result.preferences
    assert result.mode == "rules"
    assert (prefs.budget, prefs.ownership_years, prefs.annual_mileage) == (30000, 5, 15000)
    assert prefs.transmission == "manual" and prefs.location == "Austin, TX"
    assert set(prefs.must_haves) == {"all-wheel drive", "apple carplay"}
    assert prefs.excludes == ["salvage title"] and "Reliability" in prefs.priorities
    # Every chip carries the buyer's own words, so nothing is unexplained in the panel.
    assert all(c.quote and c.quote.casefold() in SENTENCE.casefold() for c in result.constraints)
    assert all(c.source == "rules" for c in result.constraints)


def test_rules_separate_a_mileage_ceiling_from_a_budget():
    result = parse_constraints("Under $32,000 and nothing over 60k miles", Preferences(), Settings())
    assert result.preferences.budget == 32000 and result.preferences.max_mileage == 60000


def test_rules_flip_a_negated_transmission_and_read_exclusions():
    prefs = parse_constraints("I do not want a manual, and no flood damage", Preferences(), Settings()).preferences
    assert prefs.transmission == "automatic" and prefs.excludes == ["flood damage"]


def test_rules_never_invent_from_an_empty_message():
    result = parse_constraints("hello there", Preferences(), Settings())
    assert result.constraints == [] and result.unmapped == ["hello there"]
    assert result.preferences == Preferences()
    assert "did not recognise" in result.reply


def test_unconfigured_model_stays_in_rules_mode_and_says_so():
    result = parse_constraints(SENTENCE, Preferences(), Settings())
    assert result.mode == "rules"
    assert any("not configured" in note for note in result.notes)


def test_model_mapping_is_merged_when_every_item_quotes_the_buyer(monkeypatch):
    monkeypatch.setattr(module, "request_json", scripted({"constraints": [
        {"field": "budget", "value": 28000, "quote": "stretch to 28k"},
        {"field": "must_haves", "value": "tow package", "quote": "pull a small trailer"},
        {"field": "excludes", "value": "smoker's car", "quote": "nothing that smells of smoke"},
    ], "unmapped": ["something silver"]}))
    message = "I could stretch to 28k, must pull a small trailer, nothing that smells of smoke, something silver"
    result = parse_constraints(message, Preferences(), LLM)
    assert result.mode == "llm" and result.preferences.budget == 28000
    assert "tow package" in result.preferences.must_haves
    assert result.preferences.excludes == ["smoker's car"]
    assert result.unmapped == ["something silver"]
    assert any("deepseek-flash" in note for note in result.notes)
    # The reply is composed from accepted constraints, so it cannot narrate a rejected one.
    assert "28,000" in result.reply and "silver" in result.reply


def test_the_reply_stops_at_what_was_recorded():
    # The page owns the next step, because only it knows whether the button says Generate or Apply.
    reply = parse_constraints("Under $32,000, keeping it 4 years", Preferences(), Settings()).reply
    assert reply == "Recorded hold period 4 years; budget 32,000."


def test_model_value_absent_from_its_own_quote_discards_the_whole_mapping(monkeypatch):
    monkeypatch.setattr(module, "request_json", scripted({"constraints": [
        {"field": "budget", "value": 48000, "quote": "about 30k"},
    ], "unmapped": []}))
    result = parse_constraints("about 30k please", Preferences(), LLM)
    # The rules answer stands, the invented figure never reaches the preferences, and it is reported.
    assert result.mode == "rules" and result.preferences.budget == 30000
    assert any("failed validation" in note for note in result.notes)


def test_model_quote_must_come_from_the_message(monkeypatch):
    monkeypatch.setattr(module, "request_json", scripted({"constraints": [
        {"field": "ownership_years", "value": 7, "quote": "keeping it 7 years"},
    ], "unmapped": []}))
    result = parse_constraints("about 30k please", Preferences(), LLM)
    assert result.mode == "rules" and result.preferences.ownership_years == 3


@pytest.mark.parametrize("item", [
    {"field": "price", "value": 19999, "quote": "about 30k"},
    {"field": "mileage", "value": 30000, "quote": "about 30k"},
    {"field": "candidate", "value": "Car A", "quote": "about 30k"},
    {"field": "budget", "value": "thirty thousand", "quote": "about 30k"},
    {"field": "transmission", "value": "cvt", "quote": "about 30k"},
])
def test_a_listing_fact_or_bad_value_is_refused(monkeypatch, item):
    monkeypatch.setattr(module, "request_json", scripted({"constraints": [item], "unmapped": []}))
    result = parse_constraints("about 30k please", Preferences(), LLM)
    assert result.mode == "rules"
    assert {c.field for c in result.constraints} == {"budget"}
    assert result.preferences.budget == 30000


def test_model_failure_degrades_to_rules(monkeypatch):
    def unavailable(*args, **kwargs):
        raise module.LLMUnavailable("Model response unavailable or invalid.")
    monkeypatch.setattr(module, "request_json", unavailable)
    result = parse_constraints(SENTENCE, Preferences(), LLM)
    assert result.mode == "rules" and result.preferences.budget == 30000
    assert any("unavailable" in note for note in result.notes)


def test_existing_preferences_are_extended_not_replaced():
    prior = Preferences(budget=50000, must_haves=["sunroof"], priorities=["Comfort"])
    prefs = parse_constraints("needs heated seats too", prior, Settings()).preferences
    assert prefs.budget == 50000 and prefs.must_haves == ["sunroof", "heated seats"]
    assert prefs.priorities == ["Comfort"]


def test_a_repeated_constraint_is_not_duplicated():
    prefs = parse_constraints("needs a sunroof", Preferences(must_haves=["sunroof"]), Settings()).preferences
    assert prefs.must_haves == ["sunroof"]


def test_rule_constraints_are_bounded():
    assert len(rule_constraints("awd " * 500)) <= 40


def test_endpoint_returns_validated_preferences():
    response = client.post("/api/constraints", json={"message": "Under $32,000, keeping it 4 years"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rules"
    assert body["preferences"]["budget"] == 32000 and body["preferences"]["ownership_years"] == 4
    assert [c["field"] for c in body["constraints"]] == ["ownership_years", "budget"]


def test_endpoint_rejects_an_empty_message_and_an_unknown_preference_field():
    assert client.post("/api/constraints", json={"message": "  "}).status_code == 422
    assert client.post("/api/constraints", json={
        "message": "hi", "preferences": {"annual_mileage": 1000, "ownership_years": 2, "location": "",
                                          "priorities": [], "must_haves": [], "price": 100}}).status_code == 422


@pytest.mark.parametrize("message, absent", [
    ("I don't need AWD", ("must_haves", "all-wheel drive")),
    ("We do not need a sunroof", ("must_haves", "sunroof")),
    ("needs automatic climate control", ("transmission", "automatic")),
    ("manual seats are fine", ("transmission", "manual")),
    ("something newer than 2020 model year, under 2020 model year is out", ("budget", 2020.0)),
])
def test_rules_do_not_misread_these_phrases(message, absent):
    assert absent not in [(c.field, c.value) for c in rule_constraints(message)]


def test_rules_still_read_a_plain_gearbox_and_must_have():
    found = [(c.field, c.value) for c in rule_constraints("has to be automatic and needs AWD")]
    assert ("transmission", "automatic") in found and ("must_haves", "all-wheel drive") in found


@pytest.mark.parametrize("value, quote, grounded", [
    (30000, "about 30k", True), (3000, "about 30k", False), (40000, "under 40", True),
    (35500, "$35,500 max", True), (3550, "$35,500 max", False), (1500, "15 hundred", True),
])
def test_model_numbers_must_be_read_with_their_own_scale(value, quote, grounded):
    assert module._number_grounded(value, quote) is grounded
