"""Offline regressions for licensed-inventory recovery and VIN registry cross-checks.

All vehicles are synthetic. Provider calls are replaced at the adapter boundary.
"""
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main, retrieval, vehicle_data
from backend.app.config import Settings
from backend.app.fetch import FetchError
from backend.app.models import ImportRequest, ImportResponse
from backend.app.search import SearchError, SearchResult
from backend.app.vehicle_data import InventoryListing, ProviderError, VinDecode

VIN = "WBS1H9C50HV123456"
OTHER_VIN = "WBS1H9C50HV654321"
STOCK = "26789012"
URL = f"https://www.carmax.com/car/{STOCK}"
MIRROR = "https://www.example.com/listing/synthetic-m2"


def row(vin=VIN, url=URL, price=42500, miles=18000, stock=STOCK, year=2017, last_seen="2026-09-10T00:00:00Z", **extra):
    return InventoryListing(vin=vin, source_url=url, stock_no=stock, heading="2017 BMW M2", price=price,
                            miles=miles, year=year, make="BMW", model="M2", transmission="Manual",
                            location="Austin, TX", last_seen=last_seen, **extra)


def decode(year=2017, make="Bmw", model="M2", problem=None, **build):
    return VinDecode(vin=VIN, year=year, make=make, model=model, trim=build.get("trim"), body="Coupe",
                     engine="3.0L 6 cyl", problem=problem, transmission=build.get("transmission"),
                     drivetrain=build.get("drivetrain"), fuel_type=build.get("fuel_type"))


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
    # A bound VIN triggers a NeoVIN MSRP decode; these tests are about identity, so it finds nothing.
    # test_neovin_msrp.py covers the decode itself.
    monkeypatch.setattr(retrieval, "decode_neovin_msrp", lambda settings, vin, timeout=8: None)
    monkeypatch.setattr(retrieval, "browse_listing", forbidden)
    monkeypatch.setattr(main, "settings", Settings())


def licensed(search=False, decode_enabled=False):
    return Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",),
                    marketcheck_api_key="test", search_api_key="test" if search else "",
                    vin_decode_enabled=decode_enabled)


def stub_inventory(monkeypatch, by_filter):
    calls = []

    def inventory_search(settings, timeout=10, source=None, past=False, **query):
        (key, value), = query.items()
        # The past-inventory endpoint takes the same identity filters, scoped to the source website.
        assert source == ("carmax.com" if past else None)
        key = f"past_{key}" if past else key
        calls.append((key, value))
        result = by_filter.get(key, [])
        if isinstance(result, Exception):
            raise result
        return list(result)

    monkeypatch.setattr(retrieval, "inventory_search", inventory_search)
    return calls


def recover(settings, url=URL, **kwargs):
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    return retrieval.recover_listing(ImportRequest(url=url, **kwargs), settings, original)


def test_listing_url_binds_identity_in_one_call(monkeypatch):
    calls = stub_inventory(monkeypatch, {"vdp_url": [row()], "vin": [row(), row(url=MIRROR, price=43500)]})
    result = recover(licensed())
    assert result.recovery_status == "recovered"
    candidate = result.candidate
    assert candidate.retrieval_method == "licensed"
    assert candidate.evidence["vin"].value == VIN
    assert (candidate.make, candidate.model, candidate.year) == ("BMW", "M2", 2017)
    assert candidate.price == 42500 and candidate.currency == "USD"
    assert all(o.method == "licensed" and o.observed_at == "2026-09-10T00:00:00Z" for o in candidate.observations)
    # Paid calls stop once the seller's own listing is found: no VIN lookup for syndicated copies.
    assert calls == [("vdp_url", URL)]
    assert not any("Search observation dates" in w for w in candidate.warnings)


def test_known_vin_finds_seller_and_copies_in_one_call(monkeypatch):
    calls = stub_inventory(monkeypatch, {"vin": [row(), row(url=MIRROR, price=43500)]})
    candidate = recover(licensed(), vin=VIN).candidate
    assert calls == [("vin", VIN)]
    # The seller's own listing wins over a syndicated copy; the disagreement stays visible.
    assert candidate.price == 42500 and "price" not in candidate.conflicts
    assert any(w.startswith("Other sources report a different price") for w in candidate.warnings)
    prices = {(o.source_url, float(o.value)) for o in candidate.observations if o.field == "price"}
    assert prices == {(URL, 42500), (MIRROR, 43500)}


def test_query_string_is_removed_before_lookup(monkeypatch):
    calls = stub_inventory(monkeypatch, {})
    recover(licensed(), url=URL + "?utm_source=test&zip=78701")
    assert calls[0] == ("vdp_url", URL)


