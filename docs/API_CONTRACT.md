# RevRank API Contract

This document defines the wire model for the RevRank API. Frontend and Backend teams should use this as the source of truth for data contracts.

**API Revision:** 1

## Recovery Status Vocabulary (Frozen)

The `recovery_status` field in `ImportResponse` is restricted to the following literal values:

| Status | Description | Suggested Frontend Badge |
|--------|-------------|--------------------------|
| `recovered` | Full vehicle data recovered from sources | "Recovered from other sources" |
| `identity_only` | Only VIN decode info (year/make/model) available | "Identity only" |
| `identity_conflict` | VIN decode returned conflicting information | "Identity conflict" |
| `not_found` | VIN not found in any source | "Not found" |
| `not_listing` | VIN exists but is not an active listing | "Not a listing" |
| `failed` | Recovery process encountered an error | "Recovery failed" |
| `disabled` | Recovery is disabled for this source/context | "Recovery disabled" |
| `unavailable` | Source temporarily unavailable | "Source unavailable" |
| `null` | Status not yet determined | — |

**Note:** Frontend owns final copy of badge labels. The suggestions above are for reference only.

## Source Status Vocabulary

The `status` field in `RecoveryAttempt` uses these values:

| Status | Description |
|--------|-------------|
| `allowed` | Source is allowed and licensed for use |
| `restricted` | Source has usage restrictions |
| `unsupported` | Source is not supported |

**Important:** Local allowlist ≠ reuse license. A source being in the allowlist does not imply it is licensed for all use cases.

## Wire Models

### ImportResponse

Response from VIN import/recovery operations.

```json
{
  "vin": "string",
  "recovery_status": "recovered|identity_only|identity_conflict|not_found|not_listing|failed|disabled|unavailable|null",
  "recovery_source": "string|null",
  "retrieval_method": "cache|api|decode|null",
  "attempts": [
    {
      "source": "string",
      "status": "allowed|restricted|unsupported",
      "timestamp": "ISO8601",
      "success": "boolean",
      "message": "string|null"
    }
  ],
  "year": "int|null",
  "make": "string|null",
  "model": "string|null",
  "trim": "string|null",
  "engine": "string|null",
  "drivetrain": "string|null",
  "body": "string|null",
  "fuel_type": "string|null",
  "transmission": "string|null",
  "exterior_color": "string|null",
  "interior_color": "string|null",
  "mileage": "int|null",
  "price": "int|null",
  "dom": "int|null",
  "dom_active": "int|null",
  "first_seen_at": "ISO8601|null",
  "observations": ["string"],
  "conflicts": ["string"],
  "ai_analysis": "string|null",
  "api_revision": "int",
  "usage": "object|null",
  "licensed": "boolean",
  "search_enabled": "boolean",
  "vin_decode_enabled": "boolean"
}
```

### Candidate

A vehicle candidate for comparison.

```json
{
  "id": "string",
  "vin": "string|null",
  "year": "int|null",
  "make": "string|null",
  "model": "string|null",
  "trim": "string|null",
  "engine": "string|null",
  "drivetrain": "string|null",
  "body": "string|null",
  "fuel_type": "string|null",
  "transmission": "string|null",
  "exterior_color": "string|null",
  "interior_color": "string|null",
  "mileage": "int|null",
  "price": "int|null",
  "dealer_name": "string|null",
  "listing_url": "string|null",
  "dom": "int|null",
  "dom_active": "int|null",
  "first_seen_at": "ISO8601|null",
  "observations": ["string"],
  "conflicts": ["string"],
  "nhtsa_safety": "NHTSASafetyData|null"
}
```

### DOM Fields (Days on Market)

The following fields are populated **ONLY** from MarketCheck payload already fetched during licensed recovery:

- `dom`: Total days on market (int|null)
- `dom_active`: Days as active listing (int|null)
- `first_seen_at`: ISO8601 timestamp when listing was first seen (string|null)

**Important:** These values are NEVER invented. If MarketCheck data is not available, these fields will be `null`. No additional paid API calls are made to populate these fields.

### NHTSASafetyData

Aggregated NHTSA safety data for a model-year combination.

