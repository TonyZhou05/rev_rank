"""Offline regressions for identity-gated search recovery; all vehicles are synthetic."""
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main, retrieval, search as search_module
from backend.app.config import Settings
from backend.app.fetch import FetchError, Page
from backend.app.models import ImportRequest, ImportResponse
from backend.app.search import SearchError, SearchResult


VIN = "WBS1H9C50HV123456"
OTHER_VIN = "WBS1H9C50HV654321"
STOCK = "26789012"
URL = f"https://www.carmax.com/car/{STOCK}"
MIRROR = "https://www.example.com/listing/synthetic-m2"


def listing(vin=VIN, stock=STOCK, price="42,500", mileage="18,000"):
    return (f"Make: BMW\nModel: M2\nYear: 2017\nPrice: ${price} USD\n"
            f"Mileage: {mileage} miles\nVIN: {vin}\nStock: {stock}\n"
            "Seller: CarMax\nTransmission: manual\nLocation: Austin, TX")


def forbidden(*args, **kwargs):
    raise AssertionError("This offline test must not perform network access")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Catch both direct HTTP and accidental DNS before any request escapes.
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(main, "fetch_listing", forbidden)
    monkeypatch.setattr(retrieval, "search", forbidden)
    monkeypatch.setattr(main, "settings", Settings())


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",),
                        search_api_key="test")
    monkeypatch.setattr(main, "settings", settings)
    return settings


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def blocked(monkeypatch):
    calls = []

    def fetch(url, settings):
        calls.append(url)
        raise FetchError("blocked", "Source returned HTTP 403.")

    monkeypatch.setattr(main, "fetch_listing", fetch)
    return calls


class Calls(list):
    domains: list


def stub_search(monkeypatch, results):
    calls = Calls()

    def search(query, settings, timeout=10, domain=None):
        calls.append(query)
        domains.append(domain)
        return list(results)

    domains = []
    calls.domains = domains

    monkeypatch.setattr(retrieval, "search", search)
    return calls


def recover(settings, **kwargs):
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    return retrieval.recover_listing(ImportRequest(url=URL, **kwargs), settings, original)


def test_settings_search_is_opt_in():
    assert Settings().search_provider == "brave"
    assert Settings().search_api_key == ""
    assert Settings().search_enabled is False
    assert Settings(search_api_key="test").search_enabled is True
    assert ImportRequest(url=URL).recover is True


@pytest.mark.parametrize("url,seller,stock", [
    (URL, "carmax", STOCK),
    ("https://www.carvana.com/vehicle/3456789", "carvana", "3456789"),
])
def test_url_only_recovers_stock_identity(client, configured, blocked, monkeypatch, url, seller, stock):
    calls = stub_search(monkeypatch, [SearchResult(url=url, text=listing(stock=stock))])
    response = client.post("/api/import", json={"url": url})
    assert response.status_code == 200
    body = response.json()
    assert body["recovery_status"] == "recovered"
    candidate = body["candidate"]
    assert candidate["evidence"]["vin"]["value"] == VIN
    assert (candidate["make"], candidate["model"], candidate["year"]) == ("BMW", "M2", 2017)
    assert candidate["price"] == 42500
    assert candidate["mileage"] == 18000
    assert candidate["currency"] == "USD"
    assert candidate["source_url"] == url
    assert blocked == [url]
    assert 1 <= len(calls) <= 3
    assert stock in calls[0] and seller in calls[0].lower()
    # Once the stock query binds a VIN, the budget goes to VIN queries, not a repeat URL query.
    assert calls[1:] == [f'"{VIN}"', f'"{VIN}" price']
    assert body["attempts"]
    assert all({"method", "status", "detail"} <= attempt.keys() for attempt in body["attempts"])
    assert any("403" in attempt["detail"] for attempt in body["attempts"])


def test_empty_search_uses_bounded_stock_and_url_queries(configured, monkeypatch):
    calls = stub_search(monkeypatch, [])
    result = recover(configured)
    assert result.recovery_status == "not_found"
    assert result.candidate is None
    assert 1 <= len(calls) <= 3
    assert STOCK in calls[0] and "carmax" in calls[0].lower()
    assert '"carmax.com/car/26789012"' in calls
    # Stock and listing queries are scoped to the seller's site.
    assert calls.domains == ["carmax.com"] * len(calls)


