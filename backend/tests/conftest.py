"""
Pytest configuration and fixtures for RevRank tests.

All tests use stubbed data - no live API calls to MarketCheck or Tavily.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.analyst import clear_cache


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the NHTSA cache before each test."""
    clear_cache()
    yield
    clear_cache()


# =============================================================================
# Test Fixtures - Stubbed Data
# =============================================================================

@pytest.fixture
def sample_vin_recovered():
    """VIN that has full recovery data in stub cache."""
    return "1HGBH41JXMN109186"


@pytest.fixture
def sample_vin_identity_only():
    """VIN that has only identity data in stub cache."""
    return "WVWZZZ3CZWE123456"


@pytest.fixture
def sample_vin_not_found():
    """VIN that is not in any stub cache."""
    return "NOTFOUND12345678X"


@pytest.fixture
def sample_candidate_with_specs():
    """Candidate with full spec data."""
    return {
        "id": "candidate-1",
        "vin": "1HGBH41JXMN109186",
        "year": 2020,
        "make": "Toyota",
        "model": "Camry",
        "trim": "SE",
        "engine": "2.5L I4",
        "drivetrain": "FWD",
        "body": "Sedan",
        "fuel_type": "Gasoline",
        "transmission": "8-Speed Automatic",
        "mileage": 35000,
        "price": 24500,
        "exterior_color": "Silver",
        "interior_color": "Black",
        "dom": 45,
        "dom_active": 30,
        "first_seen_at": "2024-01-15T00:00:00Z",
    }


@pytest.fixture
def sample_candidate_with_nulls():
    """Candidate with null spec values."""
    return {
        "id": "candidate-2",
        "vin": "5YJSA1E26MF123456",
        "year": 2019,
        "make": "Honda",
        "model": "Accord",
        "trim": None,
        "engine": None,
        "drivetrain": None,
        "body": None,
        "fuel_type": None,
        "transmission": None,
        "mileage": None,
        "price": None,
    }


@pytest.fixture
def sample_candidate_mixed():
    """Candidate with mixed null/present spec values."""
    return {
        "id": "candidate-3",
        "vin": "TESTVIN123456789A",
        "year": 2021,
        "make": "Ford",
        "model": "F-150",
        "trim": "XLT",
        "engine": "3.5L EcoBoost V6",
        "drivetrain": None,  # null
        "body": "Truck",
        "fuel_type": None,  # null
        "transmission": "10-Speed Automatic",
        "mileage": 28000,
        "price": None,  # null
    }
