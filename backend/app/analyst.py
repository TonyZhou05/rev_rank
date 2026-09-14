"""
NHTSA Safety Data Analyst

Provides free NHTSA API helpers for recalls, complaints, and safety ratings.
Uses in-memory caching to minimize API calls. All functions are designed to
work offline with stubbed fixtures for testing.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

import httpx

from .models import (
    NHTSAComplaint,
    NHTSARating,
    NHTSARecall,
    NHTSASafetyData,
)


# =============================================================================
# Cache Configuration
# =============================================================================

_cache: dict[str, tuple[datetime, any]] = {}
CACHE_TTL_HOURS = 24


def _cache_key(prefix: str, *args) -> str:
    """Generate a cache key from prefix and arguments."""
    data = f"{prefix}:{':'.join(str(a) for a in args)}"
    return hashlib.md5(data.encode()).hexdigest()


def _get_cached(key: str) -> Optional[any]:
    """Get a value from cache if not expired."""
    if key in _cache:
        timestamp, value = _cache[key]
        if datetime.now() - timestamp < timedelta(hours=CACHE_TTL_HOURS):
            return value
        del _cache[key]
    return None


def _set_cached(key: str, value: any) -> None:
    """Store a value in cache."""
    _cache[key] = (datetime.now(), value)


def clear_cache() -> None:
    """Clear the entire cache (useful for testing)."""
    _cache.clear()


# =============================================================================
# Stubbed Data for Offline Testing
# =============================================================================
# These fixtures are used when OFFLINE_MODE is True or for testing.

OFFLINE_MODE = True  # Set to False for live API calls

STUB_RECALLS: dict[str, list[dict]] = {
    "2020:Toyota:Camry": [
        {
            "campaign_number": "20V123",
            "component": "FUEL SYSTEM",
            "summary": "Fuel pump may fail causing engine stall",
            "consequence": "Engine stall increases crash risk",
            "remedy": "Dealers will replace fuel pump",
            "report_date": "2020-03-15",
        }
    ],
    "2019:Honda:Accord": [
        {
            "campaign_number": "19V456",
            "component": "AIR BAGS",
            "summary": "Passenger airbag may not deploy correctly",
            "consequence": "Increased risk of injury in crash",
            "remedy": "Dealers will update airbag software",
            "report_date": "2019-08-22",
        }
    ],
}

STUB_COMPLAINTS: dict[str, list[dict]] = {
    "2020:Toyota:Camry": [
        {
            "odi_number": "11234567",
            "component": "ENGINE",
            "summary": "Engine hesitation during acceleration",
            "crash": False,
            "fire": False,
            "injuries": 0,
            "deaths": 0,
            "date_filed": "2020-06-15",
        }
    ],
    "2019:Honda:Accord": [
        {
            "odi_number": "11234568",
            "component": "BRAKES",
            "summary": "Brake pedal feels soft at low speeds",
            "crash": False,
            "fire": False,
            "injuries": 0,
            "deaths": 0,
            "date_filed": "2019-11-20",
        }
    ],
}

STUB_RATINGS: dict[str, dict] = {
    "2020:Toyota:Camry": {
        "overall_rating": 5,
        "frontal_crash": 5,
        "side_crash": 5,
        "rollover": 4,
    },
    "2019:Honda:Accord": {
        "overall_rating": 5,
        "frontal_crash": 5,
        "side_crash": 5,
        "rollover": 4,
    },
}


# =============================================================================
# NHTSA API Helpers
# =============================================================================

NHTSA_BASE_URL = "https://api.nhtsa.gov"


async def get_recalls(
    year: int,
    make: str,
    model: str,
    *,
    use_cache: bool = True,
) -> list[NHTSARecall]:
    """
    Fetch NHTSA recalls for a model-year combination.
    
    Uses the free NHTSA Recalls API. Results are cached.
    In OFFLINE_MODE, returns stubbed fixture data.
    """
    cache_key = _cache_key("recalls", year, make, model)
    
    if use_cache:
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached
    
    # Offline mode: return stub data
    if OFFLINE_MODE:
        stub_key = f"{year}:{make}:{model}"
        stub_data = STUB_RECALLS.get(stub_key, [])
        recalls = [NHTSARecall(**r) for r in stub_data]
        _set_cached(cache_key, recalls)
        return recalls
    
    # Live API call (only when OFFLINE_MODE is False)
    url = f"{NHTSA_BASE_URL}/recalls/recallsByVehicle"
    params = {"make": make, "model": model, "modelYear": year}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            recalls = []
            for r in data.get("results", []):
                recalls.append(NHTSARecall(
                    campaign_number=r.get("NHTSACampaignNumber", ""),
                    component=r.get("Component", ""),
                    summary=r.get("Summary", ""),
                    consequence=r.get("Consequence"),
                    remedy=r.get("Remedy"),
                    report_date=r.get("ReportReceivedDate"),
                ))
            
            _set_cached(cache_key, recalls)
            return recalls
    except Exception:
        return []


async def get_complaints(
    year: int,
    make: str,
    model: str,
    *,
    use_cache: bool = True,
) -> list[NHTSAComplaint]:
    """
    Fetch NHTSA complaints for a model-year combination.
    
    Uses the free NHTSA Complaints API. Results are cached.
    In OFFLINE_MODE, returns stubbed fixture data.
    """
    cache_key = _cache_key("complaints", year, make, model)
    
    if use_cache:
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached
    
    # Offline mode: return stub data
    if OFFLINE_MODE:
        stub_key = f"{year}:{make}:{model}"
        stub_data = STUB_COMPLAINTS.get(stub_key, [])
        complaints = [NHTSAComplaint(**c) for c in stub_data]
        _set_cached(cache_key, complaints)
        return complaints
    
    # Live API call (only when OFFLINE_MODE is False)
    url = f"{NHTSA_BASE_URL}/complaints/complaintsByVehicle"
    params = {"make": make, "model": model, "modelYear": year}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            complaints = []
            for c in data.get("results", []):
                complaints.append(NHTSAComplaint(
                    odi_number=str(c.get("odiNumber", "")),
                    component=c.get("components", ""),
                    summary=c.get("summary", ""),
                    crash=c.get("crash", "N") == "Y",
                    fire=c.get("fire", "N") == "Y",
                    injuries=int(c.get("numberOfInjuries", 0)),
                    deaths=int(c.get("numberOfDeaths", 0)),
                    date_filed=c.get("dateOfIncident"),
                ))
            
            _set_cached(cache_key, complaints)
            return complaints
    except Exception:
        return []


async def get_ratings(
    year: int,
    make: str,
    model: str,
    *,
    use_cache: bool = True,
) -> Optional[NHTSARating]:
    """
    Fetch NHTSA safety ratings for a model-year combination.
    
    Uses the free NHTSA Safety Ratings API. Results are cached.
    In OFFLINE_MODE, returns stubbed fixture data.
    """
    cache_key = _cache_key("ratings", year, make, model)
    
    if use_cache:
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached
    
    # Offline mode: return stub data
    if OFFLINE_MODE:
        stub_key = f"{year}:{make}:{model}"
        stub_data = STUB_RATINGS.get(stub_key)
        if stub_data:
            rating = NHTSARating(**stub_data)
            _set_cached(cache_key, rating)
            return rating
        return None
    
    # Live API call (only when OFFLINE_MODE is False)
    url = f"{NHTSA_BASE_URL}/SafetyRatings/modelyear/{year}/make/{make}/model/{model}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("Results", [])
            if not results:
                return None
            
            r = results[0]
            rating = NHTSARating(
                overall_rating=r.get("OverallRating"),
                frontal_crash=r.get("OverallFrontCrashRating"),
                side_crash=r.get("OverallSideCrashRating"),
                rollover=r.get("RolloverRating"),
            )
            
            _set_cached(cache_key, rating)
            return rating
    except Exception:
        return None


async def get_safety_data(
    year: int,
    make: str,
    model: str,
    *,
    use_cache: bool = True,
) -> NHTSASafetyData:
    """
    Fetch complete NHTSA safety data for a model-year combination.
    
    Aggregates recalls, complaints, and ratings into a single response.
    This is the main entry point for A5 NHTSA integration.
    
    IMPORTANT: Data is scoped to the model-year, NOT the specific VIN.
    The scope_label field communicates this to the frontend.
    """
    recalls = await get_recalls(year, make, model, use_cache=use_cache)
    complaints = await get_complaints(year, make, model, use_cache=use_cache)
    rating = await get_ratings(year, make, model, use_cache=use_cache)
    
    return NHTSASafetyData(
        year=year,
        make=make,
        model=model,
        scope_label="Model-Year Safety Data (not VIN-specific)",
        recalls=recalls,
        recall_count=len(recalls),
        complaints=complaints,
        complaint_count=len(complaints),
        rating=rating,
    )
