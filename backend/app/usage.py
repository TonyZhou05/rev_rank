"""Local monthly meter for paid providers. A call is refused before it is sent once the budget is spent.

The counts live in `.local/usage.json`, keyed by UTC month. They count calls this checkout made, so
usage from other machines or the provider dashboard is not included: keep the limits conservative.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

try:
    import fcntl
except ImportError:  # Windows: the in-process lock still applies.
    fcntl = None

from .config import Settings

LOCK = threading.Lock()
# Units per call. Tavily bills credits (advanced search = 2); MarketCheck and Brave bill requests.
COST = {'marketcheck': 1, 'tavily': 2, 'brave': 1}
UNIT = {'marketcheck': 'calls', 'tavily': 'credits', 'brave': 'requests'}


class BudgetExceeded(Exception):
    pass


def usage_path(settings: Settings) -> Path:
    return settings.data_dir / 'usage.json'


def month() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m')


class Unreadable(Exception):
    pass


def _load(path: Path) -> dict:
    """The meter, or {} when there is none yet. Raises Unreadable when a file exists but cannot be parsed."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise Unreadable(str(error)) from error
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as error:
        raise Unreadable(str(error)) from error
    if not isinstance(data, dict):
        raise Unreadable('not a JSON object')
    return data


def read(settings: Settings) -> dict:
    try:
        return _load(usage_path(settings))
    except Unreadable:
        return {}


def limit(settings: Settings, provider: str) -> int:
    return settings.marketcheck_monthly_calls if provider == 'marketcheck' else settings.search_monthly_credits


def used(settings: Settings, provider: str) -> int:
    value = read(settings).get(month(), {}).get(provider, 0)
    return value if isinstance(value, int) else 0


@contextmanager
def _exclusive(settings: Settings):
    """Serialize read-modify-write across processes too: several local servers and scripts share one meter."""
    path = usage_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path.with_name(path.name + '.lock'), 'a')
    except OSError:
        handle = None
    try:
        if handle and fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        if handle:
            handle.close()  # Closing releases the flock.


def _write(path: Path, data: dict) -> None:
    """Replace the file atomically, so a crash mid-write cannot leave JSON that reads back as empty."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps(data, indent=2))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def spend(settings: Settings, provider: str) -> None:
    """Record one call before it is sent; refuse it if it would pass the monthly limit."""
    cost = COST[provider]
    path = usage_path(settings)
    with LOCK, _exclusive(settings):
        try:
            data = _load(path)
        except Unreadable:
            # Treating it as empty would restart the month at zero and lift the limit.
            raise BudgetExceeded(f'{path.name} could not be read, so paid calls are refused until it is fixed.')
        current = data.setdefault(month(), {})
        spent = current.get(provider, 0) if isinstance(current.get(provider), int) else 0
        cap = limit(settings, provider)
        if spent + cost > cap:
            raise BudgetExceeded(f'{provider} monthly budget reached ({spent}/{cap} {UNIT[provider]}); '
                                 f'raise REVRANK_{"MARKETCHECK_MONTHLY_CALLS" if provider == "marketcheck" else "SEARCH_MONTHLY_CREDITS"} to allow more.')
        current[provider] = spent + cost
        try:
            _write(path, data)
        except OSError:
            pass  # Unrecorded usage still went out; the limit is a safeguard, not billing.


def summary(settings: Settings) -> dict:
    providers = []
    if settings.marketcheck_enabled:
        providers.append('marketcheck')
    if settings.search_enabled:
        providers.append(settings.search_provider)
    return {p: {'used': used(settings, p), 'limit': limit(settings, p), 'unit': UNIT[p], 'month': month()} for p in providers}
