"""Offline stubbed tests for backend UX unlocks.

Tests recovery_status vocabulary, new comparison metrics, NHTSA safety data,
DOM fields, MSRP calculations, and cross_model detection.
"""
import re
import socket
from typing import get_args

import pytest

from backend.app import comparison, vehicle_data
from backend.app.comparison import create_report, fetch_nhtsa_safety, nhtsa_vehicle_page, nhtsa_ymm_search
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


def recall_row(campaign):
    return {"NHTSACampaignNumber": campaign, "Component": "AIR BAGS", "Summary": "Warning lamp may fail.",
            "Remedy": "Software update.", "ReportReceivedDate": "10/06/2021"}


def complaint_row(odi):
    return {"odiNumber": odi, "components": "ENGINE", "summary": "Stalled while merging.",
            "dateComplaintFiled": "03/14/2021", "crash": False}


def stub_nhtsa(monkeypatch, recalls=None, complaints=None, variants=None, rating=None):
    """Stand in for comparison._nhtsa with the three NHTSA endpoints it calls."""
    def fake(url, params, limit=None):
        if "recallsByVehicle" in url:
            return {"results": recalls or []}
        if "complaintsByVehicle" in url:
            return {"results": complaints or []}
        if "/SafetyRatings/VehicleId/" in url:
            return {"Results": [rating or {}]}
        return {"Results": variants or []}
    monkeypatch.setattr(comparison, "_nhtsa", fake)


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

    def test_fetch_nhtsa_safety_links_recalls_to_campaign_pages(self, monkeypatch):
        stub_nhtsa(monkeypatch, recalls=[recall_row("21V421000"), recall_row("22V103000")])
        data = fetch_nhtsa_safety(2020, "BMW", "M2")
        assert data.recalls_count == 2
        assert [r.campaign_number for r in data.recalls] == ["21V421000", "22V103000"]
        assert data.recalls[0].url == "https://www.nhtsa.gov/recalls?nhtsaId=21V421000"
        assert data.recalls[0].component == "AIR BAGS"
        assert data.recalls[0].report_date == "10/06/2021"

    def test_fetch_nhtsa_safety_skips_recalls_without_campaign_number(self, monkeypatch):
        stub_nhtsa(monkeypatch, recalls=[{"Component": "SEATS", "Summary": "No campaign id."}, recall_row("21V421000")])
        data = fetch_nhtsa_safety(2020, "BMW", "M2")
        assert data.recalls_count == 2
        assert [r.campaign_number for r in data.recalls] == ["21V421000"]

    def test_fetch_nhtsa_safety_lists_complaints_without_inventing_urls(self, monkeypatch):
        stub_nhtsa(monkeypatch, complaints=[complaint_row(11111111), complaint_row(22222222)])
        data = fetch_nhtsa_safety(2020, "BMW", "M2")
        assert data.complaints_count == 2
        assert [r.odi_number for r in data.complaints] == ["11111111", "22222222"]
        assert data.complaints[0].component == "ENGINE"
        assert data.complaints[0].date_filed == "03/14/2021"
        assert all(r.url is None for r in data.complaints)

    def test_fetch_nhtsa_safety_caps_detail_lists_but_keeps_full_counts(self, monkeypatch):
        stub_nhtsa(monkeypatch,
                   recalls=[recall_row(f"21V42100{i}") for i in range(8)],
                   complaints=[complaint_row(10000000 + i) for i in range(9)])
        data = fetch_nhtsa_safety(2020, "BMW", "M2")
        assert (data.recalls_count, data.complaints_count) == (8, 9)
        assert (len(data.recalls), len(data.complaints)) == (5, 5)

    def test_fetch_nhtsa_safety_links_counts_to_trim_page_tabs(self, monkeypatch):
        stub_nhtsa(monkeypatch, variants=[{"VehicleId": 14855, "VehicleDescription": "2020 Toyota Camry 4 DR FWD"}],
                   rating={"OverallRating": "5"})
        data = fetch_nhtsa_safety(2020, "Toyota", "Camry")
        assert data.recalls_url == "https://www.nhtsa.gov/vehicle/2020/TOYOTA/CAMRY/4%252520DR/FWD#recalls"
        assert data.complaints_url == "https://www.nhtsa.gov/vehicle/2020/TOYOTA/CAMRY/4%252520DR/FWD#complaints"
        assert data.overall_rating == "5"

    def test_fetch_nhtsa_safety_falls_back_to_ymm_search_when_model_year_unrated(self, monkeypatch):
        """No variants means no body style or drive type, so the counts use the search landing."""
        stub_nhtsa(monkeypatch, recalls=[recall_row("21V421000")], variants=[])
        data = fetch_nhtsa_safety(2020, "Toyota", "Camry")
        assert data.recalls_url == "https://www.nhtsa.gov/recalls?vymm=2020%20Toyota%20Camry"
        assert data.complaints_url == "https://www.nhtsa.gov/recalls?vymm=2020%20Toyota%20Camry"
        assert data.overall_rating is None

    def test_fetch_nhtsa_safety_never_emits_safety_ratings_vehicle_id_urls(self, monkeypatch):
        """/vehicle/{VehicleId} returns "Page not found", so the numeric id must never be linked."""
        stub_nhtsa(monkeypatch, variants=[{"VehicleId": 19433, "VehicleDescription": "2020 BMW M2 2 DR RWD"}])
        data = fetch_nhtsa_safety(2020, "BMW", "M2")
        for url in (data.recalls_url, data.complaints_url, *(r.url for r in data.recalls)):
            assert "19433" not in (url or "")
            # A bare numeric path segment is the broken shape; /vehicle/{year}/... is the good one.
            assert not re.fullmatch(r"https://www\.nhtsa\.gov/vehicle/\d+/?", url or "")


