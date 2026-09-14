"""Offline stubbed tests for backend UX unlocks.

Tests recovery_status vocabulary, new comparison metrics, NHTSA safety data,
DOM fields, MSRP calculations, and cross_model detection.
"""
import socket
from typing import get_args

import pytest

from backend.app import comparison, vehicle_data
from backend.app.comparison import create_report, fetch_nhtsa_safety
from backend.app.config import Settings
from backend.app.models import (
    Candidate, Evidence, ImportResponse, NHTSASafetyData, Preferences,
    RecoveryStatus
)

SETTINGS = Settings()


def car(title, make, model, year, price=None, mileage=None, **extra):
    c = Candidate(
        id=title.replace(" ", "-").lower(),
        title=title, make=make, model=model, year=year,
        price=price, currency="USD" if price else "UNK",
        mileage=mileage, mileage_unit="mi",
        source_kind="user", **extra
    )
    for field in ("make", "model", "year"):
        if getattr(c, field):
            c.evidence[field] = Evidence(
                value=str(getattr(c, field)),
                source="User-pasted listing text",
                status="extracted"
            )
    if price:
        c.evidence["price"] = Evidence(value=str(price), source="User-pasted", status="extracted")
        c.evidence["currency"] = Evidence(value="USD", source="User-pasted", status="extracted")
    if mileage:
        c.evidence["mileage"] = Evidence(value=str(mileage), source="User-pasted", status="extracted")
        c.evidence["mileage_unit"] = Evidence(value="mi", source="User-pasted", status="extracted")
    return c


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("This offline test must not perform network access")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


class TestRecoveryStatusVocabulary:
    """Test that recovery_status is frozen to the defined vocabulary."""

    def test_recovery_status_type_is_literal(self):
        allowed = get_args(RecoveryStatus)
        assert "recovered" in allowed
        assert "identity_only" in allowed
        assert "identity_conflict" in allowed
        assert "not_found" in allowed
        assert "not_listing" in allowed
        assert "failed" in allowed
        assert "disabled" in allowed
        assert "unavailable" in allowed
        assert len(allowed) == 8

    def test_import_response_accepts_all_statuses(self):
        for status in get_args(RecoveryStatus):
            resp = ImportResponse(
                status="partial",
                candidate=None,
                message="Test",
                recovery_status=status
            )
            assert resp.recovery_status == status

    def test_import_response_accepts_null(self):
        resp = ImportResponse(status="success", candidate=None, message="Test")
        assert resp.recovery_status is None


class TestNewComparisonMetrics:
    """Test Engine, Drivetrain, Body, Fuel metrics in comparison."""

    def test_engine_metric_shows_unknown_when_missing(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [
            car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000),
            car("Car B", "Porsche", "911", 2021, price=100000, mileage=5000)
        ]
        report = create_report(cars, Preferences(), SETTINGS)
        engine_metric = next(m for m in report.metrics if m.label == "Engine")
        assert engine_metric.values == ["Unknown", "Unknown"]

    def test_engine_metric_shows_values_when_present(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [
            car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000, engine="3.0L I6"),
            car("Car B", "Porsche", "911", 2021, price=100000, mileage=5000, engine="3.0L H6")
        ]
        for c in cars:
            c.evidence["engine"] = Evidence(value=c.engine, source="Test", status="extracted")
        report = create_report(cars, Preferences(), SETTINGS)
        engine_metric = next(m for m in report.metrics if m.label == "Engine")
        assert engine_metric.values == ["3.0L I6", "3.0L H6"]

    def test_drivetrain_metric_exists(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [car("A", "BMW", "M2", 2020, price=50000), car("B", "Audi", "RS3", 2020, price=55000)]
        report = create_report(cars, Preferences(), SETTINGS)
        assert any(m.label == "Drivetrain" for m in report.metrics)

    def test_body_metric_exists(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [car("A", "BMW", "M2", 2020, price=50000), car("B", "Audi", "RS3", 2020, price=55000)]
        report = create_report(cars, Preferences(), SETTINGS)
        assert any(m.label == "Body" for m in report.metrics)

    def test_fuel_type_metric_exists(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [car("A", "BMW", "M2", 2020, price=50000), car("B", "Audi", "RS3", 2020, price=55000)]
        report = create_report(cars, Preferences(), SETTINGS)
        assert any(m.label == "Fuel Type" for m in report.metrics)


class TestNHTSASafetyData:
    """Test NHTSA model-year safety data at compare time."""

    def test_nhtsa_safety_data_model_has_scope_label(self):
        data = NHTSASafetyData(year=2020, make="BMW", model="M2")
        assert data.scope == "Model-Year Safety Data (not VIN-specific)"

    def test_fetch_nhtsa_safety_returns_none_on_error(self, monkeypatch):
        monkeypatch.setattr(comparison, "_nhtsa", lambda *a, **k: (_ for _ in ()).throw(Exception("Network error")))
        result = fetch_nhtsa_safety(2020, "BMW", "M2")
        assert result is None

    def test_nhtsa_data_populated_on_report(self, monkeypatch):
        mock_data = NHTSASafetyData(
            year=2020, make="BMW", model="M2",
            recalls_count=3, complaints_count=10,
            overall_rating="5", frontal_rating="4", side_rating="5", rollover_rating="4"
        )
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda y, mk, md: mock_data)
        cars = [car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000)]
        cars.append(car("Car B", "Audi", "RS3", 2021, price=55000, mileage=5000))
        report = create_report(cars, Preferences(), SETTINGS)
        assert len(report.nhtsa_data) == 2
        for cid, data in report.nhtsa_data.items():
            assert data.scope == "Model-Year Safety Data (not VIN-specific)"

    def test_candidate_nhtsa_safety_populated(self, monkeypatch):
        mock_data = NHTSASafetyData(year=2020, make="BMW", model="M2", recalls_count=2)
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda y, mk, md: mock_data)
        cars = [car("Car A", "BMW", "M2", 2020, price=50000), car("Car B", "Audi", "RS3", 2020, price=55000)]
        report = create_report(cars, Preferences(), SETTINGS)
        for c in report.candidates:
            assert c.nhtsa_safety is not None
            assert c.nhtsa_safety["scope"] == "Model-Year Safety Data (not VIN-specific)"


