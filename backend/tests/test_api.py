"""
Tests for FastAPI endpoints.

All tests use stubbed data - no live MarketCheck or Tavily calls.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_health_check(self, client):
        """Root health check returns healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "api_revision" in data
    
    def test_api_health_check(self, client):
        """API health check returns healthy with version info."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["api_revision"] == 1


class TestRecoveryStatusEndpoint:
    """Tests for recovery status vocabulary endpoint."""
    
    def test_get_recovery_statuses(self, client):
        """Returns all valid recovery statuses."""
        response = client.get("/api/v1/status/recovery")
        assert response.status_code == 200
        data = response.json()
        
        expected_statuses = [
            "recovered",
            "identity_only",
            "identity_conflict",
            "not_found",
            "not_listing",
            "failed",
            "disabled",
            "unavailable",
        ]
        assert data["statuses"] == expected_statuses
        assert data["nullable"] is True
    
    def test_badge_suggestions_included(self, client):
        """Returns badge suggestions for frontend."""
        response = client.get("/api/v1/status/recovery")
        data = response.json()
        
        assert "badge_suggestions" in data
        assert data["badge_suggestions"]["recovered"] == "Recovered from other sources"
        assert data["badge_suggestions"]["identity_only"] == "Identity only"


class TestVinRecoverEndpoint:
    """Tests for VIN recovery endpoint."""
    
    def test_recover_vin_success(self, client, sample_vin_recovered):
        """Successful VIN recovery."""
        response = client.post(
            "/api/v1/vin/recover",
            json={"vin": sample_vin_recovered}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["vin"] == sample_vin_recovered
        assert data["recovery_status"] == "recovered"
        assert data["year"] == 2020
        assert data["make"] == "Toyota"
    
    def test_recover_vin_with_dom_fields(self, client, sample_vin_recovered):
        """VIN recovery includes DOM fields when available (A6)."""
        response = client.post(
            "/api/v1/vin/recover",
            json={"vin": sample_vin_recovered}
        )
        data = response.json()
        
        assert data["dom"] == 45
        assert data["dom_active"] == 30
        assert data["first_seen_at"] == "2024-01-15T00:00:00Z"
    
    def test_recover_vin_not_found(self, client, sample_vin_not_found):
        """VIN not found returns appropriate status."""
        response = client.post(
            "/api/v1/vin/recover",
            json={"vin": sample_vin_not_found}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["recovery_status"] == "not_found"
    
    def test_recover_vin_includes_attempts(self, client, sample_vin_recovered):
        """Recovery response includes attempt log."""
        response = client.post(
            "/api/v1/vin/recover",
            json={"vin": sample_vin_recovered}
        )
        data = response.json()
        
        assert "attempts" in data
        assert len(data["attempts"]) > 0


class TestBatchRecoverEndpoint:
    """Tests for batch VIN recovery endpoint."""
    
    def test_recover_batch_success(
        self,
        client,
        sample_vin_recovered,
        sample_vin_not_found,
    ):
        """Batch recovery handles multiple VINs."""
        response = client.post(
            "/api/v1/vin/recover/batch",
            json={"vins": [sample_vin_recovered, sample_vin_not_found]}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert len(data) == 2
        assert data[0]["recovery_status"] == "recovered"
        assert data[1]["recovery_status"] == "not_found"
    
    def test_recover_batch_limit(self, client):
        """Batch recovery enforces limit."""
        vins = [f"VIN{i:015d}X" for i in range(51)]
        response = client.post(
            "/api/v1/vin/recover/batch",
            json={"vins": vins}
        )
        assert response.status_code == 400


class TestCompareEndpoint:
    """Tests for comparison endpoint."""
    
    def test_compare_candidates(self, client, sample_candidate_with_specs):
        """Comparison creates report with metrics."""
        response = client.post(
            "/api/v1/compare",
            json={
                "candidates": [
                    sample_candidate_with_specs,
                    {**sample_candidate_with_specs, "id": "candidate-2"},
                ],
                "include_nhtsa": False,
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "id" in data
        assert "metrics" in data
        assert len(data["candidates"]) == 2
    
    def test_compare_includes_new_metrics(
        self,
        client,
        sample_candidate_with_specs,
    ):
        """Comparison includes Engine, Drivetrain, Body, Fuel metrics (Task #3)."""
        response = client.post(
            "/api/v1/compare",
            json={
                "candidates": [
                    sample_candidate_with_specs,
                    {**sample_candidate_with_specs, "id": "candidate-2"},
                ],
                "include_nhtsa": False,
            }
        )
        data = response.json()
        
        metric_names = [m["metric_name"] for m in data["metrics"]]
        assert "engine" in metric_names
        assert "drivetrain" in metric_names
        assert "body" in metric_names
        assert "fuel_type" in metric_names
    
    def test_compare_with_nhtsa(self, client, sample_candidate_with_specs):
        """Comparison includes NHTSA data when enabled (A5)."""
        response = client.post(
            "/api/v1/compare",
            json={
                "candidates": [
                    sample_candidate_with_specs,
                    {**sample_candidate_with_specs, "id": "candidate-2"},
                ],
                "include_nhtsa": True,
            }
        )
        data = response.json()
        
        assert "nhtsa_data" in data
        assert "candidate-1" in data["nhtsa_data"]
        nhtsa = data["nhtsa_data"]["candidate-1"]
        assert nhtsa["scope_label"] == "Model-Year Safety Data (not VIN-specific)"
    
    def test_compare_minimum_candidates(self, client, sample_candidate_with_specs):
        """Comparison requires at least 2 candidates."""
        response = client.post(
            "/api/v1/compare",
            json={"candidates": [sample_candidate_with_specs]}
        )
        assert response.status_code == 400
    
    def test_compare_maximum_candidates(self, client, sample_candidate_with_specs):
        """Comparison enforces maximum candidates."""
        candidates = [
            {**sample_candidate_with_specs, "id": f"candidate-{i}"}
            for i in range(11)
        ]
        response = client.post(
            "/api/v1/compare",
            json={"candidates": candidates}
        )
        assert response.status_code == 400


class TestCompareVinsEndpoint:
    """Tests for compare-by-VINs endpoint."""
    
    def test_compare_vins(self, client, sample_vin_recovered):
        """Compare VINs recovers data first."""
        response = client.post(
            "/api/v1/compare/vins",
            json={
                "vins": [sample_vin_recovered, sample_vin_recovered],
                "include_nhtsa": True,
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["candidates"]) == 2
        assert data["candidates"][0]["year"] == 2020
    
    def test_compare_vins_minimum(self, client, sample_vin_recovered):
        """Compare VINs requires at least 2 VINs."""
        response = client.post(
            "/api/v1/compare/vins",
            json={"vins": [sample_vin_recovered]}
        )
        assert response.status_code == 400