def test_explicit_vin_is_queried_exactly(configured, monkeypatch):
    calls = stub_search(monkeypatch, [])
    result = recover(configured, vin=VIN)
    assert result.recovery_status == "not_found"
    assert 1 <= len(calls) <= 3
    assert f'"{VIN}"' in calls


def test_matching_vin_can_recover_cross_source(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url=MIRROR, text=listing(stock="99999999"))])
    result = recover(configured, vin=VIN)
    assert result.recovery_status == "recovered"
    assert result.candidate.evidence["vin"].value == VIN
    assert result.candidate.price == 42500


@pytest.mark.parametrize("text", [
    listing(vin=OTHER_VIN),
    listing() + f"\nOther inventory VIN: {OTHER_VIN}",
    listing() + f"\nVIN: {OTHER_VIN}",
])
def test_wrong_or_multiple_unique_vins_are_rejected(configured, monkeypatch, text):
    stub_search(monkeypatch, [SearchResult(url=URL, text=text)])
    result = recover(configured, vin=VIN)
    assert result.recovery_status in {"not_found", "identity_conflict"}
    assert result.candidate is None


def test_mixed_inventory_rejected_without_user_vin(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url=URL, text=listing() + f"\nVIN: {OTHER_VIN}")])
    result = recover(configured)
    assert result.recovery_status in {"not_found", "identity_conflict"}
    assert result.candidate is None


def test_different_sources_assign_different_vins_to_stock(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url=URL, text=listing()),
                             SearchResult(url=MIRROR, text=listing(vin=OTHER_VIN))])
    result = recover(configured)
    assert result.recovery_status == "identity_conflict"
    assert result.candidate is None


def test_stock_without_vin_is_insufficient_identity(configured, monkeypatch):
    # An inventory page mentioning the stock number is not the listing itself.
    stub_search(monkeypatch, [SearchResult(url="https://www.carmax.com/cars/bmw/m2",
                                        text=listing().replace(f"VIN: {VIN}\n", ""))])
    result = recover(configured)
    assert result.recovery_status == "not_found"
    assert result.candidate is None


CARVANA = "https://www.carvana.com/vehicle/3456789"
SUMMARY = "Used 2017 BMW M2 Base Coupe 2D for $42500 with 18000 miles. 365 HP and 343 lb-ft"


def test_exact_listing_summary_recovers_without_vin(configured, monkeypatch):
    calls = stub_search(monkeypatch, [SearchResult(url="https://www.carvana.com/cars", text="Shop used cars on Carvana."),
                                      SearchResult(url=CARVANA, text=SUMMARY)])
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    result = retrieval.recover_listing(ImportRequest(url=CARVANA + "?refSource=home"), configured, original)
    assert result.recovery_status == "recovered"
    candidate = result.candidate
    assert (candidate.year, candidate.make, candidate.model, candidate.trim) == (2017, "BMW", "M2", "Base Coupe 2D")
    assert (candidate.price, candidate.mileage, candidate.mileage_unit) == (42500, 18000, "mi")
    # Carvana is a US-only marketplace: its bare "$" is USD, and the inference is labeled.
    assert candidate.currency == "USD"
    assert "US marketplace" in candidate.evidence["currency"].source
    assert "vin" not in candidate.evidence
    assert all(o.vin is None for o in candidate.observations)
    assert any(w.startswith("VIN unknown") for w in candidate.warnings)
    assert "VIN unknown" in result.message
    assert all("refSource" not in q for q in calls)


def test_exact_listing_summary_does_not_override_other_vin(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url=CARVANA, text=SUMMARY + f" VIN {OTHER_VIN}")])
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    result = retrieval.recover_listing(ImportRequest(url=CARVANA, vin=VIN), configured, original)
    assert result.recovery_status in {"not_found", "identity_conflict"}
    assert result.candidate is None


