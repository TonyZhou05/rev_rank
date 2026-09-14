# Deploy RevRank on Render

Quick deployment for a friend try-out. This runs RevRank as a single web service
using the included Dockerfile.

## Create Web Service

1. Go to [Render Dashboard](https://dashboard.render.com) and click **New → Web Service**.
2. Connect your GitHub account if needed, then select this repository.
3. Render detects the `Dockerfile` automatically. Confirm these settings:
   - **Environment**: Docker
   - **Plan**: Free (or Starter for faster builds)
   - **Health Check Path**: `/api/health`

## Build and Start Commands

When using Docker (recommended), Render handles both automatically:
- **Build**: Docker multi-stage builds the frontend and installs Python dependencies.
- **Start**: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`

If you prefer native builds (without Docker), use:
- **Build Command**: `npm --prefix frontend ci && npm --prefix frontend run build && pip install -r backend/requirements.txt`
- **Start Command**: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`

## Environment Variables

These are pre-set in the Dockerfile for try-out mode:

| Variable | Default | Notes |
|----------|---------|-------|
| `REVRANK_LIVE_FETCH_ENABLED` | `false` | Paste text + synthetic examples work without API keys |
| `REVRANK_DATA_DIR` | `/app/.local` | Report storage location |

**Optional** (enable features as needed):

| Variable | Purpose |
|----------|---------|
| `REVRANK_ALLOWED_DOMAINS` | Comma-separated hostnames to enable live fetching (requires `REVRANK_LIVE_FETCH_ENABLED=true`) |
| `REVRANK_LLM_API_KEY` | OpenAI-compatible API key for AI analysis |
| `REVRANK_LLM_BASE_URL` | Custom LLM endpoint (default: `https://api.openai.com/v1`) |
| `REVRANK_LLM_MODEL` | Model name (e.g., `gpt-4o-mini`) |
| `REVRANK_MARKETCHECK_API_KEY` | Licensed inventory lookups |
| `REVRANK_SEARCH_API_KEY` | Web search for vehicle recovery |
| `REVRANK_SEARCH_PROVIDER` | `brave` or `tavily` |

## Free Tier Notes

**Cold starts**: Render free-tier services spin down after 15 minutes of inactivity.
First request after idle may take 30–60 seconds while the container restarts.

**Ephemeral disk**: The `/app/.local` directory is not persisted across deploys or
restarts. Saved reports are lost when the service redeploys. This is fine for a
try-out; upgrade to a paid tier with persistent disk for longer-term use.

## Security Warning

RevRank is an unauthenticated local prototype. Anyone with the URL can:
- Use the app and consume any API credits from keys you configure
- View all saved reports

**Keep the Render URL private.** Share it only with people you trust.

Do not add paid API keys (MarketCheck, LLM, search providers) unless you accept
that anyone with the URL can spend against them. For try-out, the default
`REVRANK_LIVE_FETCH_ENABLED=false` mode requires no keys—paste text and use
synthetic examples.
