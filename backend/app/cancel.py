"""Request-scoped cancellation for work a client may abandon.

One token per HTTP request, created by the endpoint and passed down explicitly: nothing here is
module state, so concurrent requests never cancel or time out one another. Blocking work checks
the token at safe points, and a token cancelled from another thread (the event loop noticing a
client disconnect) also closes the streams registered with it, so an in-flight read stops instead
of waiting out its socket timeout.
"""
from contextlib import contextmanager
import threading
import time
from uuid import uuid4

# Reason strings; they reach logs and honest user-facing messages, never provider detail.
DISCONNECTED = "client_disconnected"
TIMEOUT = "timeout"


class Cancelled(Exception):
    """Raised at a checkpoint once the request was abandoned or its time budget ran out."""

    def __init__(self, reason: str = TIMEOUT):
        super().__init__(reason)
        self.reason = reason


def request_id() -> str:
    """Short id for one request; it identifies a retry in logs, and carries no user data."""
    return uuid4().hex[:16]


class CancelToken:
    def __init__(self, timeout: float | None = None, id: str | None = None):
        self.id = id or request_id()
        self.timeout = timeout if timeout and timeout > 0 else None
        self._deadline = time.monotonic() + self.timeout if self.timeout else None
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closers: list = []
        self._reason = ""

    @property
    def expired(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or self.expired

    @property
    def reason(self) -> str:
        return self._reason or (TIMEOUT if self.expired else "")

    def remaining(self) -> float:
        return float("inf") if self._deadline is None else max(0.0, self._deadline - time.monotonic())

    def cancel(self, reason: str = DISCONNECTED) -> None:
        """Stop this request's work. Safe to call from another thread, and only ever once."""
        with self._lock:
            first = not self._event.is_set()
            if first:
                self._reason = reason
            self._event.set()
            closers, self._closers = self._closers, []
        for close in closers:
            try:
                close()
            except Exception:
                # A stream that refuses to close still leaves the checkpoint checks in place.
                pass

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled(self.reason)

    @contextmanager
    def closing(self, stream):
        """Let a cancel close this stream while it is being read."""
        self.check()
        with self._lock:
            self._closers.append(stream.close)
        try:
            yield stream
        finally:
            with self._lock:
                if stream.close in self._closers:
                    self._closers.remove(stream.close)


def budget(token: CancelToken | None, cap: float, minimum: float = 1.0) -> float:
    """Seconds one call may spend: its own cap, or what is left of the request's budget.

    Raises Cancelled rather than starting a call that cannot finish inside the remaining time.
    """
    if token is None:
        return cap
    token.check()
    left = token.remaining()
    if left < minimum:
        raise Cancelled(token.reason or TIMEOUT)
    return min(cap, left)


@contextmanager
def closing(token: CancelToken | None, stream):
    """token.closing for an optional token."""
    if token is None:
        yield stream
        return
    with token.closing(stream):
        yield stream
