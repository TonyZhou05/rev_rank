"""Local monthly meter for paid providers. A call is refused before it is sent once the budget is spent.

The counts live in `.local/usage.json`, keyed by UTC month. They count calls this checkout made, so
usage from other machines or the provider dashboard is not included: keep the limits conservative.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

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


def read(settings: Settings) -> dict:
    try:
        data = json.loads(usage_path(settings).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def limit(settings: Settings, provider: str) -> int:
    return settings.marketcheck_monthly_calls if provider == 'marketcheck' else settings.search_monthly_credits


def used(settings: Settings, provider: str) -> int:
    value = read(settings).get(month(), {}).get(provider, 0)
    return value if isinstance(value, int) else 0


def spend(settings: Settings, provider: str) -> None:
    """Record one call before it is sent; refuse it if it would pass the monthly limit."""
    cost = COST[provider]
    with LOCK:
        data = read(settings)
        current = data.setdefault(month(), {})
        spent = current.get(provider, 0) if isinstance(current.get(provider), int) else 0
        cap = limit(settings, provider)
        if spent + cost > cap:
            raise BudgetExceeded(f'{provider} monthly budget reached ({spent}/{cap} {UNIT[provider]}); '
                                 f'raise REVRANK_{"MARKETCHECK_MONTHLY_CALLS" if provider == "marketcheck" else "SEARCH_MONTHLY_CREDITS"} to allow more.')
        current[provider] = spent + cost
        try:
            usage_path(settings).parent.mkdir(parents=True, exist_ok=True)
            usage_path(settings).write_text(json.dumps(data, indent=2))
        except OSError:
            pass  # Unrecorded usage still went out; the limit is a safeguard, not billing.


def summary(settings: Settings) -> dict:
    providers = []
    if settings.marketcheck_enabled:
        providers.append('marketcheck')
    if settings.search_enabled:
        providers.append(settings.search_provider)
    return {p: {'used': used(settings, p), 'limit': limit(settings, p), 'unit': UNIT[p], 'month': month()} for p in providers}
