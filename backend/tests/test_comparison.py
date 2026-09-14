"""
Tests for vehicle comparison functionality.

Verifies:
- Metric rows for Engine, Drivetrain, Body, Fuel Type (Task #3)
- Null values converted to "Unknown"
- NHTSA data attached at compare time (A5)
"""

import pytest

from backend.app.comparison import create_report
from backend.app.models import Candidate


class TestCreateReportMetrics:
    """Tests for comparison report metric generation."""
    
    @pytest.mark.asyncio
    async def test_report_includes_engine_metric(
        self,
        sample_candidate_with_specs,
        sample_candidate_with_nulls,
    ):
        """Report includes Engine metric row (Task #3)."""
        candidates = [
            Candidate(**sample_candidate_with_specs),
            Candidate(**sample_candidate_with_nulls),
        ]
        report = await create_report(candidates, include_nhtsa=False)
        
        metric_names = [m.metric_name for m in report.metrics]
        assert "engine" in metric_names
        
        engine_metric = next(m for m in report.metrics if m.metric_name == "engine")
        assert engine_metric.display_name == "Engine"
        assert engine_metric.values["candidate-1"] == "2.5L I4"
        assert engine_metric.values["candidate-2"] == "Unknown"
    
    @pytest.mark.asyncio
    async def test_report_includes_drivetrain_metric(
        self,
        sample_candidate_with_specs,
        sample_candidate_with_nulls,
    ):
        """Report includes Drivetrain metric row (Task #3)."""
        candidates = [
            Candidate(**sample_candidate_with_specs),
            Candidate(**sample_candidate_with_nulls),
        ]
        report = await create_report(candidates, include_nhtsa=False)
        
        metric_names = [m.metric_name for m in report.metrics]
        assert "drivetrain" in metric_names
        
        drivetrain_metric = next(m for m in report.metrics if m.metric_name == "drivetrain")
        assert drivetrain_metric.display_name == "Drivetrain"
        assert drivetrain_metric.values["candidate-1"] == "FWD"
        assert drivetrain_metric.values["candidate-2"] == "Unknown"
    
    @pytest.mark.asyncio
    async def test_report_includes_body_metric(
        self,
        sample_candidate_with_specs,
        sample_candidate_with_nulls,
    ):
        """Report includes Body metric row (Task #3)."""
        candidates = [
            Candidate(**sample_candidate_with_specs),
            Candidate(**sample_candidate_with_nulls),
        ]
        report = await create_report(candidates, include_nhtsa=False)
        
        metric_names = [m.metric_name for m in report.metrics]
        assert "body" in metric_names
        
        body_metric = next(m for m in report.metrics if m.metric_name == "body")
        assert body_metric.display_name == "Body Style"
        assert body_metric.values["candidate-1"] == "Sedan"
        assert body_metric.values["candidate-2"] == "Unknown"
    
    @pytest.mark.asyncio
    async def test_report_includes_fuel_type_metric(
        self,
        sample_candidate_with_specs,
        sample_candidate_with_nulls,
    ):
        """Report includes Fuel Type metric row (Task #3)."""
        candidates = [
            Candidate(**sample_candidate_with_specs),
            Candidate(**sample_candidate_with_nulls),
        ]
        report = await create_report(candidates, include_nhtsa=False)
        
        metric_names = [m.metric_name for m in report.metrics]
        assert "fuel_type" in metric_names
        
        fuel_metric = next(m for m in report.metrics if m.metric_name == "fuel_type")
        assert fuel_metric.display_name == "Fuel Type"
        assert fuel_metric.values["candidate-1"] == "Gasoline"
        assert fuel_metric.values["candidate-2"] == "Unknown"
    
    @pytest.mark.asyncio
    async def test_metrics_after_transmission(
        self,
        sample_candidate_with_specs,
    ):
        """Engine, Drivetrain, Body, Fuel appear after Transmission (Task #3)."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=False)
        
        metric_names = [m.metric_name for m in report.metrics]
        
        # Find positions
        trans_idx = metric_names.index("transmission")
        engine_idx = metric_names.index("engine")
        drivetrain_idx = metric_names.index("drivetrain")
        body_idx = metric_names.index("body")
        fuel_idx = metric_names.index("fuel_type")
        
        # All should be after transmission
        assert engine_idx > trans_idx
        assert drivetrain_idx > trans_idx
        assert body_idx > trans_idx
        assert fuel_idx > trans_idx
        
        # Should be in order: engine, drivetrain, body, fuel
        assert engine_idx < drivetrain_idx < body_idx < fuel_idx


class TestMixedNullSpecCandidates:
    """Tests for candidates with mixed null/specified values."""
    
    @pytest.mark.asyncio
    async def test_mixed_null_spec_candidates(self, sample_candidate_mixed):
        """Candidates with mixed nulls show 'Unknown' for null values."""
        candidates = [
            Candidate(**sample_candidate_mixed),
            Candidate(
                id="candidate-full",
                year=2020,
                make="Toyota",
                model="Camry",
                engine="2.5L I4",
                drivetrain="FWD",
                body="Sedan",
                fuel_type="Gasoline",
            ),
        ]
        report = await create_report(candidates, include_nhtsa=False)
        
        # Check engine (mixed has value, full has value)
        engine_metric = next(m for m in report.metrics if m.metric_name == "engine")
        assert engine_metric.values["candidate-3"] == "3.5L EcoBoost V6"
        assert engine_metric.values["candidate-full"] == "2.5L I4"
        
        # Check drivetrain (mixed is null, full has value)
        drivetrain_metric = next(m for m in report.metrics if m.metric_name == "drivetrain")
        assert drivetrain_metric.values["candidate-3"] == "Unknown"
        assert drivetrain_metric.values["candidate-full"] == "FWD"
        
        # Check fuel_type (mixed is null, full has value)
        fuel_metric = next(m for m in report.metrics if m.metric_name == "fuel_type")
        assert fuel_metric.values["candidate-3"] == "Unknown"
        assert fuel_metric.values["candidate-full"] == "Gasoline"
    
    @pytest.mark.asyncio
    async def test_all_nulls_show_unknown(self):
        """Candidate with all null specs shows all 'Unknown'."""
        candidate = Candidate(
            id="all-null",
            year=None,
            make=None,
            model=None,
            engine=None,
            drivetrain=None,
            body=None,
            fuel_type=None,
        )
        report = await create_report([candidate, candidate], include_nhtsa=False)
        
        for metric in report.metrics:
            if metric.metric_name in ["engine", "drivetrain", "body", "fuel_type"]:
                assert metric.values["all-null"] == "Unknown"


class TestDOMMetrics:
    """Tests for Days on Market metrics (A6)."""
    
    @pytest.mark.asyncio
    async def test_dom_metric_included(self, sample_candidate_with_specs):
        """Report includes DOM metric."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=False)
        
        metric_names = [m.metric_name for m in report.metrics]
        assert "dom" in metric_names
        
        dom_metric = next(m for m in report.metrics if m.metric_name == "dom")
        assert dom_metric.display_name == "Days on Market"
        assert dom_metric.values["candidate-1"] == "45"
    
    @pytest.mark.asyncio
    async def test_dom_null_shows_unknown(self, sample_candidate_with_nulls):
        """Null DOM shows 'Unknown'."""
        candidate = Candidate(**sample_candidate_with_nulls)
        candidate.dom = None
        report = await create_report([candidate, candidate], include_nhtsa=False)
        
        dom_metric = next(m for m in report.metrics if m.metric_name == "dom")
        assert dom_metric.values["candidate-2"] == "Unknown"


