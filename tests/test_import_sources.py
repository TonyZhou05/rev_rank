import json

import pytest
from fastapi.testclient import TestClient

from backend.app.fetch import FetchError, Response, redirect_target
from backend.app.extraction import extract
from backend.app.main import app
from backend.app.config import Settings


client = TestClient(app)


DEFAULT_REGISTRY_EXPECTATIONS = {
    "caredge.com": "restricted",
    "cargurus.com": "restricted",
    "autotrader.com": "unsupported",
    "cars.com": "unsupported",
    "carfax.com": "unsupported",
    "truecar.com": "unsupported",
    "classic.com": "unsupported",
}


@pytest.mark.parametrize("domain, expected_status", DEFAULT_REGISTRY_EXPECTATIONS.items())
def test_default_registry_domains_report_policy_via_import(domain, expected_status, monkeypatch):
    """These are policy outcomes, not evidence that a source page was crawled."""
    monkeypatch.setattr('backend.app.main.settings', Settings())
    response = client.post("/api/import", json={"url": f"https://{domain}/representative-listing"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["candidate"] is None
    assert payload["message"]


@pytest.fixture
def representative_jsonld_listing():
    vehicle = {
        "@context": "https://schema.org",
        "@type": "Vehicle",
        "name": "2021 BMW M2 Competition",
        "brand": {"@type": "Brand", "name": "BMW"},
        "model": "M2",
        "vehicleConfiguration": "Competition",
        "vehicleModelDate": "2021",
        "vehicleTransmission": "6-speed manual",
        "vehicleIdentificationNumber": "WBS00000000000001",
        "mileageFromOdometer": {"value": 32500, "unitCode": "SMI"},
        "offers": {
            "@type": "Offer",
            "price": "58900",
            "priceCurrency": "USD",
            "availableAtOrFrom": {
                "address": {"addressLocality": "Austin", "addressRegion": "TX"}
            },
        },
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "Heated seats", "value": True},
            {"@type": "PropertyValue", "name": "M Sport brakes", "value": True},
        ],
    }
    return f'<html><head><script type="application/ld+json">{json.dumps(vehicle)}</script></head></html>'


def test_representative_jsonld_listing_extracts_without_network(representative_jsonld_listing):
    candidate, _ = extract(representative_jsonld_listing)

    assert candidate.source_kind == "user"
    assert candidate.make == "BMW"
    assert candidate.model == "M2"
    assert candidate.trim == "Competition"
    assert candidate.year == 2021
    assert candidate.price == 58900
    assert candidate.currency == "USD"
    assert candidate.mileage == 32500
    assert candidate.mileage_unit == "mi"
    assert candidate.transmission == "6-speed manual"
    assert candidate.location == "Austin, TX"
    assert candidate.features == ["Heated seats", "M Sport brakes"]
    assert candidate.evidence["price_type"].value == "asking"
    assert any("not independent" in warning for warning in candidate.warnings)


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "ftp://caredge.com/listing",
        "http://127.0.0.1/listing",
        "http://10.0.0.8/listing",
        "https://username:password@caredge.com/listing",
    ],
)
def test_invalid_private_and_credential_urls_are_blocked(url):
    response = client.post("/api/import", json={"url": url})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["candidate"] is None


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/private",
        "https://caredge.com/listing",
    ],
)
def test_redirect_targets_that_leave_safe_fetch_scope_are_blocked(location):
    response = Response(status=302, headers={"location": location}, body=b"")

    with pytest.raises(FetchError) as error:
        redirect_target("https://caredge.com/listing", response)

    assert error.value.status == "blocked"
