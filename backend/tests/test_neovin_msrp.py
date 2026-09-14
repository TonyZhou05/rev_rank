"""Offline regressions for the NeoVIN original-MSRP fill.

The payload shapes mirror a real `/v2/decode/car/neovin/{vin}/specs` response; every VIN and price
here is synthetic. No test performs network access.
"""
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import comparison, main, retrieval, vehicle_data
from backend.app.config import Settings
from backend.app.fetch import FetchError, Page
from backend.app.models import Candidate, Evidence, ImportRequest, ImportResponse, Preferences
from backend.app.vehicle_data import InventoryListing, NeoVinMsrp, ProviderError, VinDecode

VIN = "WBS1H9C50HV123456"
OTHER_VIN = "WBS1H9C50HV654321"
STOCK = "26789012"
URL = f"https://www.carmax.com/car/{STOCK}"

# The field set a live decode returned: bare `msrp` is lower than the OEM figure it is labeled with.
SPECS = {"vin": VIN, "msrp": 86500, "msrp_label": "oem_msrp", "oem_msrp": 93245, "build_specs_msrp": None,
         "original_msrp": 93245, "combined_msrp": 93195, "installed_options_msrp": 5700,
         "delivery_charges": 995, "mc_msrp": 93245}


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
    monkeypatch.setattr(retrieval, "decode_neovin_msrp", forbidden)
    monkeypatch.setattr(main, "settings", Settings())


def licensed(**extra):
    return Settings(live_fetch_enabled=True, allowed_domains=("www.carmax.com",),
                    marketcheck_api_key="test", **extra)


def row(**extra):
    return InventoryListing(vin=VIN, source_url=URL, stock_no=STOCK, heading="2017 BMW M2", price=42500,
                            miles=18000, year=2017, make="BMW", model="M2", last_seen="2026-09-10T00:00:00Z", **extra)


def stub_neovin(monkeypatch, result):
    """Record every decode so a test can prove one VIN costs at most one call."""
    calls = []

    def decode(settings, vin, timeout=8):
        calls.append(vin)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(retrieval, "decode_neovin_msrp", decode)
    return calls


def found(amount=93245, field="oem_msrp", labeled_as=None, vin=VIN):
    return NeoVinMsrp(vin=vin, amount=amount, field=field, labeled_as=labeled_as)


class TestFieldPriority:
    def test_oem_msrp_wins_over_bare_and_build_specs_msrp(self):
        picked = vehicle_data.msrp_from_specs(SPECS, VIN)
        assert (picked.amount, picked.field, picked.labeled_as) == (93245, "oem_msrp", None)

    def test_original_msrp_is_next(self):
        picked = vehicle_data.msrp_from_specs({**SPECS, "oem_msrp": None}, VIN)
        assert (picked.amount, picked.field) == (93245, "original_msrp")

    def test_combined_msrp_is_last_of_the_named_fields(self):
        picked = vehicle_data.msrp_from_specs({**SPECS, "oem_msrp": None, "original_msrp": None}, VIN)
        assert (picked.amount, picked.field) == (93195, "combined_msrp")

    def test_bare_msrp_is_used_only_when_labeled_and_uncontradicted(self):
        labeled = {"vin": VIN, "msrp": 93245, "msrp_label": "oem_msrp"}
        picked = vehicle_data.msrp_from_specs(labeled, VIN)
        assert (picked.amount, picked.field, picked.labeled_as) == (93245, "msrp", "oem_msrp")
        assert "msrp labeled oem_msrp" in picked.source

    @pytest.mark.parametrize("payload", [
        # A weaker base figure the label does not vouch for.
        {"vin": VIN, "msrp": 86500, "msrp_label": "base_msrp"},
        # The build sheet alone is not the as-built sticker.
        {"vin": VIN, "build_specs_msrp": 88000, "msrp": 86500},
        # Provider-specific totals are not the OEM figure either.
        {"vin": VIN, "mc_msrp": 93245, "installed_options_msrp": 5700, "delivery_charges": 995},
        # Zero, negative and non-numeric values are not prices.
        {"vin": VIN, "oem_msrp": 0, "original_msrp": -1, "combined_msrp": "93,195"},
        {"vin": VIN, "oem_msrp": True},
        {},
        None,
    ])
    def test_no_usable_figure_leaves_msrp_unknown(self, payload):
        assert vehicle_data.msrp_from_specs(payload, VIN) is None

    def test_named_field_beats_the_bare_figure_it_is_labeled_with(self):
        picked = vehicle_data.msrp_from_specs({"vin": VIN, "msrp": 86500, "msrp_label": "original_msrp",
                                               "original_msrp": 93245}, VIN)
        assert (picked.amount, picked.field) == (93245, "original_msrp")


