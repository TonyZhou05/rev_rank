"""Regressions from the live URL corpus (scripts/url_corpus.json). Vehicles are synthetic; the page and
snippet shapes mirror what real sites returned."""
import socket

import pytest
from fastapi.testclient import TestClient

from backend.app import fetch, main, retrieval
from backend.app.config import Settings
from backend.app.fetch import FetchError, Page, Response
from backend.app.models import ImportRequest, ImportResponse
from backend.app.search import SearchResult
from backend.app.vehicle_data import VinDecode

VIN = "1G1YC2D41M5101164"
OTHER = "1G1FK1R64N0130896"
LISTING = "https://www.autotrader.com/cars-for-sale/vehicle/775250873?zip=79402"


def forbidden(*args, **kwargs):
    raise AssertionError("offline test")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(retrieval, "search", forbidden)


def stub_search(monkeypatch, results):
    calls = []
    monkeypatch.setattr(retrieval, "search", lambda q, s, timeout=10, domain=None: calls.append(q) or list(results))
    return calls


def test_expired_listing_redirect_to_search_page_is_not_followed(monkeypatch):
    monkeypatch.setattr(fetch, "check_robots", lambda url, settings, deadline: None)
    monkeypatch.setattr(fetch, "request_once", lambda url, settings, deadline, limit: Response(
        302, {"location": "/cars-for-sale/toyota/rav4/lubbock-tx?redirectExpiredPage=1"}, b""))
    settings = Settings(live_fetch_enabled=True, allowed_domains=("www.autotrader.com",))
    with pytest.raises(FetchError) as error:
        fetch.fetch_listing(LISTING, settings)
    assert "sold or removed" in error.value.message


def test_page_with_several_vehicles_never_supplies_identity(monkeypatch):
    page = (f'<script type="application/ld+json">[{{"@type":"Car","name":"Used 2022 Toyota RAV4","vehicleIdentificationNumber":"{VIN}"}},'
            f'{{"@type":"Car","name":"Used 2025 Toyota RAV4","vehicleIdentificationNumber":"{OTHER}"}}]</script>')
    monkeypatch.setattr(main, "settings", Settings(live_fetch_enabled=True, allowed_domains=("www.autotrader.com",), search_api_key="t"))
    monkeypatch.setattr(main, "fetch_listing", lambda url, settings: Page(text=page, url=url))
    calls = stub_search(monkeypatch, [])
    body = TestClient(main.app).post("/api/import", json={"url": LISTING}).json()
    assert body["candidate"] is None
    assert any("several vehicles" in a["detail"] for a in body["attempts"])
    # Neither page VIN was used to search: the plan is the seller-scoped listing id, not a VIN.
    assert calls and not any(VIN in q or OTHER in q for q in calls)


def test_url_vin_is_attached_when_page_does_not_label_it(monkeypatch):
    url = f"https://www.truecar.com/used-cars-for-sale/listing/{VIN}/2021-chevrolet-corvette/"
    monkeypatch.setattr(main, "settings", Settings(live_fetch_enabled=True, allowed_domains=("www.truecar.com",)))
    monkeypatch.setattr(main, "fetch_listing", lambda u, s: Page(text=f"2021 Chevrolet Corvette\n{VIN}\nPrice: $67,494 USD\nMileage: 16,151 miles", url=u))
    body = TestClient(main.app).post("/api/import", json={"url": url}).json()
    assert body["candidate"]["evidence"]["vin"] == {"value": VIN, "source": "VIN shown on the listing page", "status": "extracted"}


def recover(url, settings, **kwargs):
    return retrieval.recover_listing(ImportRequest(url=url, **kwargs), settings, ImportResponse(status="blocked", message="403"))


def test_unrelated_multi_vin_pages_are_not_an_identity_conflict(monkeypatch):
    stub_search(monkeypatch, [SearchResult(url="https://www.cars.com/shopping/lexus/", text=f"Lexus {VIN} and {OTHER}")])
    result = recover("https://www.cars.com/vehicledetail/5397b0a9-43d8-4367-a42c-b80007a59c23/", Settings(search_api_key="t"))
    assert result.recovery_status == "not_found"
    assert "no page about this listing" in result.message
    assert any("0 about this listing" in a.detail for a in result.attempts)


def test_known_vin_with_only_other_vins_falls_back_to_decode(monkeypatch):
    stub_search(monkeypatch, [SearchResult(url="https://dealer.example.com/tacoma", text=f"VIN {OTHER}. Stock # 1.")])
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: VinDecode(
        vin=VIN, year=2021, make="Chevrolet", model="Corvette", trim="Premium 3LT", body="Coupe", engine="6.2L 8 cyl", problem=None))
    result = recover(f"https://www.edmunds.com/chevrolet/corvette/2021/vin/{VIN}/", Settings(search_api_key="t", vin_decode_enabled=True), vin=VIN)
    assert result.recovery_status == "identity_only"
    assert (result.candidate.year, result.candidate.model) == (2021, "Corvette")


def test_marketplace_search_page_is_rejected(monkeypatch):
    result = recover("https://www.cargurus.com/Cars/l-Used-Subaru-Outback-d380", Settings(search_api_key="t"))
    assert result.recovery_status == "not_listing" and result.candidate is None
    assert "not one car's listing" in result.message


def test_seller_page_saying_sold_is_reported(monkeypatch):
    stub_search(monkeypatch, [SearchResult(url="https://www.carvana.com/vehicle/3450496",
                                           text="This vehicle is no longer available. We've got 852 other Honda Civic in stock.")])
    result = recover("https://www.carvana.com/vehicle/3450496", Settings(search_api_key="t"))
    assert result.recovery_status == "not_found" and "no longer available" in result.message