def test_similar_listing_without_vin_is_ignored(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url="https://www.carvana.com/vehicle/3456780", text=SUMMARY)])
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    result = retrieval.recover_listing(ImportRequest(url=CARVANA), configured, original)
    assert result.recovery_status == "not_found"


def test_snippet_normalizer_drops_truncated_tail_and_reads_asking_price():
    text = retrieval.snippet_text(f"VIN: {VIN}. Listed by CarMax. Asking$42,500. Mileage: 18,000; City, State: Austin,")
    assert "Price: $42,500" in text and "Mileage: 18,000" in text
    assert "Austin" not in text


@pytest.mark.parametrize("text", ["VIN: WBS1H9C50HV123456. 502 mi away • $149 transfer",
                                  "Delivered within 50 miles of Austin", "Search radius 25 miles from 78701"])
def test_shopper_distance_is_not_mileage(text):
    from backend.app.extraction import extract
    candidate, _ = extract(text, "https://www.example.com/listing", fetched=True)
    assert candidate.mileage is None


def test_flattened_snippet_labels_are_extracted(configured, monkeypatch):
    text = (f"Stock: {STOCK}. VIN: {VIN}. Base specifications. Body: 2D Coupe; Mileage: 18,000; "
            "City, State: Austin, Texas; Prior Use: Personal")
    stub_search(monkeypatch, [SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=text)])
    result = recover(configured)
    assert result.recovery_status == "recovered"
    assert result.candidate.mileage == 18000
    # State names are normalized so sources writing "Texas" and "TX" agree.
    assert result.candidate.location == "Austin, TX"


def test_repeated_same_vin_is_one_identity(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url=URL, text=listing() + f"\nVIN: {VIN}")])
    result = recover(configured, vin=VIN)
    assert result.recovery_status == "recovered"
    assert result.candidate.evidence["vin"].value == VIN


def test_unrelated_stock_is_not_selected(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url="https://www.carmax.com/car/99999999",
                                        text=listing(stock="99999999"))])
    result = recover(configured)
    assert result.recovery_status in {"not_found", "identity_conflict"}
    assert result.candidate is None


@pytest.mark.parametrize("unsafe", [
    "http://127.0.0.1/listing", "http://10.0.0.1/listing",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/listing",
    "http://localhost/listing", "https://user:password@example.com/listing",
    "file:///etc/passwd", "https://www.example.com:8443/listing",
])
def test_unsafe_search_source_is_discarded(configured, monkeypatch, unsafe):
    stub_search(monkeypatch, [SearchResult(url=unsafe, text=listing())])
    result = recover(configured, vin=VIN)
    assert result.recovery_status != "recovered"
    assert result.candidate is None


def test_unsafe_result_does_not_poison_valid_result(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url="http://127.0.0.1/car", text=listing(price="1")),
                             SearchResult(url=URL, text=listing())])
    result = recover(configured, vin=VIN)
    assert result.recovery_status == "recovered"
    assert result.candidate.price == 42500


@pytest.mark.parametrize("field,changed,values", [("price", listing(price="43,500"), {42500, 43500})])
def test_conflicting_numbers_are_withheld_with_observations(configured, monkeypatch, field, changed, values):
    # Two syndicated copies, neither from the seller: nothing outranks the other.
    stub_search(monkeypatch, [SearchResult(url="https://www.example.org/copy", text=listing()),
                             SearchResult(url=MIRROR, text=changed)])
    result = recover(configured, vin=VIN)
    assert result.recovery_status == "recovered"
    assert result.status == "partial"
    candidate = result.candidate
    assert getattr(candidate, field) is None
    assert any(w.startswith(f"Conflicting {field}:") for w in candidate.warnings)
    assert candidate.conflicts
    observations = [item.model_dump() for item in candidate.observations]
    assert values <= {float(item["value"]) for item in observations if item["field"] == field}


def test_duplicate_agreeing_results_do_not_create_conflicts(configured, monkeypatch):
    hit = SearchResult(url=URL, text=listing())
    stub_search(monkeypatch, [hit, hit])
    result = recover(configured, vin=VIN)
    assert result.recovery_status == "recovered"
    assert result.candidate.price == 42500
    assert not any(w.startswith("Conflicting price:") for w in result.candidate.warnings)


