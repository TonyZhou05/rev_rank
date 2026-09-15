"""Offline regressions for private-browse recovery after Direct is blocked.

CI never launches Chromium or hits a live listing. Playwright is replaced at
`browse_listing` / `_playwright_open`. No MarketCheck, Tavily, or DeepSeek calls.
"""
import socket

import pytest
from fastapi.testclient import TestClient

from backend.app import browse, main, retrieval
from backend.app.browse import BrowseError, is_review_host
from backend.app.cancel import DISCONNECTED, TIMEOUT, CancelToken, Cancelled
from backend.app.config import Settings
from backend.app.fetch import FetchError, Page, Response
from backend.app.models import ImportRequest, ImportResponse
from backend.app.search import SearchResult


VIN = "WBS1H9C50HV123456"
STOCK = "26789012"
URL = f"https://www.carmax.com/car/{STOCK}"
REVIEW = "https://www.dealerrater.com/dealer/synthetic-board/"

VDP_HTML = """<!doctype html><html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Vehicle","name":"2017 BMW M2",
 "brand":{"@type":"Brand","name":"BMW"},"model":"M2","vehicleModelDate":"2017",
 "mileageFromOdometer":{"@type":"QuantitativeValue","value":18000,"unitCode":"SMI"},
 "offers":{"@type":"Offer","price":42500,"priceCurrency":"USD"},
 "vehicleIdentificationNumber":"WBS1H9C50HV123456"}
</script><title>2017 BMW M2</title></head>
<body><h1>2017 BMW M2</h1><p>Price: $42,500 USD</p><p>Mileage: 18,000 miles</p>
<p>VIN: WBS1H9C50HV123456</p><p>Location: Austin, TX</p></body></html>
"""

CHALLENGE_HTML = "<html><body>Access Denied. Checking your browser. cf-chl-</body></html>"


def forbidden(*args, **kwargs):
    raise AssertionError("This offline test must not perform network access")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(main, "fetch_listing", forbidden)
    monkeypatch.setattr(retrieval, "search", forbidden)
    monkeypatch.setattr(retrieval, "inventory_search", forbidden)
    monkeypatch.setattr(retrieval, "decode_vin", forbidden)
    monkeypatch.setattr(retrieval, "decode_neovin_msrp", lambda settings, vin, timeout=8: None)
    monkeypatch.setattr(main, "settings", Settings())


def browsable(**extra):
    return Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",),
                    browser_recovery_enabled=True, **extra)


def recover(settings, url=URL, original_status="blocked", **kwargs):
    original = ImportResponse(status=original_status, message="Source returned HTTP 403.")
    return retrieval.recover_listing(ImportRequest(url=url, **kwargs), settings, original)


def stub_browse(monkeypatch, html=VDP_HTML, url=None, error=None, calls=None):
    def browse_listing(target, settings, token=None, timeout=20):
        if calls is not None:
            calls.append(target)
        if token is not None:
            token.check()
        if error is not None:
            raise error
        return Page(text=html, url=url or target)

    monkeypatch.setattr(retrieval, "browse_listing", browse_listing)
    monkeypatch.setattr(browse, "browse_listing", browse_listing)
    return calls if calls is not None else []


def stub_search(monkeypatch, text, calls=None):
    found = calls if calls is not None else []

    def search(query, settings, timeout=10, domain=None):
        found.append(query)
        return [SearchResult(url=URL, text=text)]

    monkeypatch.setattr(retrieval, "search", search)
    return found


# ---- policy (no Playwright) ------------------------------------------------------------------
def test_review_hosts_are_refused_before_playwright(monkeypatch):
    launched = []
    monkeypatch.setattr(browse, "_playwright_open", lambda *a, **k: launched.append(1))
    settings = Settings(live_fetch_enabled=True, allowed_domains=("www.dealerrater.com",),
                        browser_recovery_enabled=True)
    with pytest.raises(BrowseError) as err:
        browse.browse_listing(REVIEW, settings)
    assert err.value.status == "refused" and "Review sites" in err.value.message
    assert launched == []
    assert is_review_host("www.dealerrater.com") and is_review_host("reddit.com")
    assert not is_review_host("www.carmax.com") and not is_review_host("carvana.com")


