"""Offline regressions for request-scoped cancel and the hard compare timeout.

No test here reaches a network: the model transport is a stub, NHTSA is stubbed out, and no paid
provider is touched.
"""
import asyncio
from dataclasses import replace
import json
import socket
import threading
import time

from fastapi import Response
from fastapi.testclient import TestClient
from starlette.requests import Request
import httpx
import pytest

from backend.app import analyst, comparison, llm, main
from backend.app.cancel import DISCONNECTED, TIMEOUT, CancelToken, Cancelled, budget
from backend.app.comparison import create_report
from backend.app.config import Settings
from backend.app.models import AIAnalysis, Candidate, CompareRequest, Evidence, Preferences

SETTINGS = Settings()
LLM_SETTINGS = Settings(llm_api_key="test-key", llm_model="scripted")


def car(title, make, model, year, price, mileage):
    c = Candidate(id=title.replace(" ", "-").lower(), title=title, make=make, model=model, year=year,
                  price=price, currency="USD", mileage=mileage, mileage_unit="mi", source_kind="user")
    for field in ("make", "model", "year", "price", "currency", "mileage", "mileage_unit"):
        c.evidence[field] = Evidence(value=str(getattr(c, field)), source="User-pasted listing text", status="extracted")
    return c


def cars():
    return [car("2021 Chevrolet Corvette", "Chevrolet", "Corvette", 2021, 67494, 16151),
            car("2022 BMW M4", "BMW", "M4", 2022, 63998, 29995)]


def payload():
    return CompareRequest(candidates=cars(), preferences=Preferences(budget=70000))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *args: None)


def client_request(disconnect_after: int = -1) -> Request:
    """A POST whose receive channel reports http.disconnect from the given poll onwards."""
    polls = {"n": 0}

    async def receive():
        polls["n"] += 1
        if 0 <= disconnect_after < polls["n"]:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "http_version": "1.1", "method": "POST", "path": "/api/compare",
                    "headers": [], "query_string": b"", "scheme": "http"}, receive)


def run(coroutine):
    return asyncio.run(coroutine)


# ---- token ------------------------------------------------------------------------------------
def test_token_reports_its_own_deadline_and_reason():
    token = CancelToken(timeout=30)
    assert not token.cancelled and token.reason == "" and 29 < token.remaining() <= 30
    token.cancel(DISCONNECTED)
    assert token.cancelled and token.reason == DISCONNECTED
    with pytest.raises(Cancelled) as stop:
        token.check()
    assert stop.value.reason == DISCONNECTED


def test_expired_token_cancels_itself_without_help():
    token = CancelToken(timeout=0.01)
    time.sleep(0.02)
    assert token.expired and token.cancelled and token.reason == TIMEOUT and token.remaining() == 0


def test_budget_never_exceeds_the_remaining_request_time():
    assert budget(None, 120) == 120
    assert 0 < budget(CancelToken(timeout=5), 120) <= 5
    assert budget(CancelToken(timeout=500), 20) == 20
    with pytest.raises(Cancelled):
        budget(CancelToken(timeout=0.01), 120, minimum=1)


def test_a_cancel_runs_the_closers_it_was_lent():
    token, closed = CancelToken(timeout=30), []
    with token.closing(lambda: closed.append("aborted")):
        assert closed == []
        # A read blocked on the provider is broken instead of waiting out its socket timeout.
        token.cancel(DISCONNECTED)
        assert closed == ["aborted"]
    with pytest.raises(Cancelled):
        with token.closing(lambda: closed.append("never")):
            raise AssertionError("an abandoned request may not open another stream")
    assert closed == ["aborted"]


def test_tokens_are_independent_of_each_other():
    first, second = CancelToken(timeout=30), CancelToken(timeout=30)
    first.cancel(DISCONNECTED)
    assert first.id != second.id
    assert first.cancelled and not second.cancelled


# ---- model transport --------------------------------------------------------------------------
def stub_transport(monkeypatch, handler, captured=None):
    """Send llm.py's own httpx client through a stub transport, keeping its timeouts observable."""
    real = httpx.Client

    def client(**kwargs):
        if captured is not None:
            captured.append(kwargs.get("timeout"))
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(llm.httpx, "Client", client)


def completion_body(content: dict) -> bytes:
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()


def test_a_cancel_mid_stream_beats_an_otherwise_usable_answer(monkeypatch):
    token = CancelToken(timeout=30)

    def body():
        yield b'{"choices": [{"message":'
        token.cancel(DISCONNECTED)  # the browser aborted the fetch while the answer arrived
        yield b' {"role": "assistant", "content": "hello"}}]}'

    stub_transport(monkeypatch, lambda request: httpx.Response(200, content=body()))
    with pytest.raises(Cancelled) as stop:
        llm.chat(LLM_SETTINGS, [{"role": "user", "content": "x"}], [], timeout=60, token=token)
    assert stop.value.reason == DISCONNECTED


