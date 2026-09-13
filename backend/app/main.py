"""RevRank local FastAPI application."""
from pathlib import Path
import json
import sqlite3
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .comparison import create_report
from .config import Settings
from .demo import demo_candidates
from .extraction import extract, import_status
from .fetch import FetchError, fetch_listing
from .llm import assist_extraction, assist_report
from .models import Candidate, CompareRequest, ImportRequest, ImportResponse, Report
from .sources import sources_response
from .retrieval import recover_listing

settings = Settings.from_env()
# Bump when the wire contract changes; the page warns when it talks to an older API process.
API_REVISION = 2
app = FastAPI(title="RevRank API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Accept"])
DB_LOCK = Lock()
DB_PATH = settings.data_dir / "reports.sqlite3"

def init_db():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, title TEXT NOT NULL, mode TEXT NOT NULL, body TEXT NOT NULL)")
init_db()

@app.get("/api/health")
def health():
    return {"status": "ok", "api_revision": API_REVISION, "llm_enabled": settings.llm_enabled, "market_enabled": False,
            "search_enabled": settings.search_enabled, "search_provider": settings.search_provider,
            "licensed_inventory_enabled": settings.marketcheck_enabled, "vin_decode_enabled": settings.vin_decode_enabled}

@app.get("/api/sources")
def sources():
    return sources_response(settings)

@app.get("/api/demo")
def demo():
    return {"candidates": demo_candidates()}

@app.post("/api/import", response_model=ImportResponse)
def import_listing(request: ImportRequest):
    source_url = request.url
    fetched = False
    raw = request.text or ""
    if request.url and not raw.strip():
        try:
            page = fetch_listing(request.url, settings)
            raw = page.text
            source_url = page.url
            fetched = True
        except FetchError as error:
            original = ImportResponse(status=error.status, candidate=None, message=error.message,
                                      attempts=[dict(method='direct', status=error.status, detail=error.message)])
            return recover_listing(request, settings, original)
    candidate, text = extract(raw, source_url, fetched=fetched)
    candidate = assist_extraction(candidate, text, settings)
    candidate.retrieval_method = 'direct' if fetched else 'paste'
    status = import_status(candidate)
    message = "Candidate extracted. Review all fields and warnings before comparing."
    if not fetched:
        message = "Analyzed your pasted text; no website was fetched. Review all fields and warnings before comparing."
    response = ImportResponse(status=status, candidate=candidate, message=message,
                              attempts=[dict(method='direct' if fetched else 'paste', status=status, detail=message)])
    if fetched and request.vin and candidate.evidence.get('vin') and candidate.evidence['vin'].value.upper() != request.vin:
        response.candidate = None
        response.status = 'partial'
        response.message = 'The page VIN differs from the VIN you entered. Confirm vehicle identity.'
        response.recovery_status = 'identity_conflict'
        return response
    if fetched and status == 'partial':
        return recover_listing(request, settings, response)
    return response

@app.post("/api/compare", response_model=Report)
def compare(request: CompareRequest):
    report = create_report(request.candidates, request.preferences, settings)
    report = assist_report(report, settings)
    body = json.dumps(report.model_dump(), separators=(",", ":"))
    with DB_LOCK, sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?)", (report.id, report.created_at, report.title, report.analysis_mode, body))
    return report

@app.get("/api/reports")
def reports():
    with DB_LOCK, sqlite3.connect(DB_PATH) as db:
        rows = db.execute("SELECT id, title, created_at, mode FROM reports ORDER BY created_at DESC LIMIT 50").fetchall()
    return {"reports": [{"id": r[0], "title": r[1], "created_at": r[2], "analysis_mode": r[3]} for r in rows]}

@app.get("/api/reports/{report_id}", response_model=Report)
def report(report_id: str):
    with DB_LOCK, sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT body FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    return Report.model_validate_json(row[0])

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    @app.get("/{path:path}")
    def frontend(path: str):
        requested = DIST / path
        if path and requested.is_file() and DIST in requested.parents:
            return FileResponse(requested)
        return FileResponse(DIST / "index.html")