def test_stock_lookup_is_seller_scoped(monkeypatch):
    calls = stub_inventory(monkeypatch, {
        "vdp_url": [row(url="https://www.carmax.com/car/99999999", vin=OTHER_VIN, stock="99999999")],
        "stock_no": [row(url=MIRROR, vin=OTHER_VIN), row(url="https://www.carmax.com/car/26789012/", stock=STOCK)],
        "vin": [],
    })
    result = recover(licensed())
    assert result.recovery_status == "recovered"
    assert result.candidate.evidence["vin"].value == VIN
    assert calls == [("vdp_url", URL), ("stock_no", STOCK)]


def test_other_seller_stock_number_is_not_identity(monkeypatch):
    stub_inventory(monkeypatch, {"stock_no": [row(url=MIRROR)]})
    result = recover(licensed())
    assert result.recovery_status == "not_found"
    assert result.candidate is None


def test_conflicting_seller_vins_stop(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row(), row(vin=OTHER_VIN)]})
    result = recover(licensed())
    assert result.recovery_status == "identity_conflict"
    assert result.candidate is None


def test_user_vin_must_match_seller_listing(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row(vin=OTHER_VIN)]})
    result = recover(licensed(), vin=VIN)
    assert result.recovery_status == "identity_conflict"
    assert result.candidate is None


def test_vin_lookup_drops_other_vehicles(monkeypatch):
    stub_inventory(monkeypatch, {"vin": [row(url=MIRROR), row(url="https://www.example.com/other", vin=OTHER_VIN, price=1)]})
    result = recover(licensed(), vin=VIN)
    assert result.recovery_status == "recovered"
    assert {o.source_url for o in result.candidate.observations} == {MIRROR}


def test_syndicated_only_disagreement_is_withheld(monkeypatch):
    stub_inventory(monkeypatch, {"vin": [row(url=MIRROR), row(url="https://www.example.org/copy", price=43500)]})
    result = recover(licensed(), vin=VIN)
    assert result.candidate.price is None
    assert "price" in result.candidate.conflicts


def test_licensed_hit_skips_search(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row()]})
    result = recover(licensed(search=True))
    assert result.recovery_status == "recovered"


def test_licensed_miss_falls_back_to_search(monkeypatch):
    stub_inventory(monkeypatch, {})
    queries = []

    def search(query, settings, timeout=10, **kwargs):
        queries.append(query)
        return [SearchResult(url=URL, text=f"Make: BMW\nModel: M2\nYear: 2017\nPrice: $42,500 USD\nVIN: {VIN}\nStock: {STOCK}")]

    monkeypatch.setattr(retrieval, "search", search)
    result = recover(licensed(search=True))
    assert result.recovery_status == "recovered"
    assert result.candidate.retrieval_method == "search"
    assert queries


@pytest.mark.parametrize("outcome,status", [({}, "not_found"),
                                            ({"vdp_url": ProviderError("Provider returned HTTP 500.")}, "failed")])
def test_licensed_only_failure_is_truthful(monkeypatch, outcome, status):
    stub_inventory(monkeypatch, outcome)
    result = recover(licensed())
    assert result.recovery_status == status
    assert result.candidate is None
    assert any(a.method == "licensed" for a in result.attempts)


def licensed_attempts(result):
    return [(a.status, a.detail) for a in result.attempts if a.method == "licensed"]


def test_lookup_that_received_nothing_is_not_reported_as_completed(monkeypatch):
    """The CarMax report: the licensed lookups came back empty, and each read as a success."""
    calls = stub_inventory(monkeypatch, {})
    result = recover(licensed())
    assert calls == [("vdp_url", URL), ("stock_no", STOCK), ("past_vdp_url", URL)]
    assert [status for status, _ in licensed_attempts(result)] == ["not_found"] * 3
    assert all("holds no listing under this identity" in detail for _, detail in licensed_attempts(result))
    # A car missing from an active-inventory feed has not been observed to sell.
    assert "no active record" in result.message and "does not confirm a sale" in result.message
    assert result.recovery_status == "not_found"


def test_lookup_that_received_other_cars_says_so(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row(url="https://www.carmax.com/car/99999999", vin=OTHER_VIN, stock="99999999")]})
    statuses = licensed_attempts(recover(licensed()))
    assert [status for status, _ in statuses] == ["not_found"] * 3
    assert "1 listings received, none of them this listing." in statuses[0][1]