def test_provider_failure_is_truthful(client, configured, blocked, monkeypatch):
    calls = []

    def fail(query, settings, timeout=10, **kwargs):
        calls.append(query)
        raise SearchError("Search provider unavailable")

    monkeypatch.setattr(retrieval, "search", fail)
    response = client.post("/api/import", json={"url": URL})
    assert response.status_code == 200
    body = response.json()
    assert body["recovery_status"] == "failed"
    assert body["candidate"] is None
    assert 1 <= len(calls) <= 3
    assert any(a["status"] == "failed" for a in body["attempts"])


@pytest.mark.parametrize("vin", ["", "123", VIN[:-1], VIN + "1", VIN.lower(),
                                 "I" + VIN[1:], "O" + VIN[1:], "Q" + VIN[1:]])
def test_invalid_vin_is_422_before_network(client, configured, vin):
    response = client.post("/api/import", json={"url": URL, "vin": vin})
    assert response.status_code == 422
    assert any(error["loc"][-1] == "vin" for error in response.json()["detail"])


def test_recover_false_never_searches(client, configured, blocked):
    response = client.post("/api/import", json={"url": URL, "recover": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["recovery_status"] == "disabled"
    assert body["candidate"] is None
    assert blocked == [URL]


def test_missing_key_never_searches(client, blocked, monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(live_fetch_enabled=True,
                                                allowed_domains=("www.carmax.com",)))
    response = client.post("/api/import", json={"url": URL})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["recovery_status"] == "unavailable"
    assert body["candidate"] is None


@pytest.mark.parametrize("text", [listing(), "Make: BMW\nModel: M2"])
@pytest.mark.parametrize("reference", [None, URL])
def test_paste_never_fetches_or_searches(client, configured, text, reference):
    body = {"text": text, "recover": True, "vin": VIN}
    if reference:
        body["url"] = reference
    response = client.post("/api/import", json=body)
    assert response.status_code == 200
    candidate = response.json()["candidate"]
    assert candidate["source_kind"] == "user"
    assert candidate["make"] == "BMW"


def test_partial_direct_import_triggers_recovery(client, configured, monkeypatch):
    monkeypatch.setattr(main, "fetch_listing", lambda url, settings: Page(
        text=f"Make: BMW\nModel: M2\nYear: 2017\nVIN: {VIN}\nStock: {STOCK}", url=url))
    calls = stub_search(monkeypatch, [SearchResult(url=URL, text=listing())])
    response = client.post("/api/import", json={"url": URL})
    assert response.status_code == 200
    body = response.json()
    assert calls
    assert body["recovery_status"] == "recovered"
    assert body["candidate"]["price"] == 42500
    assert body["candidate"]["evidence"]["vin"]["value"] == VIN


def test_complete_direct_import_does_not_search(client, configured, monkeypatch):
    monkeypatch.setattr(main, "fetch_listing", lambda url, settings: Page(text=listing(), url=url))
    response = client.post("/api/import", json={"url": URL})
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["candidate"]["price"] == 42500


def test_bare_dollar_on_unknown_site_stays_unconfirmed(configured, monkeypatch):
    stub_search(monkeypatch, [SearchResult(url=MIRROR, text=f"VIN: {VIN}\nPrice: $42,500\nMileage: 18,000")])
    result = recover(configured, vin=VIN)
    assert result.candidate.price == 42500
    assert result.candidate.currency == "UNK"


@pytest.mark.parametrize("text,price", [(f"VIN: {VIN}. View details. Advertised price. $42,500. High price.", 42500),
                                        (f"VIN: {VIN} price $9,641 below market 4,019 miles.", None)])
def test_only_labeled_prices_are_read(configured, monkeypatch, text, price):
    stub_search(monkeypatch, [SearchResult(url="https://www.truecar.com/used-cars-for-sale/listings/bmw/m2/", text=text)])
    result = recover(configured, vin=VIN)
    # A search page listing many cars yields only labeled fields; with none, there is no car at all.
    assert (result.candidate.price if result.candidate else None) == price


def test_seller_pages_outrank_syndicated_copies(configured, monkeypatch):
    calls = stub_search(monkeypatch, [SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=listing()),
                                      SearchResult(url=MIRROR, text=listing(mileage="4,019"))])
    result = recover(configured, vin=VIN)
    candidate = result.candidate
    # A lower reading elsewhere is an older observation: kept, but not reported as a disagreement.
    assert candidate.mileage == 18000 and "mileage" not in candidate.conflicts
    assert not any("mileage" in w for w in candidate.warnings)
    assert {float(o.value) for o in candidate.observations if o.field == "mileage"} == {18000, 4019}
    # VIN queries are open to other sites.
    assert calls.domains == [None] * len(calls)


def test_detailless_exact_excerpt_is_not_a_recovery(configured, monkeypatch):
    calls = stub_search(monkeypatch, [SearchResult(url=CARVANA, text="Carvana\nVehicle image 1\nVehicle image 2")])
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    result = retrieval.recover_listing(ImportRequest(url=CARVANA), configured, original)
    assert result.recovery_status == "not_found" and result.candidate is None
    # Nothing useful yet, so all three seller-scoped phrasings were tried.
    assert calls == ['"3456789" carvana.com', '"carvana.com/vehicle/3456789"', "3456789"]


def test_no_vin_plan_stops_once_the_summary_is_found(configured, monkeypatch):
    calls = stub_search(monkeypatch, [SearchResult(url=CARVANA, text=SUMMARY)])
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    result = retrieval.recover_listing(ImportRequest(url=CARVANA), configured, original)
    assert result.recovery_status == "recovered"
    assert calls == ['"3456789" carvana.com']


def test_title_recognizer_covers_known_makes():
    from backend.app.extraction import extract
    candidate, _ = extract("Carvana\n2025 Audi A5 Sportback vehicle photo", "https://www.carvana.com/vehicle/1", fetched=True)
    assert (candidate.year, candidate.make, candidate.model) == (2025, "Audi", "A5")
    candidate, _ = extract("2019 Land Rover Range Rover Sport HSE", "https://www.example.com/x", fetched=True)
    assert (candidate.make, candidate.model) == ("Land Rover", "Range Rover")


def registry(monkeypatch, year=2017):
    from backend.app.vehicle_data import VinDecode
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: VinDecode(
        vin=VIN, year=year, make="BMW", model="M2", trim="Base", body="Coupe", engine="3.0L 6 cyl", problem=None))


