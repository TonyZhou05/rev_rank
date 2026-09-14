# RevRank

Vehicle comparison and analysis API built with FastAPI.

## Features

- **VIN Recovery**: Recover vehicle data from multiple sources with fallback
- **Vehicle Comparison**: Compare multiple vehicles with detailed metrics
- **NHTSA Integration**: Free safety data (recalls, complaints, ratings)
- **Offline-First**: All tests run with stubbed data, no live API calls

## Quick Start

```bash
# Install dependencies
cd backend
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Start server
uvicorn app.main:app --reload
```

## API Documentation

See [docs/API_CONTRACT.md](docs/API_CONTRACT.md) for the complete wire model documentation.

### Key Endpoints

- `POST /api/v1/vin/recover` - Recover vehicle data for a VIN
- `POST /api/v1/compare` - Compare multiple vehicle candidates
- `GET /api/v1/status/recovery` - Get valid recovery status values

## Project Structure

```
backend/
├── app/
│   ├── main.py          # FastAPI application
│   ├── models.py        # Pydantic models
│   ├── analyst.py       # NHTSA helpers
│   ├── comparison.py    # Comparison logic
│   └── recovery.py      # VIN recovery
├── tests/               # Stubbed tests
docs/
├── API_CONTRACT.md      # Wire model documentation
```

## Development Guidelines

See [AGENTS.md](AGENTS.md) for development constraints and guidelines.

### Key Constraints

- Default offline mode - no live API calls during testing
- Never log or commit API keys
- Do not invent facts - only report actual data
- Keep credentials server-side

## Recovery Status Values

| Status | Description |
|--------|-------------|
| `recovered` | Full data recovered |
| `identity_only` | Only VIN decode info |
| `identity_conflict` | Conflicting data |
| `not_found` | VIN not found |
| `not_listing` | Not an active listing |
| `failed` | Recovery error |
| `disabled` | Recovery disabled |
| `unavailable` | Source unavailable |

## License

MIT
