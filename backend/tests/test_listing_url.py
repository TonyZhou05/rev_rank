"""Pasted listing URLs: normalization, identity hints, and same-listing matching. Offline."""
import socket

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import Settings
from backend.app.fetch import FetchError
from backend.app.listing_url import identity_url, listing_id, normalize_input_url, same_listing, url_vin, vin_check_digit_ok

VIN = "1G1YC2D41M5101164"  # Real check-digit-valid VIN from a user test listing.


@pytest.mark.parametrize("raw,expected", [
    ("https://www.carmax.com/car/70043489", "https://www.carmax.com/car/70043489"),
    ("carmax.com/car/70043489", "https://carmax.com/car/70043489"),
    ("www.carvana.com/vehicle/4711856?refSource=home", "https://www.carvana.com/vehicle/4711856?refSource=home"),
    ("Check this one: https://www.carmax.com/car/70043489, thanks!", "https://www.carmax.com/car/70043489"),
    ("(https://www.carmax.com/car/70043489)", "https://www.carmax.com/car/70043489"),
    ("See carvana.com/vehicle/4711856.", "https://carvana.com/vehicle/4711856"),
    ("ftp://caredge.com/listing", "ftp://caredge.com/listing"),
    ("user:password@example.com/listing", "user:password@example.com/listing"),
    ("not a url", "not a url"),
])
def test_normalize_input_url(raw, expected):
    assert normalize_input_url(raw) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://www.carmax.com/car/70043489/", "70043489"),
    ("https://www.carvana.com/vehicle/4711856?refSource=home", "4711856"),
    ("https://www.carvana.com/vehicle/lt/3768960?utm_vehicle_id=3768960", "3768960"),
    ("https://www.autotrader.com/cars-for-sale/vehicle/742951234?zip=10001", "742951234"),
    ("https://www.kbb.com/cars-for-sale/vehicle/712345678", "712345678"),
    ("https://www.cars.com/vehicledetail/3f8b2a10-1c2d-4e5f-9a8b-7c6d5e4f3a2b/", "3f8b2a10-1c2d-4e5f-9a8b-7c6d5e4f3a2b"),
    ("https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action?zip=1#listing=384756291", "384756291"),
    ("https://www.example.com/used/2021-corvette", None),
])
def test_listing_id(url, expected):
    assert listing_id(url) == expected


@pytest.mark.parametrize("url,expected", [
    (f"https://www.truecar.com/used-cars-for-sale/listing/{VIN}/2021-chevrolet-corvette/", VIN),
    (f"https://www.edmunds.com/chevrolet/corvette/2021/vin/{VIN}/", VIN),
    (f"https://www.carfax.com/vehicle/{VIN.lower()}", VIN),
    (f"https://www.autolist.com/chevrolet-corvette#vin={VIN}", VIN),
    ("https://www.truecar.com/listing/1G1YC2D41M5101165/", None),  # check digit fails: not a VIN
    ("https://www.example.com/abcdefghjklmnprst", None),           # letters only
    (f"https://www.example.com/{VIN}/compare/1G1FK1R64N0130896", None),  # two VINs: ambiguous
])
def test_url_vin(url, expected):
    assert url_vin(url) == expected


def test_check_digit():
    assert vin_check_digit_ok(VIN) and not vin_check_digit_ok(VIN[:8] + "5" + VIN[9:])


def test_same_listing_ignores_tracking_but_not_identity():
    carvana = "https://www.carvana.com/vehicle/4711856?refSource=home"
    assert same_listing(carvana, "https://carvana.com/vehicle/4711856/")
    assert not same_listing(carvana, "https://www.carvana.com/vehicle/4711857")
    assert same_listing("https://www.carvana.com/vehicle/lt/4711856?utm_vehicle_id=4711856", carvana)
    base = "https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
    # Every CarGurus listing shares one path; only the listing id tells them apart.
    assert same_listing(base + "?zip=1#listing=384756291", base + "?inventoryListing=384756291")
    assert not same_listing(base + "#listing=384756291", base + "?inventoryListing=111")
    assert not same_listing(base + "#listing=384756291", base)


def test_identity_url_keeps_only_listing_identity():
    assert identity_url("https://www.autotrader.com/cars-for-sale/vehicle/742951234?zip=10001&utm_source=x") == \
        "https://www.autotrader.com/cars-for-sale/vehicle/742951234"
    assert identity_url("https://x.com/Cars/view.action?zip=1#listing=42") == "https://x.com/Cars/view.action?listing=42"


def forbidden(*args, **kwargs):
    raise AssertionError("offline test")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(main, "settings", Settings(live_fetch_enabled=True, allowed_domains=("www.truecar.com", "carmax.com")))
    with TestClient(main.app) as instance:
        yield instance


def test_import_normalizes_pasted_url_and_reads_url_vin(client, monkeypatch):
    seen = []

    def fetch(url, settings):
        seen.append(url)
        raise FetchError("blocked", "The website returned HTTP 403.")

    monkeypatch.setattr(main, "fetch_listing", fetch)
    body = client.post("/api/import", json={"url": f"look: www.truecar.com/used-cars-for-sale/listing/{VIN}/2021-corvette/ ok"}).json()
    assert seen == [f"https://www.truecar.com/used-cars-for-sale/listing/{VIN}/2021-corvette/"]
    assert any(a["method"] == "url" and VIN in a["detail"] for a in body["attempts"])


def test_url_vin_conflicting_with_entered_vin_stops(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_listing", forbidden)
    body = client.post("/api/import", json={"url": f"https://www.truecar.com/listing/{VIN}/", "vin": "1G1FK1R64N0130896"}).json()
    assert body["recovery_status"] == "identity_conflict" and body["candidate"] is None