def test_aggregate_page_heading_is_not_vehicle_identity(monkeypatch):
    # Shape of a real CarGurus market-analysis excerpt: the heading is about the page, not this VIN.
    settings = Settings(search_api_key="test", vin_decode_enabled=True)
    registry(monkeypatch)
    stub_search(monkeypatch, [
        SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=listing()),
        SearchResult(url="https://www.cargurus.com/Cars/l-Used-2016-BMW-M2-c1", text=(
            f"{VIN}. CarGurus Analysis: 2016 BMW M2. 5.0. With 175 currently listed for sale, 29.1% of 2016 BMW M2s"))])
    candidate = recover(settings, vin=VIN).candidate
    assert (candidate.year, candidate.model) == (2017, "M2")
    assert "year" not in candidate.conflicts and "model" not in candidate.conflicts


def test_third_party_identity_disagreement_defers_to_vin_decode(monkeypatch):
    settings = Settings(search_api_key="test", vin_decode_enabled=True)
    registry(monkeypatch)
    stub_search(monkeypatch, [SearchResult(url=MIRROR, text=listing().replace("Year: 2017", "Year: 2016"))])
    candidate = recover(settings, vin=VIN).candidate
    assert candidate.year == 2017 and "year" not in candidate.conflicts
    assert any(w.startswith("Another source reports year 2016") for w in candidate.warnings)
    assert {o.value for o in candidate.observations if o.field == "year"} == {"2016", "2017"}


