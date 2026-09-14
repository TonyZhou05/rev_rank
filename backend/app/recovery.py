"""
VIN Recovery Module

Handles vehicle data recovery from multiple sources.
All recovery paths emit only the frozen RecoveryStatus values.
"""

from datetime import datetime, timezone
from typing import Optional

from . import API_REVISION
from .models import (
    ImportResponse,
    RecoveryAttempt,
    RecoveryStatusNullable,
    SourceStatus,
)


# =============================================================================
# Recovery Source Configuration
# =============================================================================
# NOTE: Local allowlist ≠ reuse license. Just because a source is in the
# allowlist doesn't mean it's licensed for all use cases.

RECOVERY_SOURCES = {
    "marketcheck": {
        "status": "allowed",
        "licensed": True,
        "priority": 1,
    },
    "nhtsa_decode": {
        "status": "allowed",
        "licensed": False,  # Free API
        "priority": 2,
    },
    "cache": {
        "status": "allowed",
        "licensed": False,
        "priority": 0,
    },
}


# =============================================================================
# Stubbed/Fixture Data for Offline Testing
# =============================================================================

STUB_CACHE: dict[str, dict] = {
    "1HGBH41JXMN109186": {
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
        # DOM fields from MarketCheck (A6)
        "dom": 45,
        "dom_active": 30,
        "first_seen_at": "2024-01-15T00:00:00Z",
    },
    "5YJSA1E26MF123456": {
        "year": 2019,
        "make": "Honda",
        "model": "Accord",
        "trim": "EX-L",
        "engine": "1.5L Turbo I4",
        "drivetrain": "FWD",
        "body": "Sedan",
        "fuel_type": "Gasoline",
        "transmission": "CVT",
        "mileage": 42000,
        "price": 22000,
        "exterior_color": "Blue",
        "interior_color": "Beige",
        # No DOM data for this one
        "dom": None,
        "dom_active": None,
        "first_seen_at": None,
    },
    # Identity-only example
    "WVWZZZ3CZWE123456": {
        "year": 2022,
        "make": "Volkswagen",
        "model": "Jetta",
        "trim": None,
        # No spec data - identity only
    },
}


# =============================================================================
# Recovery Functions
# =============================================================================

def _create_attempt(
    source: str,
    status: SourceStatus,
    success: bool,
    message: Optional[str] = None,
) -> RecoveryAttempt:
    """Create a recovery attempt record."""
    return RecoveryAttempt(
        source=source,
        status=status,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        success=success,
        message=message,
    )


def _determine_recovery_status(
    data: Optional[dict],
    attempts: list[RecoveryAttempt],
    source_disabled: bool = False,
    source_unavailable: bool = False,
) -> RecoveryStatusNullable:
    """
    Determine the recovery status based on available data and attempts.
    
    Returns ONLY values from the frozen RecoveryStatus vocabulary:
    - recovered: Full data available
    - identity_only: Only VIN decode info (year/make/model)
    - identity_conflict: Conflicting decode information
    - not_found: VIN not found in any source
    - not_listing: VIN exists but not an active listing
    - failed: Recovery process error
    - disabled: Recovery disabled for source/context
    - unavailable: Source temporarily unavailable
    """
    if source_disabled:
        return "disabled"
    
    if source_unavailable:
        return "unavailable"
    
    # Check for any failed attempts
    failed_attempts = [a for a in attempts if not a.success]
    if failed_attempts and not data:
        # Check if it's a "not found" vs actual failure
        for attempt in failed_attempts:
            if attempt.message and "not found" in attempt.message.lower():
                return "not_found"
            if attempt.message and "not listing" in attempt.message.lower():
                return "not_listing"
        return "failed"
    
    if not data:
        return "not_found"
    
    # Check if we have full data or just identity
    has_identity = all([
        data.get("year"),
        data.get("make"),
        data.get("model"),
    ])
    
    has_specs = any([
        data.get("engine"),
        data.get("drivetrain"),
        data.get("body"),
        data.get("fuel_type"),
        data.get("transmission"),
        data.get("mileage"),
        data.get("price"),
    ])
    
    # Check for conflicts
    if data.get("_has_conflict"):
        return "identity_conflict"
    
    if has_identity and has_specs:
        return "recovered"
    elif has_identity:
        return "identity_only"
    else:
        return "not_found"