```json
{
  "year": "int",
  "make": "string",
  "model": "string",
  "scope_label": "Model-Year Safety Data (not VIN-specific)",
  "recalls": [
    {
      "campaign_number": "string",
      "component": "string",
      "summary": "string",
      "consequence": "string|null",
      "remedy": "string|null",
      "report_date": "string|null"
    }
  ],
  "recall_count": "int",
  "complaints": [
    {
      "odi_number": "string",
      "component": "string",
      "summary": "string",
      "crash": "boolean",
      "fire": "boolean",
      "injuries": "int",
      "deaths": "int",
      "date_filed": "string|null"
    }
  ],
  "complaint_count": "int",
  "rating": {
    "overall_rating": "int|null (1-5)",
    "frontal_crash": "int|null (1-5)",
    "side_crash": "int|null (1-5)",
    "rollover": "int|null (1-5)"
  }
}
```

**IMPORTANT:** NHTSA data is scoped to the **model-year**, NOT the specific VIN. The `scope_label` field is always `"Model-Year Safety Data (not VIN-specific)"`. Frontend should display this label clearly to users.

VIN-level recall lookup is OUT OF SCOPE for this implementation.

### ComparisonReport

Full comparison report for multiple candidates.

```json
{
  "id": "string (UUID)",
  "created_at": "ISO8601",
  "candidates": ["Candidate"],
  "metrics": [
    {
      "metric_name": "string",
      "display_name": "string",
      "values": {
        "candidate_id": "string|'Unknown'"
      }
    }
  ],
  "summary": "string|null",
  "nhtsa_data": {
    "candidate_id": "NHTSASafetyData|null"
  }
}
```

## Comparison Metrics

The comparison report includes the following metrics in order:

1. **Year** - Vehicle year
2. **Make** - Manufacturer
3. **Model** - Model name
4. **Trim** - Trim level
5. **Transmission** - Transmission type
6. **Engine** - Engine specification (NEW)
7. **Drivetrain** - Drive type (FWD/RWD/AWD/4WD) (NEW)
8. **Body Style** - Body style (Sedan/SUV/etc.) (NEW)
9. **Fuel Type** - Fuel type (Gasoline/Diesel/Electric/etc.) (NEW)
10. **Mileage** - Odometer reading (formatted with commas)
11. **Price** - Listed price (formatted with $ and commas)
12. **Exterior Color** - Exterior color
13. **Interior Color** - Interior color
14. **Days on Market** - DOM value

**Note:** Null values are displayed as `"Unknown"` in metric values.

## API Endpoints

### Health Check

```
GET /health
GET /api/v1/health
```

Returns API health and version information.

### VIN Recovery

```
POST /api/v1/vin/recover
Body: { "vin": "string", "use_cache": true, "use_licensed": true }
Response: ImportResponse
```

```
POST /api/v1/vin/recover/batch
Body: { "vins": ["string"], "use_cache": true, "use_licensed": true }
Response: [ImportResponse]
Limit: 50 VINs per batch
```

### Comparison

```
POST /api/v1/compare
Body: { "candidates": [Candidate], "include_nhtsa": true }
Response: ComparisonReport
Limit: 2-10 candidates
```

```
POST /api/v1/compare/vins
Body: { "vins": ["string"], "use_cache": true, "use_licensed": true, "include_nhtsa": true }
Response: ComparisonReport
Limit: 2-10 VINs
```

### Recovery Status Reference

```
GET /api/v1/status/recovery
Response: { "statuses": [...], "nullable": true, "badge_suggestions": {...} }
```

## Health/Meta Fields

The following fields are included in `ImportResponse` for health and compatibility tracking:

| Field | Type | Description |
|-------|------|-------------|
| `api_revision` | int | API revision for compatibility tracking |
| `usage` | object\|null | Usage/quota information |
| `licensed` | boolean | Whether licensed data sources were used |
| `search_enabled` | boolean | Whether search functionality is enabled |
| `vin_decode_enabled` | boolean | Whether VIN decode is enabled |

## Compatibility Notes

- Wire strings for `recovery_status` are unchanged; no API_REVISION bump required
- Source status uses `unsupported` (not `unreviewed`)
- Frontend should handle all recovery statuses gracefully
- Null values in spec fields indicate data not available (not "missing")
