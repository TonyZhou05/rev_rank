# syntax=docker/dockerfile:1
# RevRank Render deployment: single-process web service

# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Production image
FROM python:3.12-slim
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directory (ephemeral on Render free tier)
RUN mkdir -p .local

# Default environment for try-out: no external API keys required
ENV REVRANK_LIVE_FETCH_ENABLED=false
ENV REVRANK_DATA_DIR=/app/.local

# Render injects PORT; bind to 0.0.0.0 for external access
EXPOSE 10000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