class TestNHTSAConsumerUrls:
    """URL construction for the pages buyers actually open."""

    def test_trim_deep_link_encodes_body_style_the_way_nhtsa_does(self):
        url = nhtsa_vehicle_page(2020, "Toyota", "Camry", "2020 Toyota Camry 4 DR FWD", "#recalls")
        assert url == "https://www.nhtsa.gov/vehicle/2020/TOYOTA/CAMRY/4%252520DR/FWD#recalls"

    def test_trim_deep_link_keeps_multi_word_trims_in_the_model_segment(self):
        url = nhtsa_vehicle_page(2020, "BMW", "M2", "2020 BMW M2 Competition 2 DR RWD")
        assert url == "https://www.nhtsa.gov/vehicle/2020/BMW/M2%252520COMPETITION/2%252520DR/RWD"

    def test_trim_deep_link_handles_single_word_body_styles(self):
        url = nhtsa_vehicle_page(2020, "Kia", "Telluride", "2020 Kia Telluride SUV AWD", "#complaints")
        assert url == "https://www.nhtsa.gov/vehicle/2020/KIA/TELLURIDE/SUV/AWD#complaints"

    @pytest.mark.parametrize("description", [
        None, "", "2020 Toyota Camry", "2020 Toyota Camry 4 DR", "2020 Toyota Camry FWD",
        "2020 Toyota Camry 4 DR HYBRID",
    ])
    def test_falls_back_to_ymm_search_when_body_or_drive_is_unusable(self, description):
        url = nhtsa_vehicle_page(2020, "Toyota", "Camry", description, "#recalls")
        assert url == "https://www.nhtsa.gov/recalls?vymm=2020%20Toyota%20Camry"

    def test_ymm_search_encodes_spaces_in_the_query(self):
        assert nhtsa_ymm_search(2019, "Mazda", "CX-5") == "https://www.nhtsa.gov/recalls?vymm=2019%20Mazda%20CX-5"

    @pytest.mark.parametrize("year,make,model", [(None, "BMW", "M2"), (2020, "", "M2"), (2020, "BMW", None)])
    def test_returns_none_when_identity_incomplete(self, year, make, model):
        assert nhtsa_vehicle_page(year, make, model, "2020 BMW M2 2 DR RWD") is None
        assert nhtsa_ymm_search(year, make, model) is None

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

    def test_candidate_percent_of_msrp_computed_when_confirmed(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        c1 = car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000)
        c1.msrp = 65000
        c1.verified_fields = ["msrp"]
        c1.evidence["msrp"] = Evidence(value="65000", source="User", status="user_confirmed")
        c2 = car("Car B", "Audi", "RS3", 2021, price=55000, mileage=5000)
        report = create_report([c1, c2], Preferences(), SETTINGS)
        # percent_of_msrp should be (50000/65000)*100 = 76.92...
        assert report.candidates[0].percent_of_msrp is not None
        assert 76.9 <= report.candidates[0].percent_of_msrp <= 77.0
        assert report.candidates[1].percent_of_msrp is None

    def test_candidate_percent_of_msrp_null_when_not_confirmed(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        c1 = car("Car A", "BMW", "M2", 2020, price=50000, mileage=10000)
        c1.msrp = 65000  # Not in verified_fields
        c2 = car("Car B", "Audi", "RS3", 2021, price=55000, mileage=5000)
        report = create_report([c1, c2], Preferences(), SETTINGS)
        assert report.candidates[0].percent_of_msrp is None

    def test_candidate_percent_of_msrp_null_when_currency_unknown(self, monkeypatch):
        monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *a: None)
        c1 = Candidate(
            id="car-a", title="Car A", make="BMW", model="M2", year=2020,
            price=50000, currency="UNK", mileage=10000, mileage_unit="mi",
            source_kind="user", msrp=65000, verified_fields=["msrp"]
        )
        c1.evidence["msrp"] = Evidence(value="65000", source="User", status="user_confirmed")
        c2 = car("Car B", "Audi", "RS3", 2021, price=55000, mileage=5000)
        report = create_report([c1, c2], Preferences(), SETTINGS)
        assert report.candidates[0].percent_of_msrp is None

    def test_candidate_percent_of_msrp_default_null(self):
        c = Candidate(id="test", title="Test", source_kind="user")
        assert c.percent_of_msrp is None


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
