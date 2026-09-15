"""Offline regressions for private-browse recovery after Direct is blocked.

CI never launches Chromium or hits a live listing. Playwright is replaced at
`browse_listing` / `_playwright_open`. No MarketCheck, Tavily, or DeepSeek calls.
"""
import socket

import pytest
from fastapi.testclient import TestClient

from backend.app import browse, main, retrieval
from backend.app.browse import BrowseError, browse_vdp_allowed, is_review_host
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
<p>VIN: WBS1H9C50HV123456</p><p>Location: Austin, TX</p>
<p>Carfax One Owner. No accidents reported.</p>
<p>Features: Navigation, Heated seats</p>
<p>Engine: 3.0 liter I6 Twin Turbo</p></body></html>
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
def test_browser_recovery_defaults_off(monkeypatch):
    monkeypatch.delenv("REVRANK_BROWSER_RECOVERY_ENABLED", raising=False)
    assert Settings().browser_recovery_enabled is False
    assert Settings.from_env().browser_recovery_enabled is False


# Ship-gate example: Dealer.com inventory slug with a check-digit VIN in the path.
BMW_VIN = "3MW89CW02T8G83036"
DEALER_VDP = (
    "https://www.bmwbuffalo.com/inventory/new-2026-bmw-330i-awd-sedan-3mw89cw02t8g83036/"
)
DEALER_SRP = "https://www.bmwbuffalo.com/used-vehicles/"
DEALER_INDEX = "https://www.bmwbuffalo.com/inventory/"
DEALER_HOME = "https://www.bmwbuffalo.com/"


def test_unknown_host_is_blocked_before_playwright(monkeypatch):
    launched = []
    monkeypatch.setattr(browse, "_playwright_open", lambda *a, **k: launched.append(1))
    unknown = "https://www.example.com/car/1"
    assert browse_vdp_allowed(unknown)[0] is False
    with pytest.raises(BrowseError) as err:
        browse.browse_listing(unknown, browsable())
    assert err.value.status == "refused" and "single vehicle listing" in err.value.message
    assert launched == []
    result = recover(browsable(), url=unknown, recovery_source="browse")
    assert result.candidate is None
    assert any(a.method == "browse" and a.status == "refused" for a in result.attempts)
    assert "Paste the price, mileage, and VIN" in result.message


def test_dealer_inventory_vin_vdp_is_allowlisted(monkeypatch):
    launched = []
    allowed, reason = browse_vdp_allowed(DEALER_VDP)
    assert allowed is True and reason == ""
    # VIN on a non-inventory path, and marketplace listing-id schemes, still work.
    assert browse_vdp_allowed(f"https://www.example-dealer.com/vehicle/{BMW_VIN}")[0] is True
    assert browse_vdp_allowed(URL)[0] is True
    assert browse_vdp_allowed("https://www.carmax.com/cars/bmw")[0] is False
    monkeypatch.setattr(browse, "robots_decision", lambda *a, **k: (True, ""))
    monkeypatch.setattr(browse, "_playwright_open",
                        lambda url, host, token, timeout: launched.append(url) or Page(text=VDP_HTML, url=url))
    # Pattern gate only — the rooftop is not in allowed_domains or BROWSE_VDP_HOSTS.
    page = browse.browse_listing(DEALER_VDP, Settings(live_fetch_enabled=True, browser_recovery_enabled=True))
    assert launched == [DEALER_VDP] and "BMW" in page.text


def test_dealer_search_and_inventory_index_are_refused_before_playwright(monkeypatch):
    launched = []
    monkeypatch.setattr(browse, "_playwright_open", lambda *a, **k: launched.append(1))
    for url in (DEALER_SRP, DEALER_INDEX, "https://www.bmwbuffalo.com/inventory/used/"):
        allowed, message = browse_vdp_allowed(url)
        assert allowed is False and "not a search" in message.lower()
        with pytest.raises(BrowseError) as err:
            browse.browse_listing(url, Settings(live_fetch_enabled=True, browser_recovery_enabled=True))
        assert err.value.status == "refused" and "not a search" in err.value.message.lower()
    home_ok, home_msg = browse_vdp_allowed(DEALER_HOME)
    assert home_ok is False and "single vehicle listing" in home_msg
    assert launched == []


