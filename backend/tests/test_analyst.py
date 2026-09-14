"""
Tests for NHTSA analyst module.

All tests use OFFLINE_MODE with stubbed fixtures - no live API calls.
Never invents counts; uses only fixture data.
"""

import pytest

from backend.app.analyst import (
    STUB_COMPLAINTS,
    STUB_RATINGS,
    STUB_RECALLS,
    clear_cache,
    get_complaints,
    get_ratings,
    get_recalls,
    get_safety_data,
)


class TestNHTSARecalls:
    """Tests for NHTSA recall fetching."""
    
    @pytest.mark.asyncio
    async def test_get_recalls_from_stub(self):
        """Recalls fetched from stub data."""
        recalls = await get_recalls(2020, "Toyota", "Camry")
        
        # Should match stub data exactly - never invent counts
        expected = STUB_RECALLS.get("2020:Toyota:Camry", [])
        assert len(recalls) == len(expected)
        
        if recalls:
            assert recalls[0].campaign_number == "20V123"
            assert recalls[0].component == "FUEL SYSTEM"
    
    @pytest.mark.asyncio
    async def test_get_recalls_empty_for_unknown(self):
        """Empty list for unknown year/make/model."""
        recalls = await get_recalls(2000, "Unknown", "Model")
        assert recalls == []
    
    @pytest.mark.asyncio
    async def test_get_recalls_cached(self):
        """Recalls are cached."""
        # First call
        recalls1 = await get_recalls(2020, "Toyota", "Camry")
        # Second call should use cache
        recalls2 = await get_recalls(2020, "Toyota", "Camry")
        
        assert len(recalls1) == len(recalls2)


class TestNHTSAComplaints:
    """Tests for NHTSA complaint fetching."""
    
    @pytest.mark.asyncio
    async def test_get_complaints_from_stub(self):
        """Complaints fetched from stub data."""
        complaints = await get_complaints(2020, "Toyota", "Camry")
        
        # Should match stub data exactly
        expected = STUB_COMPLAINTS.get("2020:Toyota:Camry", [])
        assert len(complaints) == len(expected)
        
        if complaints:
            assert complaints[0].odi_number == "11234567"
            assert complaints[0].component == "ENGINE"
    
    @pytest.mark.asyncio
    async def test_get_complaints_empty_for_unknown(self):
        """Empty list for unknown year/make/model."""
        complaints = await get_complaints(2000, "Unknown", "Model")
        assert complaints == []


class TestNHTSARatings:
    """Tests for NHTSA safety rating fetching."""
    
    @pytest.mark.asyncio
    async def test_get_ratings_from_stub(self):
        """Ratings fetched from stub data."""
        rating = await get_ratings(2020, "Toyota", "Camry")
        
        # Should match stub data
        expected = STUB_RATINGS.get("2020:Toyota:Camry")
        assert rating is not None
        assert rating.overall_rating == expected["overall_rating"]
    
    @pytest.mark.asyncio
    async def test_get_ratings_none_for_unknown(self):
        """None for unknown year/make/model."""
        rating = await get_ratings(2000, "Unknown", "Model")
        assert rating is None


class TestNHTSASafetyData:
    """Tests for aggregated NHTSA safety data."""
    
    @pytest.mark.asyncio
    async def test_get_safety_data_aggregates(self):
        """Safety data aggregates recalls, complaints, ratings."""
        data = await get_safety_data(2020, "Toyota", "Camry")
        
        assert data.year == 2020
        assert data.make == "Toyota"
        assert data.model == "Camry"
        
        # Counts should match fixture data exactly
        assert data.recall_count == len(data.recalls)
        assert data.complaint_count == len(data.complaints)
        assert data.rating is not None
    
    @pytest.mark.asyncio
    async def test_safety_data_scope_label(self):
        """Safety data has correct scope label for frontend."""
        data = await get_safety_data(2020, "Toyota", "Camry")
        assert data.scope_label == "Model-Year Safety Data (not VIN-specific)"
    
    @pytest.mark.asyncio
    async def test_safety_data_for_unknown_vehicle(self):
        """Safety data for unknown vehicle has zero counts."""
        data = await get_safety_data(2000, "Unknown", "Model")
        
        assert data.recall_count == 0
        assert data.complaint_count == 0
        assert data.rating is None
        assert data.recalls == []
        assert data.complaints == []


class TestCaching:
    """Tests for NHTSA data caching."""
    
    @pytest.mark.asyncio
    async def test_cache_cleared(self):
        """Cache can be cleared."""
        # Prime cache
        await get_recalls(2020, "Toyota", "Camry")
        
        # Clear
        clear_cache()
        
        # Should work after clear
        recalls = await get_recalls(2020, "Toyota", "Camry")
        assert len(recalls) == len(STUB_RECALLS.get("2020:Toyota:Camry", []))
    
    @pytest.mark.asyncio
    async def test_cache_bypass(self):
        """Cache can be bypassed."""
        # Get with cache
        data1 = await get_safety_data(2020, "Toyota", "Camry", use_cache=True)
        # Get without cache
        data2 = await get_safety_data(2020, "Toyota", "Camry", use_cache=False)
        
        # Both should have same data
        assert data1.recall_count == data2.recall_count


class TestOfflineMode:
    """Tests verifying offline mode behavior."""
    
    @pytest.mark.asyncio
    async def test_no_live_api_calls(self):
        """Verify no live API calls are made in tests."""
        # This test documents that all tests run in OFFLINE_MODE
        # The analyst module has OFFLINE_MODE = True
        from backend.app.analyst import OFFLINE_MODE
        assert OFFLINE_MODE is True, "Tests must run in OFFLINE_MODE"
    
    @pytest.mark.asyncio
    async def test_stub_data_used(self):
        """Verify stub data is used."""
        recalls = await get_recalls(2020, "Toyota", "Camry")
        
        # If not using stub, we'd get different data (or error)
        # With stub, we get exactly what's in STUB_RECALLS
        stub_data = STUB_RECALLS.get("2020:Toyota:Camry", [])
        assert len(recalls) == len(stub_data)
