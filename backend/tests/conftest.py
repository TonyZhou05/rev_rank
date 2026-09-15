import pytest

# The repository-root conftest.py has already blanked .env credentials before this import.
from backend.app import comparison, usage, vehicle_data
from backend.app.vehicle_data import ProviderError


@pytest.fixture(autouse=True)
def isolated_usage(monkeypatch, tmp_path):
    # Tests must never read or advance the real paid-provider meter in .local/usage.json, or read
    # the real NeoVIN cache (a hit there would skip the stubbed provider).
    monkeypatch.setattr(usage, "usage_path", lambda settings: tmp_path / "usage.json")
    monkeypatch.setattr(vehicle_data, "neovin_cache_path", lambda settings: tmp_path / "neovin_msrp.json")


@pytest.fixture(autouse=True)
def offline_nhtsa(monkeypatch):
    """Report tests do not reach api.nhtsa.gov; tests of the NHTSA block stub `_nhtsa` themselves."""
    def offline(*args, **kwargs):
        raise ProviderError("NHTSA is offline in tests")
    monkeypatch.setattr(comparison, "_nhtsa", offline)


@pytest.fixture(autouse=True)
def no_playwright(monkeypatch):
    """CI never launches Chromium. Recovery tests stub browse_listing; this catches a missed stub."""
    def forbidden(*args, **kwargs):
        raise AssertionError("CI must not launch Playwright")
    monkeypatch.setattr("backend.app.browse._playwright_open", forbidden)
