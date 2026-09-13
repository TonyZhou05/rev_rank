import os

import pytest

from backend.app.config import Settings
from backend.app.extraction import extract, import_status, money
from backend.app.fetch import FetchError, validated_url
from backend.app.sources import REGISTRY, source_for


def test_major_sources_are_explicitly_classified():
    settings = Settings()
    states = {domain: source_for(domain, settings)['status'] for domain, *_ in REGISTRY}
    assert states['caredge.com'] == 'restricted'
    assert states['cargurus.com'] == 'restricted'
    assert states['autotrader.com'] == 'unsupported'
    assert states['cars.com'] == 'unsupported'
    assert states['carfax.com'] == 'unsupported'
    assert states['truecar.com'] == 'unsupported'
    assert states['classic.com'] == 'unsupported'


def test_json_ld_fixture_extracts_evidence_without_network():
    raw = '''<html><script type="application/ld+json">{
      "@type":"Vehicle", "name":"2023 BMW M2", "brand":{"name":"BMW"},
      "model":"M2", "vehicleModelDate":"2023", "vehicleTransmission":"Manual",
      "mileageFromOdometer":{"value":12000,"unitCode":"SMI"},
      "offers":{"price":62000,"priceCurrency":"USD"}}
      </script></html>'''
    candidate, _ = extract(raw, 'https://example.test/listing', fetched=True)
    assert candidate.model == 'M2'
    assert candidate.price == 62000
    assert candidate.currency == 'USD'
    assert candidate.mileage == 12000
    assert candidate.evidence['price_type'].value == 'asking'
    assert import_status(candidate) == 'success'


def test_guarded_urls_reject_private_credentials_and_nonstandard_ports():
    for url in ('http://127.0.0.1/listing', 'http://localhost/listing', 'https://user:pass@example.com/x', 'https://example.com:8443/x'):
        try:
            validated_url(url)
        except FetchError:
            pass
        else:
            raise AssertionError(f'URL should be rejected: {url}')


def test_live_site_checks_are_opt_in():
    assert Settings().live_fetch_enabled is False

def test_configured_hosts_require_exact_match():
    settings = Settings(live_fetch_enabled=True, allowed_domains=('www.carmax.com',))
    assert source_for('www.carmax.com', settings)['status'] == 'allowed'
    assert source_for('unreviewed.carmax.com', settings)['status'] == 'unsupported'


@pytest.mark.parametrize("raw,expected", [("$71,998.", 71998), ("$71,998", 71998), ("$42,500.50", 42500.5),
                                           ("$29590.", 29590), ("$71,998.123", None), ("$1,23", None)])
def test_money_never_truncates_to_a_prefix(raw, expected):
    assert money(raw)[0] == expected