def test_vin_lookup_counts_syndicated_copies_as_a_hit(monkeypatch):
    """Copies of the bound VIN build the candidate, so that lookup did produce something."""
    stub_inventory(monkeypatch, {"vin": [row(url=MIRROR)]})
    result = recover(licensed(), vin=VIN)
    assert result.recovery_status == "recovered"
    assert licensed_attempts(result)[0] == ("completed", "VIN lookup: 1 listings received, 1 matching this listing.")


def test_expired_record_recovers_identity_but_never_a_current_price(monkeypatch):
    """Active inventory drops a delisted car; the past-inventory endpoint still binds its identity."""
    calls = stub_inventory(monkeypatch, {"past_vdp_url": [row(last_seen="2026-08-30T00:00:00Z")]})
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode())
    result = recover(licensed(decode_enabled=True))
    assert calls[-1] == ("past_vdp_url", URL)
    candidate = result.candidate
    assert result.recovery_status == "recovered"
    assert candidate.evidence["vin"].value == VIN
    # The VIN decode identifies the car; the expired listing's own numbers stay in the past.
    assert (candidate.make, candidate.model, candidate.year) == ("Bmw", "M2", 2017)
    assert candidate.price is None and candidate.mileage is None
    assert candidate.evidence["last_listed_price"].value == "$42,500 (2026-08-30T00:00:00Z)"
    assert any(w.startswith("Licensed inventory holds only an expired record") for w in candidate.warnings)
    assert "does not confirm a sale" in result.message
    # An expired listing names a rooftop that no longer has the car.
    assert candidate.dealer is None
    # With no price, an MSRP is a percentage of nothing: the extra decode is not worth a call.
    assert not any("NeoVIN" in a.detail for a in result.attempts)


def test_active_inventory_hit_spends_no_past_inventory_call(monkeypatch):
    calls = stub_inventory(monkeypatch, {"vdp_url": [row()], "past_vdp_url": [row()]})
    assert recover(licensed()).recovery_status == "recovered"
    assert calls == [("vdp_url", URL)]


def test_past_inventory_lookup_can_be_switched_off(monkeypatch):
    calls = stub_inventory(monkeypatch, {"past_vdp_url": [row()]})
    settings = Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",),
                        marketcheck_api_key="test", marketcheck_past_enabled=False)
    assert recover(settings).recovery_status == "not_found"
    assert calls == [("vdp_url", URL), ("stock_no", STOCK)]


def test_licensed_miss_is_named_when_search_then_fails(monkeypatch):
    """Both legs must appear: a spent search key is not evidence about the listing."""
    stub_inventory(monkeypatch, {})
    exhausted = SearchError("The search provider returned HTTP 432: the account's usage limit is exhausted; "
                            "add credits or raise the plan limit.")

    def search(query, settings, timeout=10, **kwargs):
        raise exhausted

    monkeypatch.setattr(retrieval, "search", search)
    result = recover(licensed(search=True))
    assert result.recovery_status == "failed"
    assert "Licensed inventory holds no active record of this listing" in result.message
    assert "usage limit is exhausted" in result.message


def test_registry_agreement_is_recorded(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row()]})
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode())
    result = recover(licensed(decode_enabled=True))
    candidate = result.candidate
    assert candidate.make == "BMW" and candidate.year == 2017
    assert candidate.evidence["year"].source.endswith("matches NHTSA VIN decode")
    assert {o.field for o in candidate.observations if o.method == "registry"} >= {"year", "make", "body", "engine"}
    assert any(a.method == "registry" and a.status == "completed" for a in result.attempts)


def test_registry_disagreement_withholds_identity_field(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row()]})
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode(year=2019))
    candidate = recover(licensed(decode_enabled=True)).candidate
    assert candidate.year is None
    assert "year" in candidate.conflicts
    assert any(w.startswith("Conflicting year:") for w in candidate.warnings)


def test_registry_fills_missing_identity_and_flags_bad_check_digit(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row(year=None)]})
    monkeypatch.setattr(retrieval, "decode_vin",
                        lambda vin, timeout=8: decode(problem="1 - Check Digit (9th position) does not calculate properly"))
    candidate = recover(licensed(decode_enabled=True)).candidate
    assert candidate.year == 2017
    assert candidate.evidence["year"].source.startswith("NHTSA vPIC")
    assert any("Check Digit" in w for w in candidate.warnings)


def test_registry_failure_does_not_block_recovery(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row()]})

    def fail(vin, timeout=8):
        raise ProviderError("Provider returned HTTP 503.")

    monkeypatch.setattr(retrieval, "decode_vin", fail)
    result = recover(licensed(decode_enabled=True))
    assert result.recovery_status == "recovered"
    assert any(a.method == "registry" and a.status == "failed" for a in result.attempts)