def test_unsupported_direct_browses_dealer_vdp(monkeypatch):
    stub_browse(monkeypatch)
    result = recover(Settings(browser_recovery_enabled=True), url=DEALER_VDP, original_status="unsupported")
    assert result.recovery_status == "recovered"
    assert result.candidate.retrieval_method == "browse"


def test_search_or_category_url_is_refused_before_playwright(monkeypatch):
    launched = []
    monkeypatch.setattr(browse, "_playwright_open", lambda *a, **k: launched.append(1))
    srp = "https://www.carmax.com/cars/bmw"
    assert browse_vdp_allowed(srp)[0] is False
    with pytest.raises(BrowseError) as err:
        browse.browse_listing(srp, browsable())
    assert err.value.status == "refused" and "not a search" in err.value.message.lower()
    assert launched == []


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
    # A VIN in the path does not override REVIEW_HOSTS (classifieds, unknown review boards).
    review_vin = f"https://www.dealerrater.com/classifieds/2026-BMW-iX-ad-{BMW_VIN}-1/"
    allowed, message = browse_vdp_allowed(review_vin)
    assert allowed is False and "Review sites" in message
    with pytest.raises(BrowseError) as vin_err:
        browse.browse_listing(review_vin, settings)
    assert vin_err.value.status == "refused" and launched == []


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
    assert car.evidence["price"].source.startswith("user_vdp_browse")
    digest = __import__("hashlib").sha256(VDP_HTML.encode()).hexdigest()[:16]
    assert any(a.method == "browse" and a.status == "completed" and digest in a.detail
               and a.detail.startswith("user_vdp_browse") for a in result.attempts)
    assert car.history is None and car.features == [] and car.engine is None
    assert car.evidence["stock_no"].value == STOCK
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


def test_browse_hit_skips_licensed(monkeypatch):
    licensed = []
    monkeypatch.setattr(retrieval, "inventory_search", lambda *a, **k: licensed.append(1) or [])
    stub_browse(monkeypatch)
    result = recover(browsable(marketcheck_api_key="test"))
    assert result.candidate.retrieval_method == "browse" and licensed == []


def test_browse_miss_falls_through_to_licensed(monkeypatch):
    from backend.app.vehicle_data import InventoryListing
    stub_browse(monkeypatch, error=BrowseError("blocked", "The private browse received HTTP 403."))

    def inventory_search(settings, timeout=10, **query):
        return [InventoryListing(vin=VIN, source_url=URL, stock_no=STOCK, heading="2017 BMW M2",
                                 price=40000, miles=17000, year=2017, make="BMW", model="M2")]

    monkeypatch.setattr(retrieval, "inventory_search", inventory_search)
    result = recover(browsable(marketcheck_api_key="test"))
    assert result.candidate.retrieval_method == "licensed"
    assert any(a.method == "browse" and a.status == "blocked" for a in result.attempts)


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


def test_browse_not_used_for_restricted_direct(monkeypatch):
    browsed = []
    monkeypatch.setattr(retrieval, "browse_listing", lambda *a, **k: browsed.append(1))
    result = recover(browsable(), original_status="restricted")
    assert browsed == []
    assert result.candidate is None


def test_browse_runs_after_failed_or_thin_direct(monkeypatch):
    stub_browse(monkeypatch)
    failed = recover(browsable(), original_status="failed")
    thin = recover(browsable(), original_status="partial")
    assert failed.recovery_status == "recovered" and thin.recovery_status == "recovered"


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


def test_health_defaults_browse_off(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings())
    with TestClient(main.app) as client:
        health = client.get("/api/health").json()
    assert health["browser_recovery_enabled"] is False


def test_api_revision_matches_frontend():
    import pathlib
    import re
    page = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/api.ts").read_text()
    assert re.search(r"API_REVISION = (\d+)", page).group(1) == "9"
