"""Licensed inventory and VIN registry adapters. Provider output is evidence, never an instruction.

Fixed provider endpoints only. These are authorized data services, not a way to request a
blocked page: nothing here contacts the seller's website or reuses browser sessions.
"""
from dataclasses import dataclass
import json
from math import isfinite
import re
import time
import httpx

from .config import Settings
from .fetch import FetchError, validated_url

MARKETCHECK_URL = 'https://api.marketcheck.com/v2/search/car/active'
VPIC_URL = 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}'
VIN = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')


class ProviderError(Exception):
    pass


def get_json(url: str, params: dict, timeout: float, limit: int = 1_000_000):
    timeout = max(.1, min(timeout, 10))
    deadline = time.monotonic() + timeout
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(4, timeout)),
                          follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', url, params=params, headers={'Accept': 'application/json'}) as response:
                if response.status_code != 200:
                    raise ProviderError(f'Provider returned HTTP {response.status_code}.')
                chunks, size = [], 0
                for chunk in response.iter_bytes(chunk_size=8192):
                    size += len(chunk)
                    if size > limit or time.monotonic() >= deadline:
                        raise ProviderError('Provider exceeded response size or time limit.')
                    chunks.append(chunk)
        return json.loads(b''.join(chunks))
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError):
        # Never echo the request URL: MarketCheck authenticates with a query parameter.
        raise ProviderError('Provider response unavailable or malformed.') from None


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1_000_000_000:
        return None
    return value


def text(value, limit=300):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class InventoryListing:
    vin: str
    source_url: str
    stock_no: str | None = None
    heading: str | None = None
    price: float | None = None
    miles: float | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    transmission: str | None = None
    location: str | None = None
    seller: str | None = None
    history_claims: tuple[str, ...] = ()
    last_seen: str | None = None


def parse_listing(row) -> InventoryListing | None:
    if not isinstance(row, dict):
        return None
    vin = row.get('vin').upper() if isinstance(row.get('vin'), str) else ''
    if not VIN.fullmatch(vin) or not isinstance(row.get('vdp_url'), str):
        return None
    try:
        source_url, _, _ = validated_url(row['vdp_url'])
    except FetchError:
        return None
    build = row.get('build') if isinstance(row.get('build'), dict) else {}
    dealer = row.get('dealer') if isinstance(row.get('dealer'), dict) else {}
    year = build.get('year')
    year = year if isinstance(year, int) and not isinstance(year, bool) and 1886 <= year <= 2100 else None
    place = ', '.join(p for p in (text(dealer.get('city'), 80), text(dealer.get('state'), 20)) if p)
    # The provider marks these as "if mentioned on dealer website": seller claims, not a history report.
    claims = tuple(label for key, label in (('carfax_1_owner', 'one previous owner'),
                                            ('carfax_clean_title', 'clean title')) if row.get(key) is True)
    stock = row.get('stock_no')
    return InventoryListing(
        vin=vin, source_url=source_url, stock_no=str(stock)[:40] if isinstance(stock, (str, int)) and not isinstance(stock, bool) else None,
        heading=text(row.get('heading')), price=number(row.get('price')), miles=number(row.get('miles')),
        year=year, make=text(build.get('make'), 80), model=text(build.get('model'), 80),
        trim=text(build.get('trim'), 80), transmission=text(build.get('transmission'), 80),
        location=place or None, seller=text(dealer.get('name'), 120), history_claims=claims,
        last_seen=text(row.get('last_seen_at_date'), 40))


def inventory_search(settings: Settings, *, vin: str | None = None, vdp_url: str | None = None,
                     stock_no: str | None = None, timeout: float = 10) -> list[InventoryListing]:
    if not settings.marketcheck_enabled:
        raise ProviderError('Licensed inventory provider is not configured.')
    filters = {k: v for k, v in (('vin', vin), ('vdp_url', vdp_url), ('stock_no', stock_no)) if v}
    if len(filters) != 1:
        raise ValueError('Use exactly one identity filter.')
    # nodedup keeps syndicated copies visible; append_api_key=false keeps the key out of returned URLs.
    params = {'api_key': settings.marketcheck_api_key, 'rows': 10, 'nodedup': 'true',
              'append_api_key': 'false', **filters}
    payload = get_json(MARKETCHECK_URL, params, timeout)
    rows = payload.get('listings') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProviderError('Provider response unavailable or malformed.')
    return [item for item in map(parse_listing, rows[:10]) if item]


@dataclass(frozen=True)
class VinDecode:
    vin: str
    year: int | None
    make: str | None
    model: str | None
    trim: str | None
    body: str | None
    engine: str | None
    problem: str | None

    @property
    def source_url(self) -> str:
        return VPIC_URL.format(vin=self.vin) + '?format=json'


def decode_vin(vin: str, timeout: float = 8) -> VinDecode | None:
    vin = vin.upper()
    if not VIN.fullmatch(vin):
        raise ValueError('Invalid VIN.')
    payload = get_json(VPIC_URL.format(vin=vin), {'format': 'json'}, timeout, limit=200_000)
    rows = payload.get('Results') if isinstance(payload, dict) else None
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    if row is None:
        raise ProviderError('VIN decoder response unavailable or malformed.')
    make = text(row.get('Make'), 80)
    if not make:
        return None
    make = make.title() if len(make) > 3 else make
    year = row.get('ModelYear')
    year = int(year) if isinstance(year, str) and year.isdigit() and 1886 <= int(year) <= 2100 else None
    codes = {c.strip() for c in str(row.get('ErrorCode', '')).split(',') if c.strip()}
    displacement, cylinders = text(row.get('DisplacementL'), 10), text(row.get('EngineCylinders'), 4)
    engine = ' '.join(p for p in (
        displacement and re.fullmatch(r'\d+(?:\.\d+)?', displacement) and f'{float(displacement):.1f}L',
        cylinders and cylinders.isdigit() and f'{cylinders} cyl') if p)
    return VinDecode(vin=vin, year=year, make=make, model=text(row.get('Model'), 80), trim=text(row.get('Trim'), 80),
                     body=text(row.get('BodyClass'), 80), engine=engine or None,
                     problem=text(row.get('ErrorText'), 300) if codes - {'0'} else None)
