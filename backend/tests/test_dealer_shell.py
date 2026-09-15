"""Offline regressions for the dealer link-out shell.

All vehicles and dealers are synthetic. The point of these tests is what the shell refuses to do:
invent a dealer identity, invent coordinates, spend an extra paid call, or trust a link that came
in with a request.
"""
import socket
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.app import comparison, dealer, main, retrieval, vehicle_data
from backend.app.config import Settings
from backend.app.models import DEALER_SCOPE, Candidate, DealerInfo, ImportRequest, ImportResponse, Preferences
from backend.app.search import SearchResult
from backend.app.vehicle_data import DealerRecord, InventoryListing

VIN = "WBS1H9C50HV123456"
STOCK = "26789012"
URL = f"https://www.carmax.com/car/{STOCK}"
MIRROR = "https://www.example.com/listing/synthetic-m2"
DEALER = {"name": "Synthetic Motors of Austin", "website": "https://www.synthetic-motors.example",
          "street": "100 Example Row", "city": "Austin", "state": "TX", "zip": "78701",
          "phone": "(512) 555-0100"}


def forbidden(*args, **kwargs):
    raise AssertionError("This offline test must not perform network access")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(main, "fetch_listing", forbidden)
    monkeypatch.setattr(retrieval, "search", forbidden)
    monkeypatch.setattr(retrieval, "inventory_search", forbidden)
    monkeypatch.setattr(retrieval, "decode_vin", forbidden)
    monkeypatch.setattr(retrieval, "decode_neovin_msrp", lambda settings, vin, timeout=8: None)
    # Report building must not reach NHTSA either; safety data is another slice.
    monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda year, make, model: None)
    monkeypatch.setattr(main, "settings", Settings())


def record(**changes) -> DealerRecord:
    fields = {"name": DEALER["name"], "website": DEALER["website"], "phone": DEALER["phone"],
              "street": DEALER["street"], "city": DEALER["city"], "state": DEALER["state"],
              "postal_code": DEALER["zip"]}
    return DealerRecord(**{**fields, **changes})


def row(url=URL, dealer_record=..., location="Austin, TX", **extra) -> InventoryListing:
    return InventoryListing(vin=VIN, source_url=url, stock_no=STOCK, heading="2017 BMW M2", price=42500,
                            miles=18000, year=2017, make="BMW", model="M2", location=location,
                            seller=DEALER["name"], last_seen="2026-09-10T00:00:00Z",
                            dealer=record() if dealer_record is ... else dealer_record, **extra)


def licensed(**changes) -> Settings:
    return Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",),
                    marketcheck_api_key="test", **changes)


def stub_inventory(monkeypatch, by_filter):
    calls = []

    def inventory_search(settings, timeout=10, **query):
        (key, value), = query.items()
        calls.append((key, value))
        return list(by_filter.get(key, []))

    monkeypatch.setattr(retrieval, "inventory_search", inventory_search)
    return calls


def recover(settings, url=URL, **kwargs) -> ImportResponse:
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    return retrieval.recover_listing(ImportRequest(url=url, **kwargs), settings, original)


