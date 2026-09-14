"""
Tests for RevRank data models.

Verifies that:
1. RecoveryStatus vocabulary is frozen and correct
2. All models serialize/deserialize correctly
3. DOM fields are nullable
"""

import pytest
from typing import get_args

from backend.app.models import (
    Candidate,
    ComparisonReport,
    ImportResponse,
    MetricComparison,
    NHTSAComplaint,
    NHTSARating,
    NHTSARecall,
    NHTSASafetyData,
    RecoveryAttempt,
    RecoveryStatus,
    RecoveryStatusNullable,
    SourceStatus,
)


class TestRecoveryStatusVocabulary:
    """Tests for the frozen recovery_status vocabulary."""
    
    def test_recovery_status_values(self):
        """Verify the exact set of allowed recovery_status values."""
        expected = {
            "recovered",
            "identity_only",
            "identity_conflict",
            "not_found",
            "not_listing",
            "failed",
            "disabled",
            "unavailable",
        }
        actual = set(get_args(RecoveryStatus))
        assert actual == expected, f"RecoveryStatus mismatch: {actual} != {expected}"
    
    def test_recovery_status_nullable_includes_none(self):
        """Verify RecoveryStatusNullable allows None."""
        # RecoveryStatusNullable is a Union of RecoveryStatus and None
        # We test this by creating an ImportResponse with null status
        response = ImportResponse(vin="TEST123", recovery_status=None)
        assert response.recovery_status is None
    
    def test_all_recovery_statuses_valid_in_import_response(self):
        """Verify all recovery statuses can be used in ImportResponse."""
        statuses = get_args(RecoveryStatus)
        for status in statuses:
            response = ImportResponse(vin="TEST123", recovery_status=status)
            assert response.recovery_status == status


class TestSourceStatusVocabulary:
    """Tests for the source status vocabulary."""
    
    def test_source_status_values(self):
        """Verify the exact set of allowed source status values."""
        expected = {"allowed", "restricted", "unsupported"}
        actual = set(get_args(SourceStatus))
        assert actual == expected


class TestCandidateModel:
    """Tests for the Candidate model including DOM fields (A6)."""
    
    def test_candidate_with_all_fields(self, sample_candidate_with_specs):
        """Verify candidate with all fields including DOM."""
        candidate = Candidate(**sample_candidate_with_specs)
        assert candidate.dom == 45
        assert candidate.dom_active == 30
        assert candidate.first_seen_at == "2024-01-15T00:00:00Z"
    
    def test_candidate_dom_fields_nullable(self):
        """Verify DOM fields can be null (A6)."""
        candidate = Candidate(
            id="test",
            vin="TEST123",
            year=2020,
            make="Toyota",
            model="Camry",
            dom=None,
            dom_active=None,
            first_seen_at=None,
        )
        assert candidate.dom is None
        assert candidate.dom_active is None
        assert candidate.first_seen_at is None
    
    def test_candidate_dom_fields_default_to_none(self):
        """Verify DOM fields default to None when not provided."""
        candidate = Candidate(id="test", vin="TEST123")
        assert candidate.dom is None
        assert candidate.dom_active is None
        assert candidate.first_seen_at is None
    
    def test_candidate_spec_fields_nullable(self):
        """Verify all spec fields can be null."""
        candidate = Candidate(
            id="test",
            engine=None,
            drivetrain=None,
            body=None,
            fuel_type=None,
        )
        assert candidate.engine is None
        assert candidate.drivetrain is None
        assert candidate.body is None
        assert candidate.fuel_type is None


class TestImportResponseModel:
    """Tests for the ImportResponse model."""
    
    def test_import_response_with_recovery(self):
        """Verify ImportResponse with full recovery."""
        response = ImportResponse(
            vin="1HGBH41JXMN109186",
            recovery_status="recovered",
            recovery_source="cache",
            retrieval_method="cache",
            year=2020,
            make="Toyota",
            model="Camry",
            engine="2.5L I4",
            drivetrain="FWD",
            body="Sedan",
            fuel_type="Gasoline",
        )
        assert response.recovery_status == "recovered"
        assert response.engine == "2.5L I4"
    
    def test_import_response_identity_only(self):
        """Verify ImportResponse with identity only."""
        response = ImportResponse(
            vin="WVWZZZ3CZWE123456",
            recovery_status="identity_only",
            recovery_source="nhtsa_decode",
            year=2022,
            make="Volkswagen",
            model="Jetta",
        )
        assert response.recovery_status == "identity_only"
        assert response.engine is None
    
    def test_import_response_dom_fields(self):
        """Verify DOM fields in ImportResponse (A6)."""
        response = ImportResponse(
            vin="TEST123",
            dom=45,
            dom_active=30,
            first_seen_at="2024-01-15T00:00:00Z",
        )
        assert response.dom == 45
        assert response.dom_active == 30
        assert response.first_seen_at == "2024-01-15T00:00:00Z"


class TestNHTSAModels:
    """Tests for NHTSA safety data models."""
    
    def test_nhtsa_recall_model(self):
        """Verify NHTSARecall model."""
        recall = NHTSARecall(
            campaign_number="20V123",
            component="FUEL SYSTEM",
            summary="Test recall",
        )
        assert recall.campaign_number == "20V123"
    
    def test_nhtsa_complaint_model(self):
        """Verify NHTSAComplaint model."""
        complaint = NHTSAComplaint(
            odi_number="11234567",
            component="ENGINE",
            summary="Test complaint",
        )
        assert complaint.crash is False
        assert complaint.injuries == 0
    
    def test_nhtsa_rating_model(self):
        """Verify NHTSARating with bounds."""
        rating = NHTSARating(
            overall_rating=5,
            frontal_crash=4,
            side_crash=5,
            rollover=3,
        )
        assert rating.overall_rating == 5
    
    def test_nhtsa_safety_data_scope_label(self):
        """Verify NHTSA safety data has correct scope label."""
        data = NHTSASafetyData(
            year=2020,
            make="Toyota",
            model="Camry",
        )
        assert data.scope_label == "Model-Year Safety Data (not VIN-specific)"


class TestComparisonModels:
    """Tests for comparison report models."""
    
    def test_metric_comparison_model(self):
        """Verify MetricComparison model."""
        metric = MetricComparison(
            metric_name="engine",
            display_name="Engine",
            values={"c1": "2.5L I4", "c2": "Unknown"},
        )
        assert metric.values["c2"] == "Unknown"
    
    def test_comparison_report_model(self):
        """Verify ComparisonReport model."""
        report = ComparisonReport(
            id="test-report",
            created_at="2024-01-01T00:00:00Z",
            candidates=[],
            metrics=[],
        )
        assert report.nhtsa_data == {}
