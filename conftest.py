"""Shared by backend/tests and tests/: every test run is offline and uses a throwaway data dir.

config.py loads .env with override=False, so these are set before any backend module is imported.
Without them a local run with a developer .env calls the live model and paid providers, and saves
test reports into the real .local/reports.sqlite3. CI has no .env, so this changes nothing there.
"""
import os
import tempfile

for name in ("REVRANK_LLM_API_KEY", "REVRANK_LLM_MODEL", "REVRANK_MARKETCHECK_API_KEY", "REVRANK_SEARCH_API_KEY"):
    os.environ[name] = ""
for name in ("REVRANK_LIVE_FETCH_ENABLED", "REVRANK_VIN_DECODE_ENABLED", "REVRANK_DEALER_SIGNALS_ENABLED",
             "REVRANK_BROWSER_RECOVERY_ENABLED"):
    os.environ[name] = "false"
os.environ["REVRANK_DATA_DIR"] = tempfile.mkdtemp(prefix="revrank-tests-")