def test_a_closed_stream_is_reported_as_a_cancel_not_as_a_bad_model(monkeypatch):
    token = CancelToken(timeout=30)

    def body():
        yield b'{"choices"'
        token.cancel(DISCONNECTED)
        raise httpx.ReadError("stream closed")

    stub_transport(monkeypatch, lambda request: httpx.Response(200, content=body()))
    with pytest.raises(Cancelled):
        llm.chat(LLM_SETTINGS, [{"role": "user", "content": "x"}], [], timeout=60, token=token)


def test_a_transport_error_without_a_cancel_stays_a_model_failure(monkeypatch):
    def body():
        yield b'{"choices"'
        raise httpx.ReadError("provider went away")

    stub_transport(monkeypatch, lambda request: httpx.Response(200, content=body()))
    with pytest.raises(llm.LLMUnavailable):
        llm.chat(LLM_SETTINGS, [{"role": "user", "content": "x"}], [], timeout=60, token=CancelToken(timeout=30))


def stalling_endpoint() -> tuple[str, threading.Thread]:
    """A local socket that answers with headers and then never sends a body."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve():
        connection, _ = listener.accept()
        with connection, listener:
            connection.recv(65536)
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n")
            while True:
                try:
                    if connection.recv(1) == b"":
                        return
                except OSError:
                    return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{listener.getsockname()[1]}/v1", thread


def test_a_cancel_breaks_a_read_blocked_on_the_model():
    """A blocked read must fail on the cancel, not on its own socket timeout minutes later."""
    endpoint, server = stalling_endpoint()
    settings = replace(LLM_SETTINGS, llm_base_url=endpoint)
    token = CancelToken(timeout=120)
    threading.Timer(0.3, lambda: token.cancel(DISCONNECTED)).start()
    started = time.monotonic()
    with pytest.raises(Cancelled) as stop:
        llm.chat(settings, [{"role": "user", "content": "x"}], [], timeout=120, token=token)
    assert stop.value.reason == DISCONNECTED
    assert time.monotonic() - started < 5
    server.join(timeout=5)
    # The provider is told the request is gone instead of finishing an answer nobody reads.
    assert not server.is_alive()


def test_the_socket_timeout_is_clamped_to_the_remaining_budget(monkeypatch):
    captured = []
    stub_transport(monkeypatch, lambda request: httpx.Response(200, content=completion_body({"ok": True})), captured)
    assert llm.request_json(LLM_SETTINGS, "system", {}, token=CancelToken(timeout=4), timeout=20) == {"ok": True}
    assert 3 < captured[0].read <= 4


def test_no_request_is_started_once_the_request_is_cancelled(monkeypatch):
    def refuse(request):
        raise AssertionError("a cancelled request must not reach the model")

    stub_transport(monkeypatch, refuse)
    token = CancelToken(timeout=30)
    token.cancel(DISCONNECTED)
    with pytest.raises(Cancelled):
        llm.chat(LLM_SETTINGS, [], [], timeout=60, token=token)
    with pytest.raises(Cancelled):
        llm.request_json(LLM_SETTINGS, "system", {}, token=token)


# ---- analyst ----------------------------------------------------------------------------------
def analyst_report():
    return create_report(cars(), Preferences(budget=70000), LLM_SETTINGS)


def tool_call(name, **args):
    return {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_the_analyst_never_starts_a_turn_without_time_for_one(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no model turn may start without time to finish it")

    monkeypatch.setattr(analyst, "chat", refuse)
    analysis = analyst.analyze(analyst_report(), LLM_SETTINGS, token=CancelToken(timeout=0.5))
    assert analysis.status == "unavailable"
    assert analyst.STOPPED_EARLY in analysis.message


def test_a_disconnect_stops_the_tool_loop_and_reaches_the_endpoint(monkeypatch):
    token = CancelToken(timeout=60)
    turns = []

    def chat(settings, messages, tools, timeout, token=None):
        turns.append(timeout)
        token.cancel(DISCONNECTED)
        return {"role": "assistant", "content": "", "tool_calls": [tool_call("get_vehicle_facts", car="A")]}

    monkeypatch.setattr(analyst, "chat", chat)
    with pytest.raises(Cancelled) as stop:
        analyst.analyze(analyst_report(), LLM_SETTINGS, token=token)
    assert stop.value.reason == DISCONNECTED
    assert len(turns) == 1


def test_a_spent_budget_keeps_the_findings_that_passed_the_checks(monkeypatch):
    token = CancelToken(timeout=60)

    def chat(settings, messages, tools, timeout, token=None):
        if not getattr(chat, "used", False):
            chat.used = True
            return {"role": "assistant", "content": "", "tool_calls": [
                tool_call("get_vehicle_facts", car="A"), tool_call("get_comparison_metrics"),
                tool_call("add_finding", kind="verdict", car="all", citations=["M.price_gap.AB"],
                          text="Car B is 3,496 USD cheaper than Car A.")]}
        token.cancel(TIMEOUT)
        raise Cancelled(TIMEOUT)

    monkeypatch.setattr(analyst, "chat", chat)
    analysis = analyst.analyze(analyst_report(), LLM_SETTINGS, token=token)
    assert analysis.status == "partial"
    assert analysis.verdict.text.startswith("2022 BMW M4 is 3,496 USD cheaper")
    assert analyst.STOPPED_EARLY in analysis.message


# ---- deterministic phase ----------------------------------------------------------------------
def test_safety_data_is_skipped_rather_than_spending_the_whole_budget(monkeypatch):
    fetched = []
    monkeypatch.setattr(comparison, "fetch_nhtsa_safety", lambda *args: fetched.append(args) or None)
    cancelled = CancelToken(timeout=60)
    cancelled.cancel(DISCONNECTED)
    for token in (cancelled, CancelToken(timeout=2)):
        report = create_report(cars(), Preferences(), SETTINGS, token)
        assert report.nhtsa_data == {}
        # The comparison itself is unaffected: only the optional enrichment is dropped.
        assert any(m.label == "Asking price" for m in report.metrics)
    assert fetched == []


# ---- endpoint ---------------------------------------------------------------------------------
def test_compare_returns_a_request_id_header_that_differs_per_call():
    with TestClient(main.app) as client:
        body = json.loads(payload().model_dump_json())
        first = client.post("/api/compare", json=body)
        second = client.post("/api/compare", json=body)
    assert first.status_code == second.status_code == 200
    ids = {first.headers[main.REQUEST_ID_HEADER], second.headers[main.REQUEST_ID_HEADER]}
    assert len(ids) == 2 and all(len(value) == 16 for value in ids)


def test_a_client_disconnect_abandons_the_model_work_and_saves_nothing(monkeypatch):
    events = []
    monkeypatch.setattr(main, "save", lambda report: events.append("saved"))

    def analyze(report, settings, token=None):
        events.append("analysis started")
        while not token.cancelled:
            time.sleep(0.01)
        events.append("analysis stopped: " + token.reason)
        raise Cancelled(token.reason)

    monkeypatch.setattr(main, "analyze", analyze)
    response = run(main.compare(payload(), client_request(disconnect_after=1), Response()))
    assert response.status_code == 499
    assert response.headers[main.REQUEST_ID_HEADER]
    assert events == ["analysis started", "analysis stopped: " + DISCONNECTED]


def test_the_hard_timeout_returns_the_deterministic_report_without_inventing_analysis(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(SETTINGS, compare_timeout_seconds=0.5))
    monkeypatch.setattr(main, "save", lambda report: None)

    def analyze(report, settings, token=None):
        while not token.cancelled:
            time.sleep(0.01)
        raise Cancelled(token.reason)

    monkeypatch.setattr(main, "analyze", analyze)
    started = time.monotonic()
    report = run(main.compare(payload(), client_request(), Response()))
    assert time.monotonic() - started < 5
    assert report.analysis_mode == "rules"
    assert report.ai_analysis.status == "unavailable"
    assert report.ai_analysis.verdict is None and report.ai_analysis.comparisons == []
    assert "server time limit" in report.ai_analysis.message
    assert any("server time limit" in w for w in report.warnings)
    # The deterministic comparison is still whole.
    assert any(m.label == "Asking price" for m in report.metrics) and report.findings


def test_a_worker_that_ignores_the_cancel_cannot_reach_the_response(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(SETTINGS, compare_timeout_seconds=0.3))
    monkeypatch.setattr(main, "GRACE_SECONDS", 0.2)
    monkeypatch.setattr(main, "save", lambda report: None)
    done = threading.Event()

    def analyze(report, settings, token=None):
        time.sleep(1.0)
        # A stubborn worker still only ever mutates this request's own copy of the report.
        report.warnings.append("late model warning")
        done.set()
        return AIAnalysis(status="complete", message="late analysis")

    monkeypatch.setattr(main, "analyze", analyze)
    report = run(main.compare(payload(), client_request(), Response()))
    assert report.analysis_mode == "rules" and report.ai_analysis.status == "unavailable"
    assert done.wait(5)
    assert not any("late" in w for w in report.warnings)
    assert report.ai_analysis.message != "late analysis"


def test_concurrent_compares_keep_separate_ids_state_and_cancellation(monkeypatch):
    monkeypatch.setattr(main, "save", lambda report: None)
    release, tokens = threading.Event(), []

    def analyze(report, settings, token=None):
        tokens.append(token)
        while not release.is_set():
            if token.cancelled:
                raise Cancelled(token.reason)
            time.sleep(0.01)
        return AIAnalysis(status="complete", message="stub analysis")

    monkeypatch.setattr(main, "analyze", analyze)

    async def both():
        async def releaser():
            await asyncio.sleep(0.8)
            release.set()
        return await asyncio.gather(main.compare(payload(), client_request(disconnect_after=1), Response()),
                                    main.compare(payload(), client_request(), Response()),
                                    releaser())

    abandoned, report, _ = run(both())
    assert abandoned.status_code == 499
    assert report.analysis_mode == "llm" and report.ai_analysis.status == "complete"
    first, second = tokens
    assert first is not second and first.id != second.id
    assert first.cancelled and first.reason == DISCONNECTED
    assert not second.cancelled
