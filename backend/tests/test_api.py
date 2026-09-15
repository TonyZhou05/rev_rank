from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

def test_health_and_demo():
    assert client.get('/api/health').json()['status'] == 'ok'
    # The frontend compares this with API_REVISION in frontend/src/api.ts to detect a stale API process.
    assert client.get('/api/health').json()['api_revision'] == 10
    import pathlib, re
    page = (pathlib.Path(__file__).resolve().parents[2] / 'frontend/src/api.ts').read_text()
    assert re.search(r'API_REVISION = (\d+)', page).group(1) == '10'
    assert len(client.get('/api/demo').json()['candidates']) == 3

def test_pasted_text_and_compare():
    a = client.post('/api/import', json={'text': '2023 BMW M2\nPrice: $58,500 USD\nMileage: 18,000 miles\nTransmission: manual\nLocation: Austin, TX'}).json()
    b = client.post('/api/import', json={'text': '2022 Toyota GR Supra\nPrice: $52,900 USD\nMileage: 24,000 miles\nTransmission: automatic\nLocation: Dallas, TX'}).json()
    assert a['candidate']['model'] == 'M2'
    assert b['candidate']['model'] == 'GR Supra'
    body = {'candidates': [a['candidate'], b['candidate']], 'preferences': {'annual_mileage': 12000, 'ownership_years': 3, 'location': 'Austin, TX', 'priorities': ['performance'], 'must_haves': []}}
    report = client.post('/api/compare', json=body)
    assert report.status_code == 200
    assert report.json()['analysis_mode'] == 'rules'
    assert 'asking prices' in report.json()['warnings'][0]

def test_unapproved_url_is_truthfully_restricted(monkeypatch):
    from backend.app.config import Settings
    monkeypatch.setattr('backend.app.main.settings', Settings())
    result = client.post('/api/import', json={'url': 'https://www.cargurus.com/example'}).json()
    assert result['status'] == 'restricted'
    assert result['candidate'] is None

def test_paste_with_reference_url_never_fetches(monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        raise AssertionError('Pasted text must not trigger a website request')

    monkeypatch.setattr('backend.app.main.fetch_listing', unexpected_fetch)
    result = client.post('/api/import', json={
        'url': 'https://www.example.com/listing',
        'text': '2023 BMW M2\nPrice: $58,500 USD\nMileage: 18,000 miles',
    }).json()
    assert result['candidate']['model'] == 'M2'
    assert result['candidate']['source_kind'] == 'user'
    assert result['candidate']['source_url'] == 'https://www.example.com/listing'
    assert 'no website was fetched' in result['message']


LIVE_DEMO_PREFS = {
    'budget': 50000, 'must_haves': ['manual'], 'priorities': ['reliability', 'fun'],
    'annual_mileage': 12000, 'ownership_years': 3, 'location': '',
}


def test_three_demo_candidates_compare():
    cars = client.get('/api/demo').json()['candidates']
    assert len(cars) == 3
    report = client.post('/api/compare', json={
        'candidates': cars,
        'preferences': {'annual_mileage': 12000, 'ownership_years': 3, 'location': '',
                        'priorities': ['Lower asking price', 'Lower mileage'], 'must_haves': []},
    })
    assert report.status_code == 200
    assert report.headers.get('content-type', '').startswith('application/json')
    body = report.json()
    assert len(body['candidates']) == 3
    assert body['analysis_mode'] == 'rules'


def test_three_demo_compare_with_the_live_failing_preferences():
    """Render 500: all three /api/demo cars plus budget 50k, must-have manual, reliability/fun."""
    cars = client.get('/api/demo').json()['candidates']
    report = client.post('/api/compare', json={'candidates': cars, 'preferences': LIVE_DEMO_PREFS})
    assert report.status_code == 200
    assert 'application/json' in report.headers.get('content-type', '')
    body = report.json()
    assert len(body['candidates']) == 3
    assert any(e['conflicts'] for e in body['shortlist'])


def test_compare_keeps_the_report_when_analyst_crashes(monkeypatch):
    from backend.app import main

    def boom(*args, **kwargs):
        raise RuntimeError("analyst exploded")

    monkeypatch.setattr(main, "analyze", boom)
    cars = client.get('/api/demo').json()['candidates']
    report = client.post('/api/compare', json={
        'candidates': cars,
        'preferences': {'annual_mileage': 12000, 'ownership_years': 3, 'must_haves': []},
    })
    assert report.status_code == 200
    body = report.json()
    assert body['analysis_mode'] == 'rules'
    assert body['ai_analysis']['status'] == 'unavailable'
    assert 'failed' in body['ai_analysis']['message'].lower()
    assert len(body['candidates']) == 3


def test_compare_500_is_json_when_the_comparison_itself_crashes(monkeypatch):
    from backend.app import main

    def boom(*args, **kwargs):
        raise RuntimeError("comparison exploded")

    monkeypatch.setattr(main, "create_report", boom)
    cars = client.get('/api/demo').json()['candidates']
    report = client.post('/api/compare', json={
        'candidates': cars[:2],
        'preferences': {'annual_mileage': 12000, 'ownership_years': 3, 'must_haves': []},
    })
    assert report.status_code == 500
    assert 'application/json' in report.headers.get('content-type', '')
    detail = report.json()['detail']
    assert isinstance(detail, str) and detail
    assert '8000' not in detail


def test_uncaught_api_errors_are_json_not_plain_text(monkeypatch):
    """Starlette's default 500 is text/plain; the page then shows the port-8000 copy."""
    from backend.app import main

    def boom(*args, **kwargs):
        raise RuntimeError("sources exploded")

    monkeypatch.setattr(main, "sources_response", boom)
    with TestClient(app, raise_server_exceptions=False) as quiet:
        response = quiet.get('/api/sources')
    assert response.status_code == 500
    assert 'application/json' in response.headers.get('content-type', '')
    assert 'detail' in response.json()
    assert '8000' not in response.json()['detail']


def test_static_route_does_not_serve_files_outside_dist():
    import pytest
    from backend.app.main import DIST
    if not DIST.exists():
        pytest.skip('frontend/dist is not built, so the static route is not mounted')
    # The path parameter arrives percent-decoded, so these reach the handler as "../..".
    for path in ('/%2e%2e/package.json', '/%2e%2e/%2e%2e/AGENTS.md', '/..%2f..%2fAGENTS.md'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/html'), path
        assert 'Paid API budget' not in response.text and 'revrank-frontend' not in response.text
