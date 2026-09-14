"""
Vehicle Comparison Module

Creates comparison reports for multiple vehicle candidates.
Includes spec metrics, NHTSA safety data, and analysis.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from .analyst import get_safety_data
from .models import (
    Candidate,
    ComparisonReport,
    MetricComparison,
    NHTSASafetyData,
)


def _null_to_unknown(value: Optional[str]) -> str:
    """Convert null/None values to 'Unknown' for display."""
    return value if value is not None else "Unknown"


async def create_report(
    candidates: list[Candidate],
    *,
    include_nhtsa: bool = True,
) -> ComparisonReport:
    """
    Create a comparison report for the given candidates.
    
    Generates metric comparisons for all spec fields including:
    - Year, Make, Model, Trim
    - Transmission, Engine, Drivetrain, Body, Fuel Type
    - Mileage, Price, Colors
    
    If include_nhtsa is True (default), fetches NHTSA safety data
    for each candidate with year/make/model information.
    
    Args:
        candidates: List of Candidate objects to compare
        include_nhtsa: Whether to include NHTSA safety data (A5)
    
    Returns:
        ComparisonReport with metrics, candidates, and optional NHTSA data
    """
    report_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Build candidate ID -> value mappings for each metric
    metrics: list[MetricComparison] = []
    
    # Identity metrics
    metrics.append(MetricComparison(
        metric_name="year",
        display_name="Year",
        values={c.id: str(c.year) if c.year else "Unknown" for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="make",
        display_name="Make",
        values={c.id: _null_to_unknown(c.make) for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="model",
        display_name="Model",
        values={c.id: _null_to_unknown(c.model) for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="trim",
        display_name="Trim",
        values={c.id: _null_to_unknown(c.trim) for c in candidates},
    ))
    
    # Transmission (existing metric)
    metrics.append(MetricComparison(
        metric_name="transmission",
        display_name="Transmission",
        values={c.id: _null_to_unknown(c.transmission) for c in candidates},
    ))
    
    # === NEW METRICS (Task #3) ===
    # Added after Transmission: Engine, Drivetrain, Body, Fuel Type
    
    metrics.append(MetricComparison(
        metric_name="engine",
        display_name="Engine",
        values={c.id: _null_to_unknown(c.engine) for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="drivetrain",
        display_name="Drivetrain",
        values={c.id: _null_to_unknown(c.drivetrain) for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="body",
        display_name="Body Style",
        values={c.id: _null_to_unknown(c.body) for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="fuel_type",
        display_name="Fuel Type",
        values={c.id: _null_to_unknown(c.fuel_type) for c in candidates},
    ))
    
    # Other spec metrics
    metrics.append(MetricComparison(
        metric_name="mileage",
        display_name="Mileage",
        values={
            c.id: f"{c.mileage:,}" if c.mileage is not None else "Unknown"
            for c in candidates
        },
    ))
    
    metrics.append(MetricComparison(
        metric_name="price",
        display_name="Price",
        values={
            c.id: f"${c.price:,}" if c.price is not None else "Unknown"
            for c in candidates
        },
    ))
    
    metrics.append(MetricComparison(
        metric_name="exterior_color",
        display_name="Exterior Color",
        values={c.id: _null_to_unknown(c.exterior_color) for c in candidates},
    ))
    
    metrics.append(MetricComparison(
        metric_name="interior_color",
        display_name="Interior Color",
        values={c.id: _null_to_unknown(c.interior_color) for c in candidates},
    ))
    
    # DOM metrics (A6)
    metrics.append(MetricComparison(
        metric_name="dom",
        display_name="Days on Market",
        values={
            c.id: str(c.dom) if c.dom is not None else "Unknown"
            for c in candidates
        },
    ))
    
    # A5: Fetch NHTSA safety data for each candidate
    nhtsa_data: dict[str, Optional[NHTSASafetyData]] = {}
    updated_candidates: list[Candidate] = []
    
    for candidate in candidates:
        if include_nhtsa:
            if candidate.year and candidate.make and candidate.model:
                safety_data = await get_safety_data(
                    candidate.year,
                    candidate.make,
                    candidate.model,
                )
                nhtsa_data[candidate.id] = safety_data
                
                # Attach NHTSA data to the candidate
                updated_candidate = candidate.model_copy(
                    update={"nhtsa_safety": safety_data}
                )
                updated_candidates.append(updated_candidate)
            else:
                nhtsa_data[candidate.id] = None
                updated_candidates.append(candidate)
        else:
            # When NHTSA is disabled, don't populate nhtsa_data
            updated_candidates.append(candidate)
    
    return ComparisonReport(
        id=report_id,
        created_at=created_at,
        candidates=updated_candidates,
        metrics=metrics,
        nhtsa_data=nhtsa_data,
    )


async def create_report_from_vins(
    vins: list[str],
    candidate_data: dict[str, dict],
) -> ComparisonReport:
    """
    Create a comparison report from VINs and associated data.
    
    This is a convenience wrapper that constructs Candidate objects
    from raw data dictionaries.
    
    Args:
        vins: List of VINs to compare
        candidate_data: Dict mapping VIN -> candidate data dict
    
    Returns:
        ComparisonReport with comparison results
    """
    candidates = []
    for vin in vins:
        data = candidate_data.get(vin, {})
        candidates.append(Candidate(
            id=vin,
            vin=vin,
            **data,
        ))
    
    return await create_report(candidates)