async def recover_vin(
    vin: str,
    *,
    use_cache: bool = True,
    use_licensed: bool = True,
    disabled_sources: Optional[list[str]] = None,
) -> ImportResponse:
    """
    Attempt to recover vehicle data for a VIN.
    
    Recovery is attempted in priority order:
    1. Cache (if use_cache=True)
    2. Licensed sources like MarketCheck (if use_licensed=True)
    3. Free sources like NHTSA decode
    
    Args:
        vin: The VIN to recover
        use_cache: Whether to check cache first
        use_licensed: Whether to use licensed data sources
        disabled_sources: List of sources to skip
    
    Returns:
        ImportResponse with recovery results and status
    """
    disabled_sources = disabled_sources or []
    attempts: list[RecoveryAttempt] = []
    recovered_data: Optional[dict] = None
    recovery_source: Optional[str] = None
    retrieval_method: Optional[str] = None
    licensed_used = False
    
    # Attempt 1: Check cache
    if use_cache and "cache" not in disabled_sources:
        if vin in STUB_CACHE:
            recovered_data = STUB_CACHE[vin]
            recovery_source = "cache"
            retrieval_method = "cache"
            attempts.append(_create_attempt(
                "cache", "allowed", True, "Data found in cache"
            ))
        else:
            attempts.append(_create_attempt(
                "cache", "allowed", False, "VIN not in cache"
            ))
    
    # Attempt 2: MarketCheck (licensed source) - STUB for offline mode
    if not recovered_data and use_licensed and "marketcheck" not in disabled_sources:
        # In real implementation, this would call MarketCheck API
        # For offline mode, we just record the attempt as unavailable
        attempts.append(_create_attempt(
            "marketcheck",
            "allowed",
            False,
            "MarketCheck API not called (offline mode)",
        ))
    
    # Attempt 3: NHTSA decode (free, identity only)
    if not recovered_data and "nhtsa_decode" not in disabled_sources:
        # Stub NHTSA decode - would return identity only
        # For now, check if it's in our stub cache for identity
        if vin in STUB_CACHE:
            stub = STUB_CACHE[vin]
            if stub.get("year") and stub.get("make") and stub.get("model"):
                recovered_data = {
                    "year": stub["year"],
                    "make": stub["make"],
                    "model": stub["model"],
                    "trim": stub.get("trim"),
                }
                recovery_source = "nhtsa_decode"
                retrieval_method = "decode"
                attempts.append(_create_attempt(
                    "nhtsa_decode", "allowed", True, "VIN decoded successfully"
                ))
        else:
            attempts.append(_create_attempt(
                "nhtsa_decode", "allowed", False, "VIN not found in NHTSA database"
            ))
    
    # Determine recovery status
    recovery_status = _determine_recovery_status(recovered_data, attempts)
    
    # If we got full data from cache (which had MarketCheck data), update flags
    if recovery_source == "cache" and recovered_data:
        full_stub = STUB_CACHE.get(vin, {})
        if full_stub.get("dom") is not None:
            licensed_used = True  # DOM data came from licensed source
    
    # Build observations and conflicts
    observations: list[str] = []
    conflicts: list[str] = []
    
    if recovery_status == "recovered":
        observations.append("Full vehicle data recovered")
    elif recovery_status == "identity_only":
        observations.append("Only identity information available (year/make/model)")
    elif recovery_status == "identity_conflict":
        conflicts.append("VIN decode returned conflicting information")
    
    # Build response
    return ImportResponse(
        vin=vin,
        recovery_status=recovery_status,
        recovery_source=recovery_source,
        retrieval_method=retrieval_method,
        attempts=attempts,
        year=recovered_data.get("year") if recovered_data else None,
        make=recovered_data.get("make") if recovered_data else None,
        model=recovered_data.get("model") if recovered_data else None,
        trim=recovered_data.get("trim") if recovered_data else None,
        engine=recovered_data.get("engine") if recovered_data else None,
        drivetrain=recovered_data.get("drivetrain") if recovered_data else None,
        body=recovered_data.get("body") if recovered_data else None,
        fuel_type=recovered_data.get("fuel_type") if recovered_data else None,
        transmission=recovered_data.get("transmission") if recovered_data else None,
        exterior_color=recovered_data.get("exterior_color") if recovered_data else None,
        interior_color=recovered_data.get("interior_color") if recovered_data else None,
        mileage=recovered_data.get("mileage") if recovered_data else None,
        price=recovered_data.get("price") if recovered_data else None,
        dom=recovered_data.get("dom") if recovered_data else None,
        dom_active=recovered_data.get("dom_active") if recovered_data else None,
        first_seen_at=recovered_data.get("first_seen_at") if recovered_data else None,
        observations=observations,
        conflicts=conflicts,
        api_revision=API_REVISION,
        licensed=licensed_used,
        search_enabled=True,
        vin_decode_enabled=True,
    )


async def recover_batch(
    vins: list[str],
    **kwargs,
) -> list[ImportResponse]:
    """Recover data for multiple VINs."""
    results = []
    for vin in vins:
        result = await recover_vin(vin, **kwargs)
        results.append(result)
    return results