def query_of(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


# --- Payload mapping -------------------------------------------------------------------------

def test_parse_listing_maps_the_dealer_object():
    parsed = vehicle_data.parse_listing({"vin": VIN, "vdp_url": URL, "dealer": DEALER,
                                         "build": {"year": 2017, "make": "BMW"}})
    assert parsed.seller == DEALER["name"]
    # city/state still describe where the car is; the dealer block keeps the rooftop's own address.
    assert parsed.location == "Austin, TX"
    assert parsed.dealer == record()


def test_parse_listing_keeps_only_usable_dealer_fields():
    parsed = vehicle_data.parse_listing({"vin": VIN, "vdp_url": URL, "dealer": {
        "name": "  Synthetic Motors  ", "website": {"url": "https://nope.example"}, "phone": 5125550100,
        "street": "", "city": "Austin", "state": "TX", "zip": 78701, "latitude": 30.26, "longitude": -97.74}})
    assert parsed.dealer == DealerRecord(name="Synthetic Motors", website=None, phone="5125550100",
                                         street=None, city="Austin", state="TX", postal_code="78701")


@pytest.mark.parametrize("payload", [{}, {"latitude": 30.26, "longitude": -97.74}, "not a dealer", None])
def test_dealer_without_identity_is_null(payload):
    assert vehicle_data.parse_dealer(payload) is None
    assert vehicle_data.parse_listing({"vin": VIN, "vdp_url": URL, "dealer": payload}).dealer is None


def test_dealer_block_is_null_when_the_record_names_no_business():
    assert dealer.from_listing(row(dealer_record=None)) is None
    assert dealer.dealer_info(name=None, website=None, city=None) is None


def test_dealer_name_is_never_derived_from_the_listing_url():
    # An address-only record stays nameless: "carmax.com" is not a dealer name.
    info = dealer.from_listing(row(dealer_record=record(name=None, website=None)))
    assert info.name is None
    assert info.address == "100 Example Row, Austin, TX 78701"
    assert DEALER["name"] not in (info.maps_url or "")
    # Nothing to look up by name, so only the area link the ZIP supports is offered.
    assert [link.label for link in info.links] == ["DealerRater dealers near 78701"]


# --- Constructed links -----------------------------------------------------------------------

def test_maps_url_is_a_keyless_search_over_the_reported_address():
    url = dealer.maps_url(DEALER["name"], DEALER["street"], DEALER["city"], DEALER["state"], DEALER["zip"])
    assert url.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert query_of(url)["query"] == ["Synthetic Motors of Austin 100 Example Row Austin TX 78701"]
    assert query_of(url)["api"] == ["1"]
    # No API key, and no coordinate pin: the record's own text is what Maps receives.
    assert "key=" not in url and "@" not in url


def test_maps_url_encodes_a_hostile_dealer_name():
    url = dealer.maps_url("Ampersand & Co #1 <b>", city="Austin")
    assert query_of(url)["query"] == ["Ampersand & Co #1 <b> Austin"]
    assert "<b>" not in url and "#" not in url


def test_maps_url_needs_something_to_search_for():
    assert dealer.maps_url() is None
    assert dealer.maps_url(name="   ", city=None) is None


def test_address_line_uses_only_the_parts_present():
    assert dealer.address_line(city="Austin", state="TX") == "Austin, TX"
    assert dealer.address_line(street="100 Example Row", postal_code="78701") == "100 Example Row, 78701"
    assert dealer.address_line() is None


def test_lookup_links_are_constructed_searches_not_ratings():
    links = dealer.lookup_links(DEALER["name"], DEALER["city"], DEALER["state"], DEALER["zip"])
    bbb, dealerrater = links
    assert bbb.url.startswith("https://www.bbb.org/search?")
    assert query_of(bbb.url)["find_text"] == [DEALER["name"]]
    assert query_of(bbb.url)["find_loc"] == ["Austin, TX"]
    assert query_of(dealerrater.url)["PostalCode"] == ["78701"]
    assert all("does not read, quote or score" in link.note for link in links)


def test_lookup_links_need_a_name_or_a_zip():
    assert dealer.lookup_links(city="Austin", state="TX") == []
    assert [link.label for link in dealer.lookup_links(postal_code="78701-1234")] == ["DealerRater dealers near 78701"]
    assert dealer.lookup_links(name=DEALER["name"], postal_code="not a zip")[0].label == "Look up on BBB"


def test_unsafe_dealer_website_is_dropped_not_shown():
    for unsafe in ("javascript:alert(1)", "http://127.0.0.1/dealer", "https://user:pw@dealer.example", ""):
        info = dealer.dealer_info(name=DEALER["name"], website=unsafe, city="Austin")
        assert info.website is None and info.source_domain is None


def test_dealer_block_carries_its_scope_and_provenance():
    info = dealer.from_listing(row())
    assert info.scope == DEALER_SCOPE
    assert info.source.startswith("Dealer as reported by the licensed inventory record for " + URL)
    assert "provider last seen 2026-09-10T00:00:00Z" in info.source
    assert info.notes[0].endswith("They describe the business, not this VIN.")
    assert info.vdp_url == URL and info.source_domain == "synthetic-motors.example"


def test_dealer_block_says_when_the_car_sits_elsewhere():
    info = dealer.from_listing(row(location="West Memphis, AR"))
    assert info.vehicle_location == "West Memphis, AR"
    assert any("places the car in West Memphis, AR, not at this rooftop" in note for note in info.notes)
    # Same place: no note to make, and none invented.
    assert not any("places the car in" in note for note in dealer.from_listing(row()).notes)


def test_name_only_record_says_the_map_link_is_a_name_search():
    info = dealer.from_listing(row(dealer_record=record(street=None, city=None, state=None, postal_code=None)))
    assert info.address is None
    assert any("no dealer address" in note for note in info.notes)


# --- Recovery path ---------------------------------------------------------------------------

def test_licensed_recovery_populates_the_dealer_without_extra_calls(monkeypatch):
    calls = stub_inventory(monkeypatch, {"vdp_url": [row()]})
    candidate = recover(licensed()).candidate
    # One paid call, exactly as before this slice: the dealer rides on the same payload.
    assert calls == [("vdp_url", URL)]
    info = candidate.dealer
    assert (info.name, info.phone, info.city, info.state) == (DEALER["name"], DEALER["phone"], "Austin", "TX")
    # The website keeps the reported host; validation only normalises the empty path to "/".
    assert info.website == DEALER["website"] + "/"
    assert info.address == "100 Example Row, Austin, TX 78701"
    assert query_of(info.maps_url)["query"] == ["Synthetic Motors of Austin 100 Example Row Austin TX 78701"]


def test_syndicated_copy_never_supplies_the_dealer(monkeypatch):
    # The VIN lookup found only a mirror of this listing, so which rooftop sells the car is unknown.
    stub_inventory(monkeypatch, {"vin": [row(url=MIRROR)]})
    candidate = recover(licensed(), vin=VIN).candidate
    assert candidate.dealer is None


def test_search_recovery_has_no_dealer_block(monkeypatch):
    stub_inventory(monkeypatch, {})
    monkeypatch.setattr(retrieval, "search", lambda query, settings, timeout=10, **kwargs: [
        SearchResult(url=URL, text=f"Make: BMW\nModel: M2\nYear: 2017\nPrice: $42,500 USD\nVIN: {VIN}")])
    result = recover(licensed(search_api_key="test"))
    assert result.candidate.retrieval_method == "search"
    assert result.candidate.dealer is None


def test_import_response_exposes_the_dealer_block(monkeypatch):
    monkeypatch.setattr(main, "settings", licensed())
    monkeypatch.setattr(main, "fetch_listing", lambda url, settings: (_ for _ in ()).throw(
        __import__("backend.app.fetch", fromlist=["FetchError"]).FetchError("blocked", "The website returned HTTP 403.")))
    stub_inventory(monkeypatch, {"vdp_url": [row()]})
    with TestClient(main.app) as client:
        body = client.post("/api/import", json={"url": URL}).json()
    info = body["candidate"]["dealer"]
    assert info["name"] == DEALER["name"] and info["scope"] == DEALER_SCOPE
    assert info["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")
    assert [link["label"] for link in info["links"]] == ["Look up on BBB", "DealerRater dealers near 78701"]


# --- Report building -------------------------------------------------------------------------

def candidate(**changes) -> Candidate:
    fields = {"id": "a", "title": "2017 BMW M2", "source_kind": "listing", "make": "BMW", "model": "M2",
              "year": 2017, "price": 42500, "currency": "USD"}
    return Candidate(**{**fields, **changes})


def report_for(*candidates):
    return comparison.create_report(list(candidates), Preferences(), Settings())


def test_report_rebuilds_the_dealer_links_it_was_sent():
    sent = DealerInfo(name=DEALER["name"], city="Austin", state="TX",
                      maps_url="https://maps.example.test/pinned?lat=30.26&lng=-97.74",
                      address="somewhere else entirely",
                      links=[{"label": "Dealer score", "url": "https://ratings.example.test/9-out-of-10"}])
    info = report_for(candidate(dealer=sent), candidate(id="b", title="2018 BMW M2")).candidates[0].dealer
    assert query_of(info.maps_url)["query"] == ["Synthetic Motors of Austin Austin TX"]
    assert info.address == "Austin, TX"
    assert [link.label for link in info.links] == ["Look up on BBB"]


def test_report_drops_an_empty_dealer_block():
    report = report_for(candidate(dealer=DealerInfo(name=None, notes=["Trust me"])),
                        candidate(id="b", title="2018 BMW M2"))
    assert report.candidates[0].dealer is None
    assert report.candidates[1].dealer is None
