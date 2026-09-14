"""
RevRank Wire Models

This module defines the canonical Pydantic models for the RevRank API.
All wire formats are defined here and documented in docs/API_CONTRACT.md.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Recovery Status Vocabulary (Frozen)
# =============================================================================
# These are the ONLY valid values for ImportResponse.recovery_status.
# Frontend badge mappings are documented in docs/API_CONTRACT.md.

RecoveryStatus = Literal[
    "recovered",          # Full vehicle data recovered from sources
    "identity_only",      # Only VIN decode info (year/make/model) available
    "identity_conflict",  # VIN decode returned conflicting information
    "not_found",          # VIN not found in any source
    "not_listing",        # VIN exists but is not an active listing
    "failed",             # Recovery process encountered an error
    "disabled",           # Recovery is disabled for this source/context
    "unavailable",        # Source temporarily unavailable
]

# Nullable variant for when status is not yet determined
RecoveryStatusNullable = Literal[
    "recovered",
    "identity_only",
    "identity_conflict",
    "not_found",
    "not_listing",
    "failed",
    "disabled",
    "unavailable",
] | None


# =============================================================================
# Source Status Vocabulary
# =============================================================================
# Status of data sources in the recovery pipeline.

SourceStatus = Literal[
    "allowed",      # Source is allowed and licensed for use
    "restricted",   # Source has usage restrictions
    "unsupported",  # Source is not supported
]


# =============================================================================
# NHTSA Safety Data Models
# =============================================================================

class NHTSARecall(BaseModel):
    """NHTSA recall record."""
    campaign_number: str
    component: str
    summary: str
    consequence: Optional[str] = None
    remedy: Optional[str] = None
    report_date: Optional[str] = None


class NHTSAComplaint(BaseModel):
    """NHTSA complaint record."""
    odi_number: str
    component: str
    summary: str
    crash: bool = False
    fire: bool = False
    injuries: int = 0
    deaths: int = 0
    date_filed: Optional[str] = None


class NHTSARating(BaseModel):
    """NHTSA safety rating."""
    overall_rating: Optional[int] = Field(None, ge=1, le=5)
    frontal_crash: Optional[int] = Field(None, ge=1, le=5)
    side_crash: Optional[int] = Field(None, ge=1, le=5)
    rollover: Optional[int] = Field(None, ge=1, le=5)


class NHTSASafetyData(BaseModel):
    """
    Aggregated NHTSA safety data for a model-year combination.
    
    IMPORTANT: This data is scoped to the model-year, NOT the specific VIN.
    The Frontend expects the label "Model-Year Safety Data (not VIN-specific)".
    """
    year: int
    make: str
    model: str
    scope_label: str = "Model-Year Safety Data (not VIN-specific)"
    recalls: list[NHTSARecall] = Field(default_factory=list)
    recall_count: int = 0
    complaints: list[NHTSAComplaint] = Field(default_factory=list)
    complaint_count: int = 0
    rating: Optional[NHTSARating] = None


# =============================================================================
# Candidate Model (for comparison)
# =============================================================================

class Candidate(BaseModel):
    """
    A vehicle candidate for comparison.
    
    Includes spec fields, observations, and optional DOM (days-on-market) data.
    DOM fields are populated ONLY from MarketCheck payload during licensed
    recovery — no extra paid API calls are made.
    """
    id: str
    vin: Optional[str] = None
    
    # Identity fields (from VIN decode)
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    
    # Spec fields
    engine: Optional[str] = None
    drivetrain: Optional[str] = None
    body: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    mileage: Optional[int] = None
    price: Optional[int] = None
    
    # Listing metadata
    dealer_name: Optional[str] = None
    listing_url: Optional[str] = None
    
    # A6: Nullable DOM (Days on Market) fields
    # Populated ONLY from MarketCheck payload already fetched during
    # licensed recovery. Never invented; null if not available.
    dom: Optional[int] = Field(
        None,
        description="Days on market (total). From MarketCheck payload only."
    )
    dom_active: Optional[int] = Field(
        None,
        description="Days on market (active listing). From MarketCheck payload only."
    )
    first_seen_at: Optional[str] = Field(
        None,
        description="ISO timestamp when listing first seen. From MarketCheck payload only."
    )
    
    # Observations and analysis
    observations: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    
    # NHTSA safety data (A5)
    nhtsa_safety: Optional[NHTSASafetyData] = None


# =============================================================================
# Import/Recovery Response
# =============================================================================

class RecoveryAttempt(BaseModel):
    """Record of a single recovery attempt from a source."""
    source: str
    status: SourceStatus
    timestamp: str
    success: bool
    message: Optional[str] = None


class ImportResponse(BaseModel):
    """
    Response from VIN import/recovery operations.
    
    recovery_status is frozen to the RecoveryStatusNullable vocabulary.
    See docs/API_CONTRACT.md for frontend badge mappings.
    """
    vin: str
    
    # Recovery outcome
    recovery_status: RecoveryStatusNullable = Field(
        None,
        description="Recovery outcome. See RecoveryStatus for valid values."
    )
    recovery_source: Optional[str] = Field(
        None,
        description="Primary source that provided the data (if recovered)."
    )
    retrieval_method: Optional[str] = Field(
        None,
        description="Method used for retrieval: 'cache', 'api', 'decode'."
    )
    
    # Recovery attempts log
    attempts: list[RecoveryAttempt] = Field(default_factory=list)
    
    # Decoded identity
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    
    # Spec fields (populated on full recovery)
    engine: Optional[str] = None
    drivetrain: Optional[str] = None
    body: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    mileage: Optional[int] = None
    price: Optional[int] = None
    
    # DOM fields (A6) - from MarketCheck only
    dom: Optional[int] = None
    dom_active: Optional[int] = None
    first_seen_at: Optional[str] = None
    
    # Analysis
    observations: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    ai_analysis: Optional[str] = Field(
        None,
        description="AI-generated analysis summary (when available)."
    )
    
    # Health/meta
    api_revision: int = Field(
        default=1,
        description="API revision for compatibility tracking."
    )
    usage: Optional[dict] = Field(
        None,
        description="Usage/quota information."
    )
    licensed: bool = Field(
        False,
        description="Whether licensed data sources were used."
    )
    search_enabled: bool = Field(
        True,
        description="Whether search functionality is enabled."
    )
    vin_decode_enabled: bool = Field(
        True,
        description="Whether VIN decode is enabled."
    )


# =============================================================================
# Comparison Report Models
# =============================================================================

class MetricComparison(BaseModel):
    """A single metric comparison across candidates."""
    metric_name: str
    display_name: str
    values: dict[str, Optional[str]]  # candidate_id -> value or "Unknown"


class ComparisonReport(BaseModel):
    """
    Full comparison report for multiple candidates.
    
    Includes spec comparisons, NHTSA safety data, and analysis.
    """
    id: str
    created_at: str
    candidates: list[Candidate]
    metrics: list[MetricComparison]
    summary: Optional[str] = None
    
    # NHTSA data aggregated for all candidates
    nhtsa_data: dict[str, Optional[NHTSASafetyData]] = Field(
        default_factory=dict,
        description="NHTSA safety data keyed by candidate ID."
    )