class TestDecodeRequest:
    def mock_client(self, monkeypatch, handler):
        real = httpx.Client
        monkeypatch.setattr(vehicle_data.httpx, "Client",
                            lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))

    def test_request_targets_the_decode_endpoint_and_meters_one_call(self, monkeypatch):
        seen = []
        self.mock_client(monkeypatch, lambda request: seen.append(request.url) or httpx.Response(200, json=SPECS))
        settings = Settings(marketcheck_api_key="secret-key")
        picked = vehicle_data.decode_neovin_msrp(settings, VIN.lower())
        assert (picked.amount, picked.field, picked.vin) == (93245, "oem_msrp", VIN)
        assert seen[0].host == "api.marketcheck.com"
        assert seen[0].path == f"/v2/decode/car/neovin/{VIN}/specs"
        from backend.app import usage
        assert usage.used(settings, "marketcheck") == 1
        # The evidence source records the endpoint without the key.
        assert "api_key" not in picked.source_url

    def test_errors_never_echo_the_key(self, monkeypatch):
        self.mock_client(monkeypatch, lambda request: httpx.Response(401, text="secret-key echoed"))
        with pytest.raises(ProviderError) as error:
            vehicle_data.decode_neovin_msrp(Settings(marketcheck_api_key="secret-key"), VIN)
        assert "secret-key" not in str(error.value)

    def test_response_about_another_vin_is_refused(self, monkeypatch):
        self.mock_client(monkeypatch, lambda request: httpx.Response(200, json={**SPECS, "vin": OTHER_VIN}))
        with pytest.raises(ProviderError, match="different vehicle"):
            vehicle_data.decode_neovin_msrp(Settings(marketcheck_api_key="secret-key"), VIN)

    def test_budget_stops_the_decode_before_it_is_sent(self, monkeypatch):
        sent = []
        self.mock_client(monkeypatch, lambda request: sent.append(request) or httpx.Response(200, json=SPECS))
        settings = Settings(marketcheck_api_key="secret-key", marketcheck_monthly_calls=1)
        vehicle_data.decode_neovin_msrp(settings, VIN)
        with pytest.raises(ProviderError, match="monthly budget reached"):
            vehicle_data.decode_neovin_msrp(settings, VIN)
        assert len(sent) == 1

    def test_invalid_vin_and_missing_key_never_reach_the_provider(self, monkeypatch):
        self.mock_client(monkeypatch, forbidden)
        with pytest.raises(ValueError):
            vehicle_data.decode_neovin_msrp(Settings(marketcheck_api_key="k"), "../../etc/passwd")
        with pytest.raises(ProviderError, match="not configured"):
            vehicle_data.decode_neovin_msrp(Settings(), VIN)


def recover(settings, url=URL, **kwargs):
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    return retrieval.recover_listing(ImportRequest(url=url, **kwargs), settings, original)


def stub_inventory(monkeypatch, by_filter):
    def inventory_search(settings, timeout=10, **query):
        (key, _), = query.items()
        return list(by_filter.get(key, []))

    monkeypatch.setattr(retrieval, "inventory_search", inventory_search)


