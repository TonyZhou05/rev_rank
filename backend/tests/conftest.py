import pytest

from backend.app import usage


@pytest.fixture(autouse=True)
def isolated_usage(monkeypatch, tmp_path):
    # Tests must never read or advance the real paid-provider meter in .local/usage.json.
    monkeypatch.setattr(usage, "usage_path", lambda settings: tmp_path / "usage.json")


@pytest.fixture(autouse=True)
def no_playwright(monkeypatch):
    """CI never launches Chromium. Recovery tests stub browse_listing; this catches a missed stub."""
    def forbidden(*args, **kwargs):
        raise AssertionError("CI must not launch Playwright")
    monkeypatch.setattr("backend.app.browse._playwright_open", forbidden)
