"""
RevRank FastAPI Backend

Main application entry point with API endpoints for VIN recovery
and vehicle comparison.
"""

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import API_REVISION, __version__
from .comparison import create_report
from .models import (
    Candidate,
    ComparisonReport,
    ImportResponse,
    RecoveryStatus,
)
from .recovery import recover_batch, recover_vin


# =============================================================================
# Application Setup
# =============================================================================

app = FastAPI(
    title="RevRank API",
    description="Vehicle comparison and analysis API",
    version=__version__,
)


# =============================================================================
# Request/Response Models
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    api_revision: int


class RecoverRequest(BaseModel):
    """VIN recovery request."""
    vin: str
    use_cache: bool = True
    use_licensed: bool = True


class BatchRecoverRequest(BaseModel):
    """Batch VIN recovery request."""
    vins: list[str]
    use_cache: bool = True
    use_licensed: bool = True


class CompareRequest(BaseModel):
    """Comparison request."""
    candidates: list[Candidate]
    include_nhtsa: bool = True


class CompareVinsRequest(BaseModel):
    """Compare by VINs request."""
    vins: list[str]
    use_cache: bool = True
    use_licensed: bool = True
    include_nhtsa: bool = True


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=__version__,
        api_revision=API_REVISION,
    )


@app.get("/api/v1/health", response_model=HealthResponse)
async def api_health_check():
    """API health check with version info."""
    return HealthResponse(
        status="healthy",
        version=__version__,
        api_revision=API_REVISION,
    )


@app.post("/api/v1/vin/recover", response_model=ImportResponse)
async def recover_vin_endpoint(request: RecoverRequest):
    """
    Recover vehicle data for a single VIN.
    
    recovery_status will be one of:
    - recovered: Full vehicle data recovered
    - identity_only: Only VIN decode info available
    - identity_conflict: Conflicting decode information
    - not_found: VIN not found
    - not_listing: VIN exists but not an active listing
    - failed: Recovery error
    - disabled: Recovery disabled
    - unavailable: Source unavailable
    - null: Status not yet determined
    
    See docs/API_CONTRACT.md for frontend badge mappings.
    """
    return await recover_vin(
        request.vin,
        use_cache=request.use_cache,
        use_licensed=request.use_licensed,
    )


@app.post("/api/v1/vin/recover/batch", response_model=list[ImportResponse])
async def recover_batch_endpoint(request: BatchRecoverRequest):
    """Recover vehicle data for multiple VINs."""
    if len(request.vins) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 VINs per batch")
    
    return await recover_batch(
        request.vins,
        use_cache=request.use_cache,
        use_licensed=request.use_licensed,
    )


@app.post("/api/v1/compare", response_model=ComparisonReport)
async def compare_candidates(request: CompareRequest):
    """
    Create a comparison report for the provided candidates.
    
    Compares spec metrics including:
    - Year, Make, Model, Trim
    - Transmission, Engine, Drivetrain, Body Style, Fuel Type
    - Mileage, Price, Colors, Days on Market
    
    If include_nhtsa is True, attaches NHTSA safety data (recalls,
    complaints, ratings) for each candidate with year/make/model.
    NOTE: NHTSA data is model-year scoped, NOT VIN-specific.
    """
    if len(request.candidates) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 candidates required for comparison"
        )
    if len(request.candidates) > 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 candidates per comparison"
        )
    
    return await create_report(
        request.candidates,
        include_nhtsa=request.include_nhtsa,
    )


@app.post("/api/v1/compare/vins", response_model=ComparisonReport)
async def compare_vins(request: CompareVinsRequest):
    """
    Create a comparison report by recovering data for VINs first.
    
    This endpoint first recovers data for each VIN, then creates
    a comparison report with the recovered data.
    """
    if len(request.vins) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 VINs required for comparison"
        )
    if len(request.vins) > 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 VINs per comparison"
        )
    
    # Recover data for all VINs
    responses = await recover_batch(
        request.vins,
        use_cache=request.use_cache,
        use_licensed=request.use_licensed,
    )
    
    # Convert to candidates
    candidates = []
    for resp in responses:
        candidates.append(Candidate(
            id=resp.vin,
            vin=resp.vin,
            year=resp.year,
            make=resp.make,
            model=resp.model,
            trim=resp.trim,
            engine=resp.engine,
            drivetrain=resp.drivetrain,
            body=resp.body,
            fuel_type=resp.fuel_type,
            transmission=resp.transmission,
            exterior_color=resp.exterior_color,
            interior_color=resp.interior_color,
            mileage=resp.mileage,
            price=resp.price,
            dom=resp.dom,
            dom_active=resp.dom_active,
            first_seen_at=resp.first_seen_at,
            observations=resp.observations,
            conflicts=resp.conflicts,
        ))
    
    return await create_report(
        candidates,
        include_nhtsa=request.include_nhtsa,
    )


@app.get("/api/v1/status/recovery")
async def get_recovery_statuses():
    """
    Get the list of valid recovery status values.
    
    This endpoint returns the frozen vocabulary for recovery_status
    along with suggested frontend badge labels.
    """
    return {
        "statuses": [
            "recovered",
            "identity_only", 
            "identity_conflict",
            "not_found",
            "not_listing",
            "failed",
            "disabled",
            "unavailable",
        ],
        "nullable": True,
        "badge_suggestions": {
            "recovered": "Recovered from other sources",
            "identity_only": "Identity only",
            "identity_conflict": "Identity conflict",
            "not_found": "Not found",
            "not_listing": "Not a listing",
            "failed": "Recovery failed",
            "disabled": "Recovery disabled",
            "unavailable": "Source unavailable",
        },
        "note": "Frontend owns final copy. These are suggested labels only.",
    }