class TestRecoveryFill:
    def test_bound_vin_fills_msrp_as_a_sourced_suggestion(self, monkeypatch):
        stub_inventory(monkeypatch, {"vdp_url": [row()]})
        calls = stub_neovin(monkeypatch, found())
        candidate = recover(licensed()).candidate
        assert calls == [VIN]
        assert candidate.msrp == 93245
        evidence = candidate.evidence["msrp"]
        assert evidence.status == "extracted"
        assert evidence.source.startswith("MarketCheck NeoVIN oem_msrp for VIN " + VIN)
        assert "not a listing or asking price" in evidence.source
        # A sourced suggestion, not a confirmed fact: the buyer still owns the field.
        assert "msrp" not in candidate.verified_fields
        observation = next(o for o in candidate.observations if o.field == "msrp")
        assert observation.method == "licensed" and observation.vin == VIN
        assert observation.source_url == f"https://api.marketcheck.com/v2/decode/car/neovin/{VIN}/specs"

    def test_decode_only_recovery_still_fills_msrp(self, monkeypatch):
        stub_inventory(monkeypatch, {})
        monkeypatch.setattr(retrieval, "decode_vin", lambda vin, timeout=8: VinDecode(
            vin=VIN, year=2017, make="Bmw", model="M2", trim=None, body="Coupe", engine="3.0L 6 cyl", problem=None))
        calls = stub_neovin(monkeypatch, found(amount=93195, field="combined_msrp"))
        result = recover(licensed(vin_decode_enabled=True), vin=VIN)
        assert result.recovery_status == "identity_only"
        assert calls == [VIN] and result.candidate.msrp == 93195
        assert result.candidate.evidence["msrp"].source.startswith("MarketCheck NeoVIN combined_msrp")

    def test_unknown_vin_is_never_decoded(self, monkeypatch):
        stub_inventory(monkeypatch, {})
        calls = stub_neovin(monkeypatch, found())
        monkeypatch.setattr(retrieval, "search", lambda query, settings, timeout=10, domain=None: [])
        result = recover(licensed(search_api_key="test"))
        assert calls == [] and result.candidate is None

    def test_search_only_mode_spends_nothing_on_marketcheck(self, monkeypatch):
        calls = stub_neovin(monkeypatch, found())
        monkeypatch.setattr(retrieval, "search", lambda query, settings, timeout=10, domain=None: [])
        recover(licensed(search_api_key="test"), recovery_source="search")
        assert calls == []

    def test_missing_figure_is_reported_and_leaves_msrp_blank(self, monkeypatch):
        stub_inventory(monkeypatch, {"vdp_url": [row()]})
        stub_neovin(monkeypatch, None)
        result = recover(licensed())
        assert result.candidate.msrp is None and "msrp" not in result.candidate.evidence
        assert any("no OEM, original or combined MSRP" in a.detail for a in result.attempts)

    def test_provider_failure_does_not_block_recovery(self, monkeypatch):
        stub_inventory(monkeypatch, {"vdp_url": [row()]})
        stub_neovin(monkeypatch, ProviderError("Provider returned HTTP 503."))
        result = recover(licensed())
        assert result.recovery_status == "recovered" and result.candidate.msrp is None
        assert any("NeoVIN MSRP decode: Provider returned HTTP 503." in a.detail for a in result.attempts)

    def test_neovin_can_be_switched_off(self, monkeypatch):
        stub_inventory(monkeypatch, {"vdp_url": [row()]})
        calls = stub_neovin(monkeypatch, found())
        assert recover(licensed(neovin_enabled=False)).candidate.msrp is None
        assert calls == []


class TestAttachHelper:
    def candidate(self, **extra):
        return Candidate(id="c1", title="2017 BMW M2", source_kind="listing", **extra)

    def test_existing_msrp_is_never_overwritten_or_re_decoded(self, monkeypatch):
        calls = stub_neovin(monkeypatch, found())
        buyer = self.candidate(msrp=90000, verified_fields=["msrp"])
        buyer.evidence["msrp"] = Evidence(value="90000", source="User input", status="user_confirmed")
        retrieval.attach_original_msrp(buyer, VIN, licensed(), [])
        assert buyer.msrp == 90000 and calls == []
        # Twice in one import (recovery then review) still costs one call.
        fresh = self.candidate()
        attempts = []
        retrieval.attach_original_msrp(fresh, VIN, licensed(), attempts)
        retrieval.attach_original_msrp(fresh, VIN, licensed(), attempts)
        assert calls == [VIN] and fresh.msrp == 93245

    def test_no_vin_and_no_key_mean_no_call(self, monkeypatch):
        calls = stub_neovin(monkeypatch, found())
        assert retrieval.attach_original_msrp(self.candidate(), None, licensed(), []).msrp is None
        assert retrieval.attach_original_msrp(self.candidate(), VIN, Settings(), []).msrp is None
        assert calls == []