def test_robots_disallow_refuses_without_playwright(monkeypatch):
    launched = []
    monkeypatch.setattr(browse, "_playwright_open", lambda *a, **k: launched.append(1))

    def request(url, *args):
        if str(url).endswith("/robots.txt"):
            return Response(200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /car/")
        raise AssertionError("listing must not be fetched to check robots")

    monkeypatch.setattr("backend.app.fetch.request_once", request)
    settings = browsable()
    with pytest.raises(BrowseError) as err:
        browse.browse_listing(URL, settings)
    assert err.value.status == "refused" and "disallows" in err.value.message
    assert launched == []


def test_unreadable_robots_still_allows_the_single_user_url(monkeypatch):
    """CarMax from Render: robots.txt itself is HTTP 403. That is not an explicit Disallow."""
    opened = []

    def request(url, *args):
        return Response(403, {}, b"")

    monkeypatch.setattr("backend.app.fetch.request_once", request)
    monkeypatch.setattr(browse, "_playwright_open", lambda url, host, token, timeout: opened.append(url) or Page(text=VDP_HTML, url=url))
    page = browse.browse_listing(URL, browsable())
    assert opened == [URL] and "BMW" in page.text


# ---- recovery orchestration ------------------------------------------------------------------
def test_browse_recovers_core_fields_after_direct_blocked(monkeypatch):
    stub_browse(monkeypatch)
    result = recover(browsable())
    assert result.recovery_status == "recovered"
    car = result.candidate
    assert car.retrieval_method == "browse"
    assert (car.year, car.make, car.model) == (2017, "BMW", "M2")
    assert car.price == 42500 and car.mileage == 18000
    assert car.evidence["vin"].value == VIN
    assert any(a.method == "browse" and a.status == "completed" for a in result.attempts)
    assert "private browse" in result.message


def test_browse_is_seller_primary_and_skips_search(monkeypatch):
    searched = stub_search(monkeypatch, "Make: Honda\nModel: Civic\nYear: 2014\nPrice: $1 USD\nMileage: 1 miles")
    stub_browse(monkeypatch)
    settings = browsable(search_api_key="test")
    result = recover(settings)
    assert result.candidate.make == "BMW" and result.candidate.retrieval_method == "browse"
    assert searched == []


def test_browse_blocked_falls_through_to_search(monkeypatch):
    stub_browse(monkeypatch, error=BrowseError("blocked", "The private browse received HTTP 403."))
    stub_search(monkeypatch, f"Make: BMW\nModel: M2\nYear: 2017\nPrice: $41,000 USD\nMileage: 19,000 miles\nVIN: {VIN}")
    settings = browsable(search_api_key="test")
    result = recover(settings)
    assert result.recovery_status == "recovered"
    assert result.candidate.retrieval_method == "search"
    assert result.candidate.price == 41000
    assert any(a.method == "browse" and a.status == "blocked" for a in result.attempts)


def test_licensed_hit_does_not_browse(monkeypatch):
    from backend.app.vehicle_data import InventoryListing
    browsed = []
    monkeypatch.setattr(retrieval, "browse_listing", lambda *a, **k: browsed.append(1))

    def inventory_search(settings, timeout=10, **query):
        return [InventoryListing(vin=VIN, source_url=URL, stock_no=STOCK, heading="2017 BMW M2",
                                 price=40000, miles=17000, year=2017, make="BMW", model="M2")]

    monkeypatch.setattr(retrieval, "inventory_search", inventory_search)
    result = recover(browsable(marketcheck_api_key="test"))
    assert result.candidate.retrieval_method == "licensed" and browsed == []


def test_recovery_source_browse_skips_licensed_and_search(monkeypatch):
    licensed = []
    searched = stub_search(monkeypatch, "unused")
    monkeypatch.setattr(retrieval, "inventory_search", lambda *a, **k: licensed.append(1) or [])
    stub_browse(monkeypatch)
    result = recover(browsable(marketcheck_api_key="test", search_api_key="test"), recovery_source="browse")
    assert result.candidate.retrieval_method == "browse"
    assert licensed == [] and searched == []


def test_marketcheck_source_does_not_browse_even_when_enabled(monkeypatch):
    from backend.app.vehicle_data import InventoryListing
    browsed = []
    monkeypatch.setattr(retrieval, "browse_listing", lambda *a, **k: browsed.append(1))
    monkeypatch.setattr(retrieval, "inventory_search", lambda *a, **k: [
        InventoryListing(vin=VIN, source_url=URL, stock_no=STOCK, heading="2017 BMW M2",
                         price=40000, miles=17000, year=2017, make="BMW", model="M2")])
    result = recover(browsable(marketcheck_api_key="test"), recovery_source="marketcheck")
    assert result.candidate.retrieval_method == "licensed" and browsed == []


def test_browse_not_used_unless_direct_was_blocked(monkeypatch):
    browsed = []
    monkeypatch.setattr(retrieval, "browse_listing", lambda *a, **k: browsed.append(1))
    result = recover(browsable(), original_status="restricted")
    assert browsed == []
    assert result.candidate is None


def test_review_url_recovery_is_refused_and_does_not_search_when_source_is_browse(monkeypatch):
    searched = stub_search(monkeypatch, "unused")
    launched = []
    monkeypatch.setattr(browse, "_playwright_open", lambda *a, **k: launched.append(1))
    result = recover(browsable(), url=REVIEW, recovery_source="browse")
    assert result.recovery_status in {"failed", "not_found"}
    assert any(a.method == "browse" and a.status == "refused" for a in result.attempts)
    assert searched == [] and launched == []


def test_unconfigured_browse_source_is_explained():
    result = recover(Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",)),
                     recovery_source="browse")
    assert result.recovery_status == "unavailable" and "private browser" in result.message


def test_browse_alone_makes_recovery_available(monkeypatch):
    stub_browse(monkeypatch)
    result = recover(browsable())
    assert result.recovery_status == "recovered"


def test_challenge_page_is_blocked_not_extracted(monkeypatch):
    stub_browse(monkeypatch, html=CHALLENGE_HTML)
    # extract() of challenge HTML should yield no core fields → not_found, or we detect in browse_listing.
    # The stub returns the HTML; browse_records extracts it. Access-denied copy is not a vehicle.
    result = recover(browsable())
    assert result.candidate is None
    assert result.recovery_status in {"not_found", "failed"}


def test_vin_mismatch_is_identity_conflict(monkeypatch):
    stub_browse(monkeypatch)
    result = recover(browsable(), vin="1G1FK1R64N0130896")
    assert result.recovery_status == "identity_conflict" and result.candidate is None


# ---- cancel / timeout ------------------------------------------------------------------------
def test_expired_token_records_browse_timeout_instead_of_hanging(monkeypatch):
    def hang(url, settings, token=None, timeout=20):
        if token is None:
            raise AssertionError("browse must receive the import cancel token")
        token.cancel(TIMEOUT)
        token.check()
        raise AssertionError("browse should have been cancelled")

    monkeypatch.setattr(retrieval, "browse_listing", hang)
    token = CancelToken(timeout=30)
    result = retrieval.recover_listing(
        ImportRequest(url=URL, recovery_source="browse"), browsable(),
        ImportResponse(status="blocked", message="403"), token=token)
    assert result.recovery_status == "failed"
    assert any(a.method == "browse" and a.status == "timeout" for a in result.attempts)


def test_disconnect_during_browse_raises_cancelled(monkeypatch):
    def hang(url, settings, token=None, timeout=20):
        token.check()
        raise AssertionError("should have cancelled first")

    monkeypatch.setattr(retrieval, "browse_listing", hang)
    token = CancelToken(timeout=30)
    token.cancel(DISCONNECTED)
    with pytest.raises(Cancelled) as stop:
        retrieval.recover_listing(
            ImportRequest(url=URL, recovery_source="browse"), browsable(),
            ImportResponse(status="blocked", message="403"), token=token)
    assert stop.value.reason == DISCONNECTED


def test_api_browse_after_403(monkeypatch):
    def blocked(url, settings):
        raise FetchError("blocked", "The website returned HTTP 403.")

    monkeypatch.setattr(main, "fetch_listing", blocked)
    stub_browse(monkeypatch)
    monkeypatch.setattr(main, "settings", browsable())
    with TestClient(main.app) as client:
        body = client.post("/api/import", json={"url": URL}).json()
    assert body["recovery_status"] == "recovered"
    assert body["candidate"]["retrieval_method"] == "browse"
    assert body["candidate"]["make"] == "BMW"


def test_health_reports_browse_and_import_timeout(monkeypatch):
    monkeypatch.setattr(main, "settings", browsable(import_timeout_seconds=55))
    with TestClient(main.app) as client:
        health = client.get("/api/health").json()
    assert health["browser_recovery_enabled"] is True
    assert health["import_timeout_seconds"] == 55
    assert health["api_revision"] == 9


def test_api_revision_matches_frontend():
    import pathlib
    import re
    page = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/api.ts").read_text()
    assert re.search(r"API_REVISION = (\d+)", page).group(1) == "9"
