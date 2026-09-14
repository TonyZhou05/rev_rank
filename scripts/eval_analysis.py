"""Live AI-analysis self-test: import real listings, build the report, run the tool-calling analyst.

Model settings come from .env, or override them for a local run, e.g. with Ollama:

    REVRANK_LLM_BASE_URL=http://127.0.0.1:11434/v1 REVRANK_LLM_MODEL=llama3.2 REVRANK_LLM_API_KEY=ollama \\
        .venv/bin/python scripts/eval_analysis.py [URL ...]

Imports spend search credits; the analysis calls NHTSA and the configured model.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.analyst import analyze  # noqa: E402
from backend.app.comparison import create_report  # noqa: E402
from backend.app.models import Candidate, Preferences  # noqa: E402

DEFAULT_URLS = ("https://www.carmax.com/car/70043489", "https://www.carmax.com/car/28084730",
                "https://www.carvana.com/vehicle/4711856?refSource=home")


def main_() -> int:
    settings = replace(main.settings, **{k: v for k, v in (
        ("llm_base_url", os.getenv("REVRANK_LLM_BASE_URL")), ("llm_model", os.getenv("REVRANK_LLM_MODEL")),
        ("llm_api_key", os.getenv("REVRANK_LLM_API_KEY"))) if v})
    client = TestClient(main.app)
    candidates = []
    for url in sys.argv[1:] or DEFAULT_URLS:
        body = client.post("/api/import", json={"url": url}).json()
        if body.get("candidate"):
            candidates.append(Candidate.model_validate(body["candidate"]))
            print("imported", body["candidate"]["title"])
        else:
            print("FAILED import", url, body.get("message", "")[:120])
    report = create_report(candidates, Preferences(budget=70000, priorities=["Lower asking price", "Safety record"]), settings)
    started = time.monotonic()
    analysis = analyze(report, settings)
    print(f"\nstatus={analysis.status} tool_calls={analysis.tool_calls} dropped={analysis.dropped_claims} "
          f"sources={len(analysis.sources)} seconds={time.monotonic() - started:.0f} model={analysis.model}\n{analysis.message}")
    names = {c.id: c.title for c in report.candidates}
    if analysis.verdict:
        print("\nVERDICT:", analysis.verdict.text, analysis.verdict.citations)
    for vehicle in analysis.vehicles:
        print("\n#", names.get(vehicle.candidate_id))
        if vehicle.summary:
            print("  summary:", vehicle.summary.text, vehicle.summary.citations)
        for claim in vehicle.strengths:
            print("  +", claim.text, claim.citations)
        for claim in vehicle.risks:
            print("  -", claim.text, claim.citations)
    for point in analysis.comparisons:
        print(f"\n[{point.topic}] favors={names.get(point.favors or '', 'none')}: {point.claim.text} {point.claim.citations}")
    for question in analysis.questions:
        print("  ?", names.get(question.candidate_id), "—", question.text)
    print("\nSources:", json.dumps([s.id for s in analysis.sources]))
    return 0 if analysis.status != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main_())
