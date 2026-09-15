"""RevRank local FastAPI application."""
import asyncio
from pathlib import Path
import json
import logging
import sqlite3
from threading import Lock
import time
from typing import Callable, TypeVar
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .analyst import analyze
from .cancel import DISCONNECTED, TIMEOUT, Cancelled, CancelToken
from .comparison import create_report
from .config import Settings
from .constraints import parse_constraints
from .demo import demo_candidates
from .extraction import apply_market_units, extract, import_status
from .fetch import FetchError, fetch_listing
from .listing_url import normalize_input_url, url_vin
from .llm import assist_extraction, assist_report
from .models import (AIAnalysis, Candidate, CompareRequest, ConstraintRequest, ConstraintResponse, Evidence,
                     ImportRequest, ImportResponse, Report)
from .sources import sources_response
from .retrieval import attach_original_msrp, recover_listing
from . import usage

settings = Settings.from_env()
# Bump when the wire contract changes; the page warns when it talks to an older API process.
API_REVISION = 7
REQUEST_ID_HEADER = "X-RevRank-Request-Id"
# How often a long compare looks up from its worker thread to see whether the client is still there.
POLL_SECONDS = 0.25
# Grace for a cancelled worker to unwind at its own next checkpoint before it is abandoned.
GRACE_SECONDS = 2.0
log = logging.getLogger("revrank.compare")
Work = TypeVar("Work")
app = FastAPI(title="RevRank API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Accept"],
                   expose_headers=[REQUEST_ID_HEADER])
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
            # Non-secret model identity, so the page can name what it is talking to. Never the key.
            "llm_model": settings.llm_model, "llm_endpoint_host": settings.llm_endpoint_host,
            "search_enabled": settings.search_enabled, "search_provider": settings.search_provider,
            "licensed_inventory_enabled": settings.marketcheck_enabled, "vin_decode_enabled": settings.vin_decode_enabled,
            "neovin_msrp_enabled": settings.neovin_msrp_enabled,
            "compare_timeout_seconds": settings.compare_timeout_seconds,
            "usage": usage.summary(settings)}

@app.get("/api/sources")
def sources():
    return sources_response(settings)

@app.get("/api/demo")
def demo():
    return {"candidates": demo_candidates()}

@app.post("/api/import", response_model=ImportResponse)
def import_listing(request: ImportRequest):
    notes = []
    if request.url:
        # Accept pasted text around the URL and a missing scheme; read a VIN embedded in the URL.
        url = normalize_input_url(request.url)
        vin = url_vin(url)
        if vin and request.vin and vin != request.vin:
            return ImportResponse(status="partial", candidate=None, recovery_status="identity_conflict",
                                  message=f"The VIN in the listing URL ({vin}) differs from the VIN you entered. Confirm which vehicle you mean.")
        if vin and not request.vin:
            notes.append(dict(method="url", status="completed", detail=f"VIN {vin} read from the listing URL (check digit valid)."))
        request = request.model_copy(update={"url": url, "vin": request.vin or vin})
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
                                      attempts=notes + [dict(method='direct', status=error.status, detail=error.message)])
            return recover_listing(request, settings, original)
    candidate, text = extract(raw, source_url, fetched=fetched)
    if fetched and any(w.startswith(("Conflicting vin:", "Multiple structured products found")) for w in candidate.warnings):
        # Several vehicles on one page (search results, "similar cars"): none of them is known to be this listing.
        detail = "The fetched page shows several vehicles, so none of its details were used for this listing."
        original = ImportResponse(status="failed", candidate=None, message=detail,
                                  attempts=notes + [dict(method="direct", status="failed", detail=detail)])
        return recover_listing(request, settings, original)
    if fetched:
        candidate = apply_market_units(candidate, source_url)
        if request.vin and "vin" not in candidate.evidence:
            on_page = request.vin in raw.upper()
            candidate.evidence["vin"] = Evidence(value=request.vin, status="extracted", source=(
                "VIN shown on the listing page" if on_page else "VIN in the listing URL (check digit valid)"))
    elif request.vin and "vin" not in candidate.evidence:
        # No page was read, so the VIN is the buyer's own input whether or not the text repeats it.
        candidate.evidence["vin"] = Evidence(value=request.vin, status="user_confirmed", source=(
            "VIN you entered; also in the pasted text" if request.vin in raw.upper() else "VIN you entered"))
    candidate = assist_extraction(candidate, text, settings)
    candidate.retrieval_method = 'direct' if fetched else 'paste'
    status = import_status(candidate)
    message = "Candidate extracted. Review all fields and warnings before comparing."
    if not fetched:
        message = "Analyzed your pasted text; no website was fetched. Review all fields and warnings before comparing."
    response = ImportResponse(status=status, candidate=candidate, message=message,
                              attempts=notes + [dict(method='direct' if fetched else 'paste', status=status, detail=message)])
    if fetched and request.vin and candidate.evidence.get('vin') and candidate.evidence['vin'].value.upper() != request.vin:
        response.candidate = None
        response.status = 'partial'
        response.message = 'The page VIN differs from the VIN you entered. Confirm vehicle identity.'
        response.recovery_status = 'identity_conflict'
        return response
    if fetched and status == 'partial':
        return recover_listing(request, settings, response)
    # A VIN the buyer pasted, the URL carried, or the page showed also buys the factory MSRP.
    if response.candidate is not None and request.recovery_source in ('auto', 'marketcheck'):
        evidence = response.candidate.evidence.get('vin')
        attach_original_msrp(response.candidate, request.vin or (evidence.value.upper() if evidence else None),
                             settings, response.attempts)
    return response

