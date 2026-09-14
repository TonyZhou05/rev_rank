# RevRank Development Guidelines

## Core Constraints

### Default Offline Mode

All development and testing should operate in offline mode by default. This means:

- **No live API calls** to paid services (MarketCheck, Tavily, etc.) during testing
- Use stubbed fixtures for all external data sources
- NHTSA helpers run in OFFLINE_MODE using stub data
- All tests pass without network connectivity

### API Key Security

- **Never log API keys** in application logs or error messages
- **Never commit API keys** to version control
- All credentials must remain server-side; never expose to client
- Use environment variables for all sensitive configuration

### Data Integrity

- **Do not invent facts** - only report data that exists in sources
- Recall/complaint counts must match actual fixture/API data
- DOM fields are only populated from actual MarketCheck payloads
- VIN-level data is never fabricated

### Credentials Management

- All API credentials stay server-side
- No credentials in client-side code or responses
- Use environment variables: `MARKETCHECK_API_KEY`, `TAVILY_API_KEY`, etc.

## Testing Guidelines

### Stubbed Tests Only

All tests use stubbed data fixtures:

```python
# In analyst.py
OFFLINE_MODE = True  # Always True for development/testing

STUB_RECALLS = {
    "2020:Toyota:Camry": [...]
}
```

### Running Tests

```bash
cd backend
pytest tests/ -v
```

### Test Categories

1. **Model Tests** (`test_models.py`) - Verify Pydantic models
2. **Recovery Tests** (`test_recovery.py`) - VIN recovery logic
3. **Comparison Tests** (`test_comparison.py`) - Report generation
4. **Analyst Tests** (`test_analyst.py`) - NHTSA helpers
5. **API Tests** (`test_api.py`) - FastAPI endpoints

## Development Workflow

### Recovery Status Vocabulary

The `recovery_status` field is frozen to these values:

- `recovered` - Full data available
- `identity_only` - Only VIN decode info
- `identity_conflict` - Conflicting decode data
- `not_found` - VIN not in any source
- `not_listing` - VIN exists but not active listing
- `failed` - Recovery process error
- `disabled` - Recovery disabled
- `unavailable` - Source temporarily unavailable
- `null` - Status not determined

Any new status values require documentation updates and frontend coordination.

### Adding New Data Sources

1. Add source to `RECOVERY_SOURCES` in `recovery.py`
2. Add stub fixtures for offline testing
3. Implement recovery logic
4. Add tests
5. Update API_CONTRACT.md

### Comparison Metrics

Metrics in `comparison.create_report` follow this order:

1. Identity (Year, Make, Model, Trim)
2. Transmission
3. **New metrics**: Engine, Drivetrain, Body, Fuel Type
4. Other specs (Mileage, Price, Colors)
5. DOM

## API Versioning

- Current `api_revision`: 1
- Bump only when wire format changes
- Document all changes in API_CONTRACT.md

## File Structure

```
backend/
├── app/
│   ├── __init__.py      # Version and API revision
│   ├── main.py          # FastAPI app and endpoints
│   ├── models.py        # Pydantic wire models
│   ├── analyst.py       # NHTSA helpers with caching
│   ├── comparison.py    # Comparison report generation
│   └── recovery.py      # VIN recovery logic
├── tests/
│   ├── conftest.py      # Pytest fixtures
│   ├── test_models.py
│   ├── test_recovery.py
│   ├── test_comparison.py
│   ├── test_analyst.py
│   └── test_api.py
docs/
├── API_CONTRACT.md      # Wire model documentation
```