class TestNHTSAIntegration:
    """Tests for NHTSA data at compare time (A5)."""
    
    @pytest.mark.asyncio
    async def test_nhtsa_data_attached(self, sample_candidate_with_specs):
        """NHTSA data attached to candidates with year/make/model (A5)."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=True)
        
        # Check nhtsa_data dict
        assert "candidate-1" in report.nhtsa_data
        safety_data = report.nhtsa_data["candidate-1"]
        assert safety_data is not None
        assert safety_data.year == 2020
        assert safety_data.make == "Toyota"
        assert safety_data.model == "Camry"
    
    @pytest.mark.asyncio
    async def test_nhtsa_scope_label(self, sample_candidate_with_specs):
        """NHTSA data has correct scope label (A5)."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=True)
        
        safety_data = report.nhtsa_data["candidate-1"]
        assert safety_data.scope_label == "Model-Year Safety Data (not VIN-specific)"
    
    @pytest.mark.asyncio
    async def test_nhtsa_data_on_candidate(self, sample_candidate_with_specs):
        """NHTSA data also attached to candidate object (A5)."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=True)
        
        # The candidate in the report should have nhtsa_safety populated
        candidate = report.candidates[0]
        assert candidate.nhtsa_safety is not None
        assert candidate.nhtsa_safety.scope_label == "Model-Year Safety Data (not VIN-specific)"
    
    @pytest.mark.asyncio
    async def test_nhtsa_null_when_missing_identity(self):
        """NHTSA data is null for candidates missing year/make/model."""
        candidate = Candidate(
            id="no-identity",
            year=None,
            make=None,
            model=None,
        )
        report = await create_report([candidate, candidate], include_nhtsa=True)
        
        assert report.nhtsa_data["no-identity"] is None
    
    @pytest.mark.asyncio
    async def test_nhtsa_disabled(self, sample_candidate_with_specs):
        """NHTSA data not fetched when include_nhtsa=False."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=False)
        
        # nhtsa_data should still exist but be empty
        assert report.nhtsa_data == {}
        
        # Candidate should not have NHTSA data attached
        assert report.candidates[0].nhtsa_safety is None


class TestComparisonReportStructure:
    """Tests for overall comparison report structure."""
    
    @pytest.mark.asyncio
    async def test_report_has_id(self, sample_candidate_with_specs):
        """Report has a unique ID."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=False)
        assert report.id is not None
        assert len(report.id) > 0
    
    @pytest.mark.asyncio
    async def test_report_has_timestamp(self, sample_candidate_with_specs):
        """Report has creation timestamp."""
        candidates = [Candidate(**sample_candidate_with_specs)]
        report = await create_report(candidates, include_nhtsa=False)
        assert report.created_at is not None
        assert report.created_at.endswith("Z")
    
    @pytest.mark.asyncio
    async def test_report_includes_all_candidates(
        self,
        sample_candidate_with_specs,
        sample_candidate_with_nulls,
    ):
        """Report includes all input candidates."""
        candidates = [
            Candidate(**sample_candidate_with_specs),
            Candidate(**sample_candidate_with_nulls),
        ]
        report = await create_report(candidates, include_nhtsa=False)
        assert len(report.candidates) == 2
