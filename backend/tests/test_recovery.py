"""
Tests for VIN recovery functionality.

All tests use stubbed data - no live API calls.
Verifies that all recovery paths emit only frozen RecoveryStatus values.
"""

import pytest
from typing import get_args

from backend.app.models import RecoveryStatus
from backend.app.recovery import (
    STUB_CACHE,
    _determine_recovery_status,
    recover_batch,
    recover_vin,
)


class TestRecoveryStatus:
    """Tests for recovery status determination."""
    
    def test_determine_status_recovered(self):
        """Full data returns 'recovered' status."""
        data = {
            "year": 2020,
            "make": "Toyota",
            "model": "Camry",
            "engine": "2.5L I4",
        }
        status = _determine_recovery_status(data, [])
        assert status == "recovered"
    
    def test_determine_status_identity_only(self):
        """Identity only data returns 'identity_only' status."""
        data = {
            "year": 2020,
            "make": "Toyota",
            "model": "Camry",
        }
        status = _determine_recovery_status(data, [])
        assert status == "identity_only"
    
    def test_determine_status_not_found(self):
        """No data returns 'not_found' status."""
        status = _determine_recovery_status(None, [])
        assert status == "not_found"
    
    def test_determine_status_disabled(self):
        """Disabled source returns 'disabled' status."""
        status = _determine_recovery_status(None, [], source_disabled=True)
        assert status == "disabled"
    
    def test_determine_status_unavailable(self):
        """Unavailable source returns 'unavailable' status."""
        status = _determine_recovery_status(None, [], source_unavailable=True)
        assert status == "unavailable"
    
    def test_determine_status_conflict(self):
        """Conflict flag returns 'identity_conflict' status."""
        data = {
            "year": 2020,
            "make": "Toyota",
            "model": "Camry",
            "_has_conflict": True,
        }
        status = _determine_recovery_status(data, [])
        assert status == "identity_conflict"
    
    def test_all_statuses_in_vocabulary(self):
        """Verify all returned statuses are in the frozen vocabulary."""
        valid_statuses = set(get_args(RecoveryStatus))
        
        test_cases = [
            ({"year": 2020, "make": "T", "model": "C", "engine": "2.5L"}, [], {}, "recovered"),
            ({"year": 2020, "make": "T", "model": "C"}, [], {}, "identity_only"),
            (None, [], {}, "not_found"),
            (None, [], {"source_disabled": True}, "disabled"),
            (None, [], {"source_unavailable": True}, "unavailable"),
            ({"year": 2020, "make": "T", "model": "C", "_has_conflict": True}, [], {}, "identity_conflict"),
        ]
        
        for data, attempts, kwargs, expected in test_cases:
            status = _determine_recovery_status(data, attempts, **kwargs)
            assert status in valid_statuses or status is None, f"Invalid status: {status}"
            assert status == expected


class TestRecoverVin:
    """Tests for single VIN recovery."""
    
    @pytest.mark.asyncio
    async def test_recover_vin_from_cache(self, sample_vin_recovered):
        """VIN in stub cache returns 'recovered' status."""
        result = await recover_vin(sample_vin_recovered)
        assert result.recovery_status == "recovered"
        assert result.recovery_source == "cache"
        assert result.year == 2020
        assert result.make == "Toyota"
        assert result.model == "Camry"
        assert result.engine == "2.5L I4"
    
    @pytest.mark.asyncio
    async def test_recover_vin_with_dom_fields(self, sample_vin_recovered):
        """VIN with DOM data includes DOM fields (A6)."""
        result = await recover_vin(sample_vin_recovered)
        assert result.dom == 45
        assert result.dom_active == 30
        assert result.first_seen_at == "2024-01-15T00:00:00Z"
    
    @pytest.mark.asyncio
    async def test_recover_vin_identity_only(self, sample_vin_identity_only):
        """VIN with only identity returns 'identity_only' status."""
        result = await recover_vin(sample_vin_identity_only, use_cache=False)
        assert result.recovery_status == "identity_only"
        assert result.year == 2022
        assert result.make == "Volkswagen"
        assert result.model == "Jetta"
        assert result.engine is None
    
    @pytest.mark.asyncio
    async def test_recover_vin_not_found(self, sample_vin_not_found):
        """Unknown VIN returns 'not_found' status."""
        result = await recover_vin(sample_vin_not_found)
        assert result.recovery_status == "not_found"
        assert result.year is None
        assert result.make is None
    
    @pytest.mark.asyncio
    async def test_recover_vin_no_dom_when_not_available(self):
        """VIN without DOM data has null DOM fields."""
        result = await recover_vin("5YJSA1E26MF123456")
        # This VIN is in cache but has null DOM fields
        assert result.dom is None
        assert result.dom_active is None
        assert result.first_seen_at is None
    
    @pytest.mark.asyncio
    async def test_recover_vin_includes_api_revision(self, sample_vin_recovered):
        """Response includes api_revision field."""
        result = await recover_vin(sample_vin_recovered)
        assert result.api_revision == 1
    
    @pytest.mark.asyncio
    async def test_recover_vin_observations(self, sample_vin_recovered):
        """Recovery includes observations."""
        result = await recover_vin(sample_vin_recovered)
        assert len(result.observations) > 0
    
    @pytest.mark.asyncio
    async def test_recover_vin_attempts_logged(self, sample_vin_recovered):
        """Recovery logs all attempts."""
        result = await recover_vin(sample_vin_recovered)
        assert len(result.attempts) > 0
        assert result.attempts[0].source == "cache"


class TestRecoverBatch:
    """Tests for batch VIN recovery."""
    
    @pytest.mark.asyncio
    async def test_recover_batch_multiple_vins(
        self,
        sample_vin_recovered,
        sample_vin_not_found,
    ):
        """Batch recovery handles multiple VINs."""
        vins = [sample_vin_recovered, sample_vin_not_found]
        results = await recover_batch(vins)
        
        assert len(results) == 2
        assert results[0].recovery_status == "recovered"
        assert results[1].recovery_status == "not_found"
    
    @pytest.mark.asyncio
    async def test_recover_batch_mixed_statuses(self):
        """Batch recovery handles mixed recovery statuses."""
        vins = [
            "1HGBH41JXMN109186",  # recovered
            "WVWZZZ3CZWE123456",  # identity_only (if use_cache=False)
            "NOTFOUND12345678X",  # not_found
        ]
        results = await recover_batch(vins, use_cache=True)
        
        # First and third should have data, second is full from cache
        statuses = [r.recovery_status for r in results]
        assert "recovered" in statuses
        assert "not_found" in statuses


class TestRecoveryStatusVocabularyEnforcement:
    """Tests to ensure only valid statuses are emitted."""
    
    @pytest.mark.asyncio
    async def test_all_recovery_paths_emit_valid_status(self):
        """All recovery scenarios emit only frozen vocabulary values."""
        valid_statuses = set(get_args(RecoveryStatus)) | {None}
        
        # Test various scenarios
        test_vins = [
            "1HGBH41JXMN109186",  # In cache with full data
            "5YJSA1E26MF123456",  # In cache, some nulls
            "WVWZZZ3CZWE123456",  # In cache, identity only
            "NOTFOUND12345678X",  # Not in cache
        ]
        
        for vin in test_vins:
            result = await recover_vin(vin)
            assert result.recovery_status in valid_statuses, \
                f"Invalid status '{result.recovery_status}' for VIN {vin}"
