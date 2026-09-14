"""Bounded search API adapters. Search output is evidence, never an instruction.

Fixed provider endpoints; discovered URLs are not fetched by this module.
"""
from dataclasses import dataclass
import json
import time
import httpx

from .config import Settings
from .usage import BudgetExceeded, spend


@dataclass(frozen=True)
class SearchResult:
    url: str
    text: str


class SearchError(Exception):
    pass


def search(query: str, settings: Settings, timeout: float = 10, domain: str | None = None) -> list[SearchResult]:
    # domain scopes results to one site (the seller); it is a bare hostname, never user text.
    if not settings.search_enabled:
        raise SearchError('Search provider is not configured.')
    try:
        spend(settings, settings.search_provider)
    except BudgetExceeded as error:
        raise SearchError(str(error)) from None
    timeout = max(.1, min(timeout, 10))
    deadline = time.monotonic() + timeout
    if settings.search_provider == 'brave':
        method, url = 'GET', 'https://api.search.brave.com/res/v1/web/search'
        kwargs = dict(headers={'X-Subscription-Token': settings.search_api_key},
                      params={'q': (f'site:{domain} ' if domain else '') + query[:500], 'count': 5, 'extra_snippets': 'true'})
    else:
        method, url = 'POST', 'https://api.tavily.com/search'
        kwargs = dict(headers={'Authorization': 'Bearer ' + settings.search_api_key},
                      json={'query': query[:500], 'max_results': 5, 'search_depth': 'advanced',
                            'include_answer': False, 'include_raw_content': False,
                            **({'include_domains': [domain]} if domain else {})})
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(4, timeout)),
                          follow_redirects=False, trust_env=False) as client:
            with client.stream(method, url, **kwargs) as response:
                if response.status_code != 200:
                    raise SearchError(f'Search provider returned HTTP {response.status_code}.')
                chunks, size = [], 0
                for chunk in response.iter_bytes(chunk_size=8192):
                    size += len(chunk)
                    if size > 512000 or time.monotonic() >= deadline:
                        raise SearchError('Search provider exceeded response size or time limit.')
                    chunks.append(chunk)
        payload = json.loads(b''.join(chunks))
        rows = payload.get('web', {}).get('results', []) if settings.search_provider == 'brave' else payload.get('results', [])
        if not isinstance(rows, list):
            raise ValueError()
        results = []
        for row in rows[:5]:
            if not isinstance(row, dict) or not isinstance(row.get('url'), str):
                continue
            snippets = [row.get('description', '')] + row.get('extra_snippets', []) if settings.search_provider == 'brave' else [row.get('content', '')]
            # Keep independently selected snippets separate: joining excerpts could
            # bind one vehicle's VIN to a different vehicle's fields.
            for snippet in snippets[:6]:
                if isinstance(snippet, str) and snippet.strip():
                    results.append(SearchResult(row['url'][:2048], snippet[:16000]))
        return results
    except SearchError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise SearchError('Search provider response unavailable or malformed.') from None