def test_history_flags_remain_dealer_claims(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row(history_claims=("clean title",))]})
    candidate = recover(licensed()).candidate
    assert candidate.history.startswith("Dealer-reported via licensed inventory, not independently verified:")
    assert candidate.evidence["history"].status == "seller_claim"


def test_api_uses_licensed_recovery_after_403(monkeypatch):
    monkeypatch.setattr(main, "settings", licensed())

    def blocked(url, settings):
        raise FetchError("blocked", "The website returned HTTP 403.")

    monkeypatch.setattr(main, "fetch_listing", blocked)
    stub_inventory(monkeypatch, {"vdp_url": [row()]})
    with TestClient(main.app) as client:
        body = client.post("/api/import", json={"url": URL}).json()
        health = client.get("/api/health").json()
    assert body["recovery_status"] == "recovered"
    assert body["candidate"]["retrieval_method"] == "licensed"
    assert any("403" in a["detail"] for a in body["attempts"])
    assert health["licensed_inventory_enabled"] is True and health["vin_decode_enabled"] is False


@pytest.mark.parametrize("raw,kept", [
    ({"vin": VIN, "vdp_url": URL, "price": 42500, "miles": 18000, "build": {"year": 2017, "make": "BMW"}}, True),
    ({"vin": VIN, "vdp_url": "http://127.0.0.1/car"}, False),
    ({"vin": VIN, "vdp_url": "https://www.example.com:8443/car"}, False),
    ({"vin": "NOTAVIN", "vdp_url": URL}, False),
    ({"vin": VIN}, False),
    ("not a listing", False),
])
def test_parse_listing_rejects_unsafe_or_unidentified_rows(raw, kept):
    assert (vehicle_data.parse_listing(raw) is not None) == kept


def test_parse_listing_rejects_non_numeric_values():
    parsed = vehicle_data.parse_listing({"vin": VIN.lower(), "vdp_url": URL, "price": True, "miles": -5,
                                         "build": {"year": "2017"}, "carfax_clean_title": "yes"})
    assert parsed.vin == VIN
    assert (parsed.price, parsed.miles, parsed.year, parsed.history_claims) == (None, None, None, ())


def mock_client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(vehicle_data.httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


def test_inventory_request_keeps_key_out_of_errors_and_urls(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(500, text="secret-key echoed")

    mock_client(monkeypatch, handler)
    settings = Settings(marketcheck_api_key="secret-key")
    with pytest.raises(ProviderError) as error:
        vehicle_data.inventory_search(settings, vdp_url=URL)
    assert "secret-key" not in str(error.value)
    params = seen[0].params
    assert seen[0].host == "api.marketcheck.com"
    assert (params["vdp_url"], params["append_api_key"], params["nodedup"]) == (URL, "false", "true")
    with pytest.raises(ValueError):
        vehicle_data.inventory_search(settings, vin=VIN, vdp_url=URL)


def test_past_inventory_uses_the_expired_endpoint_scoped_to_the_source(monkeypatch):
    seen = []
    mock_client(monkeypatch, lambda request: seen.append(request.url) or httpx.Response(200, json={"listings": []}))
    settings = Settings(marketcheck_api_key="secret-key")
    vehicle_data.inventory_search(settings, vdp_url=URL, source="carmax.com", past=True)
    assert seen[0].path == "/v2/search/car/recents" and seen[0].params["source"] == "carmax.com"
    # The endpoint refuses an unscoped search of 90 days of expired listings; never send one.
    with pytest.raises(ValueError):
        vehicle_data.inventory_search(settings, vdp_url=URL, past=True)


def test_decoder_parses_registry_response(monkeypatch):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json={"Results": [{
        "Make": "MERCEDES-BENZ", "Model": "C-Class", "ModelYear": "2019", "ErrorCode": "0",
        "DisplacementL": "2.0", "EngineCylinders": "4", "BodyClass": "Sedan/Saloon"}]}))
    decoded = vehicle_data.decode_vin(VIN)
    assert (decoded.make, decoded.model, decoded.year, decoded.engine, decoded.problem) == (
        "Mercedes-Benz", "C-Class", 2019, "2.0L 4 cyl", None)
    with pytest.raises(ValueError):
        vehicle_data.decode_vin("../../etc/passwd")


def decode_only():
    return Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",), vin_decode_enabled=True)


