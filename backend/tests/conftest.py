import pytest

from backend.app import usage


@pytest.fixture(autouse=True)
def isolated_usage(monkeypatch, tmp_path):
    # Tests must never read or advance the real paid-provider meter in .local/usage.json.
    monkeypatch.setattr(usage, "usage_path", lambda settings: tmp_path / "usage.json")
