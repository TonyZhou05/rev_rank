from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

def test_health_and_demo():
    assert client.get('/api/health').json()['status'] == 'ok'
    # The frontend compares this with API_REVISION in frontend/src/api.ts to detect a stale API process.
    assert client.get('/api/health').json()['api_revision'] == 4
    import pathlib, re
    page = (pathlib.Path(__file__).resolve().parents[2] / 'frontend/src/api.ts').read_text()
    assert re.search(r'API_REVISION = (\d+)', page).group(1) == '4'
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
