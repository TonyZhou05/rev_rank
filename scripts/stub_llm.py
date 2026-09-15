"""Local stand-in for the OpenAI-compatible model endpoint, for offline UI work.

It answers `POST /v1/chat/completions` the way DeepSeek would, so the cited analysis, the shortlist
re-rank and the constraint chat can be seen in a browser with no API key and no spend. It is a
development aid and is never imported by the application.

Every claim it makes is copied verbatim out of the tool results the analyst handed it, so it passes
the same citation gate a real model has to pass rather than bypassing it. Constraint mappings come
from the deterministic phrase rules, so their quotes are grounded in the buyer's own message by
construction.

It exercises the plumbing, not the judgement: which metric it calls a green flag is arbitrary, so
do not read its output as a sample of what a real model would say.

    python3 scripts/stub_llm.py &
    REVRANK_LLM_API_KEY=stub REVRANK_LLM_MODEL=deepseek-flash \
      REVRANK_LLM_BASE_URL=http://127.0.0.1:8099/v1 python3 -m uvicorn backend.app.main:app
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.constraints import rule_constraints  # noqa: E402

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def tool_results(messages: list[dict]) -> list[dict]:
    """Everything the analyst has already returned to the model this run."""
    results = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            results.append(json.loads(message.get("content") or "{}"))
        except ValueError:
            continue
    return results


def facts_by_car(results: list[dict]) -> dict[str, list[dict]]:
    return {r["car"]: r.get("facts") or [] for r in results if r.get("car") and "facts" in r}


def metrics(results: list[dict]) -> list[dict]:
    return [item for r in results for item in (r.get("metrics") or [])]


def constraint_mapping(message: str) -> dict:
    """Phrase-rule output in the model's response shape; quotes come from the buyer's words."""
    found = rule_constraints(message)
    items = [{"field": f.field,
              "value": f.value if f.field not in ("budget", "annual_mileage", "ownership_years", "max_mileage")
                       else float(f.value),
              "quote": f.quote}
             for f in found]
    return {"constraints": items[:16], "unmapped": []}


def call(name: str, **arguments) -> dict:
    return {"id": f"stub-{name}-{abs(hash(json.dumps(arguments, sort_keys=True))) % 10000}",
            "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def analyst_turn(messages: list[dict]) -> list[dict]:
    results = tool_results(messages)
    if not results:
        try:
            cars = list(json.loads(messages[1]["content"])["cars"])
        except (IndexError, KeyError, ValueError):
            cars = ["A", "B"]
        return [call("get_vehicle_facts", car=car) for car in cars] + [call("get_comparison_metrics")]

    facts = facts_by_car(results)
    rows = metrics(results)
    if not any(r.get("ok") for r in results):
        calls = []
        gap = next((m for m in rows if "price_gap" in m["id"]), None) or (rows[0] if rows else None)
        if gap:
            calls.append(call("add_finding", kind="verdict", car="all", text=gap["text"], citations=[gap["id"]]))
        for car, items in facts.items():
            # Copying each tool result's own wording keeps every number inside the cited result,
            # which is what a real model has to do to get a flag past the gate.
            green = [m for key in ("budget", "msrp_pct", "mileage_per_year", "fit", "dom")
                     for m in rows if m["id"] == f"M.{car}.{key}"]
            for metric in green[:5]:
                calls.append(call("add_finding", kind="green_flag", car=car, text=metric["text"],
                                  citations=[metric["id"]]))
            for fact in [f for f in items if f["field"] in ("features", "transmission", "history")][:2]:
                calls.append(call("add_finding", kind="red_flag", car=car,
                                  text=f"Car {car} lists {fact['field'].replace('_', ' ')}: {fact['value']}. "
                                       "Confirm it on the car before relying on it.",
                                  citations=[fact["id"]]))
        mileage_gap = next((m for m in rows if "mileage_gap" in m["id"]), None)
        if mileage_gap:
            calls.append(call("add_finding", kind="comparison", car="all", topic="mileage",
                              text=mileage_gap["text"], citations=[mileage_gap["id"]]))
        for car in facts:
            calls.append(call("add_finding", kind="question", car=car,
                              text="Can you share the full service history and a pre-purchase inspection?"))
        reasons = []
        for car, items in facts.items():
            fit = next((m for m in rows if m["id"] == f"M.{car}.fit"), None)
            price = next((f for f in items if f["field"] == "price"), None)
            if fit:
                reasons.append({"car": car, "text": fit["text"], "citations": [fit["id"]]})
            elif price:
                reasons.append({"car": car, "text": f"Car {car} asks {price['value']}.", "citations": [price["id"]]})
        if len(reasons) == len(facts) and reasons:
            # Best constraint fit first, then the cheaper car; ties keep tool order.
            def key(reason):
                numbers = [float(n.replace(",", "")) for n in NUMBER.findall(reason["text"])]
                return (-(numbers[0] if numbers else 0), reason["car"])
            order = [r["car"] for r in sorted(reasons, key=key)] if all("meets" in r["text"] for r in reasons) \
                else [r["car"] for r in reasons]
            calls.append(call("set_ranking", order=order, reasons=reasons))
        return calls
    return [call("finish")]


class Handler(BaseHTTPRequestHandler):
    server_version = "RevRankStubLLM/1.0"

    def log_message(self, fmt, *args):
        print(f"stub-llm: {fmt % args}", flush=True)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404, "Only /chat/completions is stubbed")
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        messages = body.get("messages") or []
        if (body.get("response_format") or {}).get("type") == "json_object":
            payload = json.loads(messages[-1]["content"])
            if "message" in payload:
                content = json.dumps(constraint_mapping(payload["message"]))
            else:
                # The finding ranker wants an order over findings plus supplied facts as citations.
                order = list(range(len(payload.get("findings") or [])))
                content = json.dumps({"finding_order": order, "citations": (payload.get("facts") or [])[:20]})
            message = {"role": "assistant", "content": content}
        else:
            message = {"role": "assistant", "content": "", "tool_calls": analyst_turn(messages)}
        raw = json.dumps({"choices": [{"message": message}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"stub model endpoint on http://127.0.0.1:{args.port}/v1 (development only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
