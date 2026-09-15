"""A cancelled import stops before its next paid provider call. Offline: every provider is stubbed."""
import pytest

from backend.app import retrieval
from backend.app.cancel import DISCONNECTED, CancelToken, Cancelled
from backend.app.config import Settings
from backend.app.models import Candidate, ImportRequest, ImportResponse
from backend.app.retrieval import attach_original_msrp

URL = "https://www.carmax.com/car/26789012"
PAID = Settings(marketcheck_api_key="test", search_api_key="test", search_provider="tavily")


def test_a_disconnect_stops_recovery_before_the_next_paid_call(monkeypatch):
    token, calls = CancelToken(timeout=60), []

    def inventory_search(settings, timeout=10, **query):
        calls.append(("marketcheck", query))
        token.cancel(DISCONNECTED)  # The buyer closes the page while the first lookup is out.
        return []

    monkeypatch.setattr(retrieval, "inventory_search", inventory_search)
    monkeypatch.setattr(retrieval, "search", lambda *args, **kwargs: calls.append(("search", args)) or [])
    original = ImportResponse(status="blocked", message="Source returned HTTP 403.")
    with pytest.raises(Cancelled):
        retrieval.recover_listing(ImportRequest(url=URL), PAID, original, token=token)
    assert [provider for provider, _ in calls] == ["marketcheck"]


def test_a_cancelled_import_does_not_buy_the_msrp_decode(monkeypatch):
    monkeypatch.setattr(retrieval, "decode_neovin_msrp",
                        lambda *args, **kwargs: pytest.fail("A cancelled import must not spend the NeoVIN call"))
    token = CancelToken(timeout=60)
    token.cancel(DISCONNECTED)
    with pytest.raises(Cancelled):
        attach_original_msrp(Candidate(id="car", title="car", source_kind="listing"), "WBS1H9C50HV123456", PAID, [], token=token)
