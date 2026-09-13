"""Opt-in, bounded live probes through the production fetcher; no bypasses.

Run from the repo: .venv/bin/python scripts/check_sources.py --live
Writes metadata only, never copies source pages into the repository.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app import fetch
from backend.app.extraction import extract, import_status

TARGETS = (
    ('carmax.com', 'https://www.carmax.com/car/70108828', 'listing'),
    ('carvana.com', 'https://www.carvana.com/vehicle/4711856?refSource=home', 'listing'),
    ('cargurus.com', 'https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action', 'inventory'),
    ('cars.com', 'https://www.cars.com/shopping/', 'inventory'),
    ('autotrader.com', 'https://www.autotrader.com/cars-for-sale', 'inventory'),
    ('carfax.com', 'https://www.carfax.com/cars-for-sale', 'inventory'),
    ('truecar.com', 'https://www.truecar.com/used-cars-for-sale/listings/', 'inventory'),
    ('edmunds.com', 'https://www.edmunds.com/used-cars-for-sale/', 'inventory'),
    ('kbb.com', 'https://www.kbb.com/cars-for-sale/', 'inventory'),
    ('autolist.com', 'https://www.autolist.com/', 'homepage'),
)

LISTING_PATHS = {
    'autotrader.com': r'/cars-for-sale/(?:vehicle/|vehicledetails)',
    'truecar.com': r'/used-cars-for-sale/listing/',
    'kbb.com': r'/cars-for-sale/(?:vehicle/|vehicledetails)',
    'autolist.com': r'/listings/',
}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly authorize ten live source probes')
    parser.add_argument('--domain', action='append', choices=[target[0] for target in TARGETS],
                        help='Only rerun selected domains; preserve other recorded results')
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live to make network requests')
    settings = Settings.from_env()
    if not settings.live_fetch_enabled:
        parser.error('REVRANK_LIVE_FETCH_ENABLED must be true')
    output = ROOT / 'docs' / 'source-tests'
    output.mkdir(parents=True, exist_ok=True)
    results = json.loads((output / 'results.json').read_text()) if args.domain and (output / 'results.json').exists() else []
    original_request = fetch.request_once
    for domain, url, kind in TARGETS:
        if args.domain and domain not in args.domain:
            continue
        row = dict(domain=domain, url=url, page_type=kind,
                   checked_at=datetime.now(timezone.utc).isoformat(), requests=[])
        def traced_request(request_url, *args, **kwargs):
            entry = {'url': request_url}
            row['requests'].append(entry)
            try:
                response = original_request(request_url, *args, **kwargs)
                entry.update(http_status=response.status, bytes=len(response.body))
                return response
            except fetch.FetchError as error:
                entry.update(error=error.message)
                raise
        fetch.request_once = traced_request
        start = time.monotonic()
        try:
            page = fetch.fetch_listing(url, settings)
            row.update(status='reachable', message='Page fetched; listing extraction not validated on this page type.')
            if kind != 'listing' and domain in LISTING_PATHS:
                links = Links()
                links.feed(page.text)
                listing_url = next((urljoin(page.url, href) for href in links.links
                                    if urlsplit(urljoin(page.url, href)).hostname == urlsplit(page.url).hostname
                                    and re.search(LISTING_PATHS[domain], urlsplit(urljoin(page.url, href)).path)), None)
                row['discovered_listing_url'] = listing_url
                if listing_url:
                    page = fetch.fetch_listing(listing_url, settings)
                    kind = 'listing'
                else:
                    row['message'] = 'Entry page fetched, but no matching individual listing link found. Listing import remains unvalidated.'
            if kind == 'listing':
                candidate, _ = extract(page.text, page.url, fetched=True)
                row.update(status=import_status(candidate),
                           message='Automated extraction only; field accuracy not independently verified.',
                           extracted_fields=[key for key in ('make', 'model', 'year', 'price', 'currency', 'mileage')
                                             if getattr(candidate, key) is not None],
                           warnings=candidate.warnings)
        except fetch.FetchError as error:
            row.update(status=error.status, message=error.message)
        finally:
            fetch.request_once = original_request
        row['elapsed_seconds'] = round(time.monotonic() - start, 2)
        results = [previous for previous in results if previous['domain'] != domain] + [row]
        lines = [f'# {domain}', '', f"Checked: {row['checked_at']}", '',
                 f'- URL: {url}', f'- Page type: {kind}',
                 f"- Result: **{row['status']}** — {row['message']}",
                 '- Enabled in local configuration; runtime access checks remain enforced.',
                 '- A single probe does not establish domain-wide coverage or reuse rights.', '',
                 '```json', json.dumps(row, indent=2), '```', '']
        (output / f'{domain}.md').write_text('\n'.join(lines))
        print(json.dumps(row), flush=True)
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
