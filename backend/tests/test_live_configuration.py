import pytest

from backend.app.config import Settings
from backend.app.fetch import FetchError, Response, fetch_listing


def test_env_enables_exact_domains(monkeypatch):
    monkeypatch.setenv('REVRANK_LIVE_FETCH_ENABLED', 'true')
    monkeypatch.setenv('REVRANK_ALLOWED_DOMAINS', 'www.carmax.com,www.carvana.com')
    settings = Settings.from_env()
    assert settings.live_fetch_enabled
    assert settings.allowed_domains == ('www.carmax.com', 'www.carvana.com')


def test_enabled_source_still_obeys_robots(monkeypatch):
    calls = []
    def request(url, *args):
        calls.append(url)
        return Response(200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow: /car/')
    monkeypatch.setattr('backend.app.fetch.request_once', request)
    settings = Settings(live_fetch_enabled=True, allowed_domains=('www.carmax.com',))
    with pytest.raises(FetchError, match='robots.txt disallows'):
        fetch_listing('https://www.carmax.com/car/70108828', settings)
    assert calls == ['https://www.carmax.com/robots.txt']


def test_enabled_source_reports_http_denial(monkeypatch):
    def request(url, *args):
        return Response(200, {'content-type': 'text/plain'}, b'User-agent: *\nAllow: /') if url.endswith('/robots.txt') else Response(403, {}, b'')
    monkeypatch.setattr('backend.app.fetch.request_once', request)
    settings = Settings(live_fetch_enabled=True, allowed_domains=('www.carmax.com',))
    with pytest.raises(FetchError, match='HTTP 403'):
        fetch_listing('https://www.carmax.com/car/70108828', settings)