def test_user_vin_recovers_identity_without_listing_providers(monkeypatch):
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode())
    result = recover(decode_only(), vin=VIN)
    assert result.recovery_status == "identity_only"
    candidate = result.candidate
    assert (candidate.make, candidate.model, candidate.year) == ("Bmw", "M2", 2017)
    assert candidate.retrieval_method == "registry"
    assert candidate.price is None and candidate.mileage is None
    assert any("identifies the vehicle build, not this listing" in w for w in candidate.warnings)


def test_decode_only_without_vin_is_unavailable(monkeypatch):
    result = recover(decode_only())
    assert result.recovery_status == "unavailable"
    assert result.candidate is None


def test_licensed_miss_still_decodes_supplied_vin(monkeypatch):
    stub_inventory(monkeypatch, {})
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode())
    result = recover(licensed(decode_enabled=True), vin=VIN)
    assert result.recovery_status == "identity_only"
    assert any(a.method == "licensed" for a in result.attempts)


def test_identity_conflict_is_never_overridden_by_decode(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row(vin=OTHER_VIN)]})
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode())
    result = recover(licensed(decode_enabled=True), vin=VIN)
    assert result.recovery_status == "identity_conflict"
    assert result.candidate is None


def test_undecodable_vin_without_records_is_not_found(monkeypatch):
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: None)
    result = recover(decode_only(), vin=VIN)
    assert result.recovery_status == "not_found"
    assert result.candidate is None


def test_registry_fills_build_fields_without_overriding_listing(monkeypatch):
    stub_inventory(monkeypatch, {"vdp_url": [row()]})
    monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: decode(
        trim="Base", transmission="7-speed Automatic", drivetrain="Rear-Wheel Drive", fuel_type="Gasoline"))
    candidate = recover(licensed(decode_enabled=True)).candidate
    # The listing says Manual: registry build data only fills gaps and never creates a conflict.
    assert candidate.transmission == "Manual" and "transmission" not in candidate.conflicts
    assert (candidate.trim, candidate.body, candidate.engine) == ("Base", "Coupe", "3.0L 6 cyl")
    assert (candidate.drivetrain, candidate.fuel_type) == ("Rear-Wheel Drive", "Gasoline")
    assert candidate.evidence["drivetrain"].source.startswith("NHTSA vPIC")


@pytest.mark.parametrize("source,expected", [("marketcheck", "licensed"), ("search", "search")])
def test_recovery_source_switch_calls_only_the_chosen_provider(monkeypatch, source, expected):
    inventory = stub_inventory(monkeypatch, {"vdp_url": [row()]})
    queries = []

    def search(query, settings, timeout=10, **kwargs):
        queries.append(query)
        return [SearchResult(url=URL, text=f"Make: BMW\nModel: M2\nYear: 2017\nPrice: $41,000 USD\nVIN: {VIN}\nStock: {STOCK}")]

    monkeypatch.setattr(retrieval, "search", search)
    result = recover(licensed(search=True), recovery_source=source)
    assert result.candidate.retrieval_method == expected
    assert bool(inventory) == (source == "marketcheck") and bool(queries) == (source == "search")


def test_unconfigured_recovery_source_is_explained(monkeypatch):
    result = recover(licensed(), recovery_source="search")
    assert result.recovery_status == "unavailable" and "not configured" in result.message


def test_budget_stops_paid_calls_before_they_are_sent(monkeypatch):
    sent = []
    mock_client(monkeypatch, lambda request: sent.append(request) or httpx.Response(200, json={"listings": []}))
    settings = Settings(marketcheck_api_key="secret-key", marketcheck_monthly_calls=2)
    vehicle_data.inventory_search(settings, vin=VIN)
    vehicle_data.inventory_search(settings, vin=VIN)
    with pytest.raises(ProviderError, match="monthly budget reached"):
        vehicle_data.inventory_search(settings, vin=VIN)
    assert len(sent) == 2


def test_parse_listing_reads_build_and_car_location():
    parsed = vehicle_data.parse_listing({
        "vin": VIN, "vdp_url": "https://www.carvana.com/vehicle/4711856", "stock_no": "2147483647",
        "dealer": {"city": "Tempe", "state": "AZ"}, "car_location": {"city": "West Memphis", "state": "AR"},
        "build": {"body_type": "Hatchback", "engine": "2.0L I4", "drivetrain": "4WD", "fuel_type": "Premium Unleaded"}})
    assert (parsed.stock_no, parsed.location) == (None, "West Memphis, AR")
    assert (parsed.body, parsed.engine, parsed.drivetrain, parsed.fuel_type) == ("Hatchback", "2.0L I4", "4WD", "Premium Unleaded")