class TestImportEndpoint:
    def test_pasted_vin_fills_msrp_on_a_pasted_listing(self, monkeypatch):
        monkeypatch.setattr(main, "settings", licensed())
        calls = stub_neovin(monkeypatch, found())
        with TestClient(main.app) as client:
            body = client.post("/api/import", json={
                "text": "2017 BMW M2\nPrice: $42,500 USD\nMileage: 18,000 miles", "vin": VIN}).json()
        assert calls == [VIN]
        assert body["candidate"]["msrp"] == 93245
        assert body["candidate"]["evidence"]["msrp"]["status"] == "extracted"
        assert any("original MSRP" in a["detail"] for a in body["attempts"])
        # The VIN that sourced the MSRP is kept as the buyer's own input, not dropped as unknown.
        assert body["candidate"]["evidence"]["vin"] == {
            "value": VIN, "source": "VIN you entered", "status": "user_confirmed"}

    def test_vin_the_pasted_text_states_keeps_its_own_evidence(self, monkeypatch):
        monkeypatch.setattr(main, "settings", Settings())
        with TestClient(main.app) as client:
            body = client.post("/api/import", json={
                "text": f"2017 BMW M2\nVIN: {VIN}\nPrice: $42,500 USD", "vin": VIN}).json()
        evidence = body["candidate"]["evidence"]["vin"]
        assert evidence["value"] == VIN and evidence["status"] == "extracted"
        assert "pasted listing text" in evidence["source"]

    def test_page_vin_fills_msrp_on_a_fetched_listing(self, monkeypatch):
        monkeypatch.setattr(main, "settings", licensed())
        monkeypatch.setattr(main, "fetch_listing", lambda u, s: Page(url=u, text=(
            f"Make: BMW\nModel: M2\nYear: 2017\nPrice: $42,500 USD\nMileage: 18,000 miles\nVIN: {VIN}")))
        calls = stub_neovin(monkeypatch, found())
        with TestClient(main.app) as client:
            body = client.post("/api/import", json={"url": URL}).json()
        assert body["status"] == "success"
        assert calls == [VIN] and body["candidate"]["msrp"] == 93245

    def test_import_without_a_vin_spends_nothing(self, monkeypatch):
        monkeypatch.setattr(main, "settings", licensed())
        calls = stub_neovin(monkeypatch, found())
        with TestClient(main.app) as client:
            body = client.post("/api/import", json={"text": "2017 BMW M2\nPrice: $42,500 USD"}).json()
        assert calls == [] and body["candidate"]["msrp"] is None

    def test_blocked_page_recovers_and_fills_msrp_once(self, monkeypatch):
        monkeypatch.setattr(main, "settings", licensed())

        def blocked(url, settings):
            raise FetchError("blocked", "The website returned HTTP 403.")

        monkeypatch.setattr(main, "fetch_listing", blocked)
        stub_inventory(monkeypatch, {"vdp_url": [row()]})
        calls = stub_neovin(monkeypatch, found())
        with TestClient(main.app) as client:
            body = client.post("/api/import", json={"url": URL}).json()
            health = client.get("/api/health").json()
        assert calls == [VIN] and body["candidate"]["msrp"] == 93245
        assert health["neovin_msrp_enabled"] is True


def car(title, price, msrp=None):
    return Candidate(id=title, title=title, make="BMW", model="M2", year=2017, price=price, currency="USD",
                     mileage=18000, mileage_unit="mi", source_kind="listing", msrp=msrp)


class TestCompareGate:
    @pytest.fixture(autouse=True)
    def no_nhtsa(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)

    def sourced(self, price=42500, msrp=93245, field="oem_msrp"):
        candidate = car("Decoded", price, msrp)
        candidate.evidence["msrp"] = Evidence(
            value=str(msrp), source=f"MarketCheck NeoVIN {field} for VIN {VIN}; the factory MSRP of the car "
                                    "as built, not a listing or asking price", status="extracted")
        return candidate

    def test_neovin_msrp_unlocks_percent_of_sticker_without_a_buyer_edit(self):
        report = comparison.create_report([self.sourced(), car("Plain", 55000)], Preferences(), Settings())
        assert report.candidates[0].percent_of_msrp == 45.58
        metric = next(m for m in report.metrics if m.label == "% of original MSRP")
        assert metric.values == ["45.6%", "N/A"]

    def test_buyer_edit_of_a_decoded_msrp_wins(self):
        edited = self.sourced()
        edited.msrp = 90000
        edited.verified_fields = ["msrp"]
        edited.evidence["msrp"] = Evidence(value="90000", source="User correction. Previous value: 93245.0",
                                           status="user_confirmed")
        report = comparison.create_report([edited, car("Plain", 55000)], Preferences(), Settings())
        assert report.candidates[0].percent_of_msrp == 47.22

    def test_unsourced_msrp_still_needs_confirmation(self):
        guessed = car("Guessed", 42500, 93245)
        guessed.evidence["msrp"] = Evidence(value="93245", source="Listing page sticker price", status="extracted")
        report = comparison.create_report([guessed, car("Plain", 55000)], Preferences(), Settings())
        assert report.candidates[0].percent_of_msrp is None
        metric = next(m for m in report.metrics if m.label == "% of original MSRP")
        assert metric.values[0] == "MSRP not confirmed"