async def guarded(work: Callable[[], Work], http_request: Request, token: CancelToken) -> Work:
    """Run blocking compare work in a worker thread while watching the client and the deadline.

    Raises Cancelled once the client is gone or the budget is spent. The worker is then abandoned
    rather than joined: it stops at its own next checkpoint, and because it only ever mutates its
    own copy of the report, nothing it does afterwards can reach the response or another request.
    """
    task = asyncio.ensure_future(asyncio.to_thread(work))
    abandon_at = None
    while True:
        done, _ = await asyncio.wait({task}, timeout=POLL_SECONDS)
        if done:
            return task.result()
        if not token.cancelled:
            if await http_request.is_disconnected():
                token.cancel(DISCONNECTED)
            elif token.expired:
                token.cancel(TIMEOUT)
            if not token.cancelled:
                continue
        abandon_at = abandon_at if abandon_at is not None else time.monotonic() + GRACE_SECONDS
        if time.monotonic() >= abandon_at:
            task.cancel()
            raise Cancelled(token.reason)


def interpret(report: Report, token: CancelToken) -> Report:
    """The optional model work, on this request's own copy of the deterministic report."""
    working = assist_report(report.model_copy(deep=True), settings, token=token)
    working.ai_analysis = analyze(working, settings, token=token)
    if working.ai_analysis.status != "unavailable":
        working.analysis_mode = "llm"
    return working


def save(report: Report) -> None:
    body = json.dumps(report.model_dump(), separators=(",", ":"))
    with DB_LOCK, sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?)", (report.id, report.created_at, report.title, report.analysis_mode, body))


def spell_seconds(seconds: float) -> str:
    """Buyer-facing duration: "85 seconds", not "85 s"."""
    whole = round(seconds)
    return f"{whole:.0f} second{'' if whole == 1 else 's'}"


def timed_out(report: Report, seconds: float) -> Report:
    """Report the deterministic comparison honestly, with no analysis inferred from an unfinished run."""
    note = (f"AI analysis was stopped at the server time limit of {spell_seconds(seconds)}; nothing was inferred "
            "from the unfinished run. The comparison, metrics and evidence above are complete.")
    report.warnings = list(dict.fromkeys(report.warnings + [note]))
    report.analysis_mode = "rules"
    report.ai_analysis = AIAnalysis(status="unavailable", message=note)
    return report


@app.post("/api/constraints", response_model=ConstraintResponse)
def constraints(request: ConstraintRequest):
    """Free-form buyer constraints to validated preferences. Never touches a listing fact."""
    return parse_constraints(request.message, request.preferences, settings)


@app.post("/api/compare", response_model=Report)
async def compare(payload: CompareRequest, http_request: Request, response: Response):
    """Deterministic comparison first, optional model work second, both inside one time budget.

    A request id ties the two phases together in the logs so a client retry is distinguishable
    from the attempt it replaced.
    """
    token = CancelToken(timeout=settings.compare_timeout_seconds)
    response.headers[REQUEST_ID_HEADER] = token.id
    started = time.monotonic()
    log.info("compare start id=%s candidates=%d limit=%.0fs", token.id, len(payload.candidates), settings.compare_timeout_seconds)

    def finish(outcome: str) -> None:
        log.info("compare %s id=%s elapsed=%.1fs", outcome, token.id, time.monotonic() - started)

    def problem(status: int, detail: str, outcome: str) -> JSONResponse:
        finish(outcome)
        return JSONResponse(status_code=status, content={"detail": detail}, headers={REQUEST_ID_HEADER: token.id})

    def abandoned() -> JSONResponse:
        # The socket is already gone; 499 records that fact for logs and proxies.
        return problem(499, "Client closed the request before the report was ready.", "abandoned by client")

    try:
        report = await guarded(lambda: create_report(payload.candidates, payload.preferences, settings, token), http_request, token)
    except Cancelled:
        if token.reason == DISCONNECTED:
            return abandoned()
        return problem(503, f"The comparison did not finish within {spell_seconds(settings.compare_timeout_seconds)} "
                            "on the server. Nothing was invented; please try again.",
                       "timed out before the comparison was built")
    try:
        report = await guarded(lambda: interpret(report, token), http_request, token)
    except Cancelled:
        if token.reason == DISCONNECTED:
            return abandoned()
        report = timed_out(report, settings.compare_timeout_seconds)
    if token.reason == DISCONNECTED:
        return abandoned()
    await asyncio.to_thread(save, report)
    finish(f"done mode={report.analysis_mode} ai={report.ai_analysis.status if report.ai_analysis else 'none'}")
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