class TestDOMFields:
    """Test dom, dom_active, first_seen_at nullable fields."""

    def test_candidate_dom_fields_default_null(self):
        c = Candidate(id="test", title="Test", source_kind="user")
        assert c.dom is None
        assert c.dom_active is None
        assert c.first_seen_at is None

    def test_candidate_dom_fields_accept_values(self):
        c = Candidate(id="test", title="Test", source_kind="user",
                      dom=45, dom_active=30, first_seen_at="2026-08-01")
        assert c.dom == 45
        assert c.dom_active == 30
        assert c.first_seen_at == "2026-08-01"

    def test_inventory_listing_parses_dom_fields(self):
        parsed = vehicle_data.parse_listing({
            "vin": "WBS1H9C50HV123456",
            "vdp_url": "https://www.example.com/car/123",
            "dom": 45,
            "dom_active": 30,
            "first_seen_at_date": "2026-08-01",
            "build": {"year": 2020, "make": "BMW"}
        })
        assert parsed.dom == 45
        assert parsed.dom_active == 30
        assert parsed.first_seen_at == "2026-08-01"

    def test_inventory_listing_handles_missing_dom(self):
        parsed = vehicle_data.parse_listing({
            "vin": "WBS1H9C50HV123456",
            "vdp_url": "https://www.example.com/car/123",
            "build": {"year": 2020, "make": "BMW"}
        })
        assert parsed.dom is None
        assert parsed.dom_active is None
        assert parsed.first_seen_at is None

    def test_inventory_listing_rejects_invalid_dom(self):
        parsed = vehicle_data.parse_listing({
            "vin": "WBS1H9C50HV123456",
            "vdp_url": "https://www.example.com/car/123",
            "dom": -5,
            "dom_active": True,
            "build": {"year": 2020, "make": "BMW"}
        })
        assert parsed.dom is None
        assert parsed.dom_active is None


class TestMSRPFields:
    """Test MSRP and percent_of_msrp functionality."""

    def test_candidate_msrp_default_null(self):
        c = Candidate(id="test", title="Test", source_kind="user")
        assert c.msrp is None

    def test_candidate_msrp_accepts_value(self):
        c = Candidate(id="test", title="Test", source_kind="user", msrp=65000)
        assert c.msrp == 65000

    def test_msrp_in_verified_fields_allowed(self):
        c = Candidate(id="test", title="Test", source_kind="user",
                      msrp=65000, verified_fields=["msrp"])
        assert "msrp" in c.verified_fields

    def test_percent_of_msrp_calculated_when_confirmed(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        c1 = car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000)
        c1.msrp = 65000
        c1.verified_fields = ["msrp"]
        c1.evidence["msrp"] = Evidence(value="65000", source="User", status="user_confirmed")
        c2 = car("Car B", "Audi", "RS3", 2021, price=55000, mileage=5000)
        report = create_report([c1, c2], Preferences(), SETTINGS)
        msrp_metric = next(m for m in report.metrics if "MSRP" in m.label)
        assert "76.9%" in msrp_metric.values[0]
        assert msrp_metric.values[1] == "N/A"

    def test_percent_of_msrp_not_confirmed_shows_message(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        c1 = car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000)
        c1.msrp = 65000
        c2 = car("Car B", "Audi", "RS3", 2021, price=55000, mileage=5000)
        report = create_report([c1, c2], Preferences(), SETTINGS)
        msrp_metric = next(m for m in report.metrics if "MSRP" in m.label)
        assert msrp_metric.values[0] == "MSRP not confirmed"


class TestCrossModel:
    """Test cross_model detection."""

    def test_cross_model_false_when_same_make_model(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [
            car("Car A", "BMW", "M2", 2020, price=50000),
            car("Car B", "BMW", "M2", 2021, price=55000)
        ]
        report = create_report(cars, Preferences(), SETTINGS)
        assert report.cross_model is False

    def test_cross_model_true_when_different_make(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [
            car("Car A", "BMW", "M2", 2020, price=50000),
            car("Car B", "Audi", "RS3", 2021, price=55000)
        ]
        report = create_report(cars, Preferences(), SETTINGS)
        assert report.cross_model is True

    def test_cross_model_true_when_different_model(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [
            car("Car A", "BMW", "M2", 2020, price=50000),
            car("Car B", "BMW", "M4", 2021, price=75000)
        ]
        report = create_report(cars, Preferences(), SETTINGS)
        assert report.cross_model is True

    def test_cross_model_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        cars = [
            car("Car A", "BMW", "M2", 2020, price=50000),
            car("Car B", "bmw", "m2", 2021, price=55000)
        ]
        report = create_report(cars, Preferences(), SETTINGS)
        assert report.cross_model is False
