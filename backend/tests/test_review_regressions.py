"""Regressions found in the 2026-09-15 bug review. Offline: providers and the model are stubbed."""
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import Settings
from backend.app.dealer import safe_link
from backend.app.listing_url import is_listing_url
from backend.app.models import AIAnalysis


@pytest.mark.parametrize("path", ["used-vehicles/toyota/", "inventory/used/chevrolet", "new-vehicles/specials/",
                                  "used-cars/sedan", "autos/trucks"])
def test_dealer_make_and_category_filters_are_not_one_cars_listing(path):
    assert is_listing_url(f"https://www.example-motors.com/{path}") is False


@pytest.mark.parametrize("path", ["autos/18422", "inventory/used/A12345", "inventory/stk9876"])
def test_dealer_stock_numbers_still_read_as_listings(path):
    assert is_listing_url(f"https://www.example-motors.com/{path}") is True


def test_a_bare_dealer_host_from_the_inventory_record_becomes_a_link():
    assert safe_link("carmax.com") == "https://carmax.com/"
    assert safe_link("www.example-motors.com/used") == "https://www.example-motors.com/used"
    for unsafe in ("localhost", "10.0.0.1", "javascript:alert(1)", "user@evil.com"):
        assert safe_link(unsafe) is None


def test_a_vin_read_from_the_url_is_not_labelled_as_the_buyers_input(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings())
    vin = "1HGCM82633A004352"
    result = TestClient(main.app).post("/api/import", json={
        "url": f"https://www.truecar.com/used-cars-for-sale/listing/{vin}/",
        "text": "2003 Honda Accord\nPrice: $4,500 USD\nMileage: 150,000 miles"}).json()
    evidence = result["candidate"]["evidence"]["vin"]
    assert evidence["value"] == vin
    assert evidence["status"] == "extracted" and "URL" in evidence["source"]


def test_findings_reordered_by_the_model_without_an_analysis_stay_rules_based(monkeypatch):
    def reorder(report, settings, token=None):
        report.analysis_mode = "llm"  # What assist_report does after reordering findings.
        return report

    monkeypatch.setattr(main, "assist_report", reorder)
    monkeypatch.setattr(main, "analyze", lambda report, settings, token=None: AIAnalysis(status="unavailable", message="off"))
    cars = TestClient(main.app).get("/api/demo").json()["candidates"][:2]
    body = TestClient(main.app).post("/api/compare", json={"candidates": cars, "preferences": {}}).json()
    assert body["analysis_mode"] == "rules"