def test_space_separated_labels_and_truncated_tail():
    text = retrieval.snippet_text(f"VIN: {VIN} Base specifications Body: 2D Coupe Vehicle Size: Midsize "
                                  "Type: Coupes, Sports Cars Mileage: 30,368 City,")
    assert "\nMileage: 30,368" in text and text.endswith("30,368")
    assert "\nBody: 2D Coupe" in text


def test_no_vin_plan_continues_past_a_title_only_excerpt(configured, monkeypatch):
    calls = []

    def search(query, settings, timeout=10, domain=None):
        calls.append(query)
        return [SearchResult(url=CARVANA, text="Title: 2017 BMW M2 | Carvana" if len(calls) == 1 else SUMMARY)]
    monkeypatch.setattr(retrieval, "search", search)
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    candidate = retrieval.recover_listing(ImportRequest(url=CARVANA), configured, original).candidate
    assert (candidate.price, candidate.mileage) == (42500, 18000)
    assert len(calls) == 2


def mileage_case(monkeypatch, configured, results):
    stub_search(monkeypatch, results)
    return recover(configured, vin=VIN).candidate


def test_higher_mileage_elsewhere_is_reported_but_seller_value_is_shown(configured, monkeypatch):
    candidate = mileage_case(monkeypatch, configured, [
        SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=listing(mileage="18,000")),
        SearchResult(url=MIRROR, text=listing(mileage="18,450"))])
    assert candidate.mileage == 18000 and "mileage" in candidate.conflicts
    assert any(w.startswith("Conflicting mileage: another source reports 18,450, higher than the seller reading of 18,000")
               for w in candidate.warnings)


def test_seller_reporting_several_readings_uses_the_highest(configured, monkeypatch):
    candidate = mileage_case(monkeypatch, configured, [
        SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=listing(mileage="17,950")),
        SearchResult(url="https://www.carmax.com/cars/coupes", text=listing(mileage="18,000"))])
    assert candidate.mileage == 18000 and "mileage" not in candidate.conflicts


def test_without_a_seller_reading_the_highest_is_shown_unflagged(configured, monkeypatch):
    candidate = mileage_case(monkeypatch, configured, [
        SearchResult(url=MIRROR, text=listing(mileage="18,000")),
        SearchResult(url="https://www.example.org/copy", text=listing(mileage="19,000"))])
    assert candidate.mileage == 19000 and "mileage" not in candidate.conflicts


def test_lone_higher_seller_reading_does_not_override_the_consensus(configured, monkeypatch):
    # Seven excerpts read 2,322 and one leaked neighbor card reads 21,252 (real Rubicon case, synthetic VIN).
    # Distinct excerpt windows of the same card, as the real pages returned them.
    results = [SearchResult(url=f"https://www.carmax.com/cars/jeep/p{i}", text=listing(mileage="2,322") + f"\nPage: {i}") for i in range(2)]
    results.append(SearchResult(url="https://www.carmax.com/cars/jeep/wrangler/2024", text=listing(mileage="21,252") + "\nType: SUV"))
    candidate = mileage_case(monkeypatch, configured, results)
    assert candidate.mileage == 2322 and "mileage" in candidate.conflicts
    assert any("another source reports 21,252" in w for w in candidate.warnings)


def search_transport(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(search_module.httpx, "Client",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.parametrize("code,reason", [
    (432, "the account's usage limit is exhausted"),
    (429, "the provider is rate limiting this server"),
    (401, "the API key was rejected"),
    (500, None),
])
def test_provider_refusal_names_what_the_operator_must_fix(monkeypatch, code, reason):
    """RevRank's own meter counts only this checkout, so a spent key is invisible until the API says so."""
    search_transport(monkeypatch, lambda request: httpx.Response(code, json={"detail": {"error": "nope"}}))
    settings = Settings(search_provider="tavily", search_api_key="test")
    with pytest.raises(SearchError) as error:
        search_module.search("anything", settings)
    assert f"HTTP {code}" in str(error.value)
    assert (reason in str(error.value)) if reason else str(error.value).endswith(f"HTTP {code}.")
