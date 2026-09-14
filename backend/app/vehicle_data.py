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
from .usage import BudgetExceeded, spend

MARKETCHECK_URL = 'https://api.marketcheck.com/v2/search/car/active'
NEOVIN_URL = 'https://api.marketcheck.com/v2/decode/car/neovin/{vin}/specs'
VPIC_URL = 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}'
VIN = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')
# A NeoVIN decode reports several MSRP figures. Only these are the factory sticker for the car as
# built, in preference order. Bare `msrp` is often a weaker base figure, `build_specs_msrp` covers
# the build sheet alone, and a listing's inventory `msrp` frequently just repeats the asking price.
MSRP_FIELDS = ('oem_msrp', 'original_msrp', 'combined_msrp')
# `msrp` is used only when NeoVIN labels it as one of these and no named field contradicts it.
MSRP_LABELS = ('oem_msrp', 'original_msrp')
# Prefix of the evidence source string for a NeoVIN-sourced value; the UI and the compare gate read it.
NEOVIN_SOURCE = 'MarketCheck NeoVIN'


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
    body: str | None = None
    engine: str | None = None
    drivetrain: str | None = None
    fuel_type: str | None = None
    seller: str | None = None
    history_claims: tuple[str, ...] = ()
    last_seen: str | None = None
    # A6: Days-on-market from MarketCheck payload (0 extra paid calls)
    dom: int | None = None
    dom_active: int | None = None
    first_seen_at: str | None = None


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
    # car_location is where the car is; dealer is the selling rooftop. They differ for transfers and hubs.
    spot = row.get('car_location') if isinstance(row.get('car_location'), dict) else dealer
    year = build.get('year')
    year = year if isinstance(year, int) and not isinstance(year, bool) and 1886 <= year <= 2100 else None
    place = ', '.join(p for p in (text(spot.get('city'), 80), text(spot.get('state'), 20)) if p)
    # The provider marks these as "if mentioned on dealer website": seller claims, not a history report.
    claims = tuple(label for key, label in (('carfax_1_owner', 'one previous owner'),
                                            ('carfax_clean_title', 'clean title')) if row.get(key) is True)
    stock = row.get('stock_no')
    # Carvana rows carry 2147483647 (the 32-bit integer maximum) as a placeholder, not a real stock number.
    stock = str(stock)[:40] if isinstance(stock, (str, int)) and not isinstance(stock, bool) and str(stock) != '2147483647' else None
    # A6: Extract DOM fields from MarketCheck payload (no extra paid calls)
    dom_val = row.get('dom')
    dom = int(dom_val) if isinstance(dom_val, (int, float)) and not isinstance(dom_val, bool) and 0 <= dom_val <= 100000 else None
    dom_active_val = row.get('dom_active')
    dom_active = int(dom_active_val) if isinstance(dom_active_val, (int, float)) and not isinstance(dom_active_val, bool) and 0 <= dom_active_val <= 100000 else None
    first_seen = text(row.get('first_seen_at_date'), 40)

    return InventoryListing(
        vin=vin, source_url=source_url, stock_no=stock,
        heading=text(row.get('heading')), price=number(row.get('price')), miles=number(row.get('miles')),
        year=year, make=text(build.get('make'), 80), model=text(build.get('model'), 80),
        trim=text(build.get('trim'), 80), transmission=text(build.get('transmission'), 80),
        location=place or None, body=text(build.get('body_type'), 80), engine=text(build.get('engine'), 80),
        drivetrain=text(build.get('drivetrain'), 40), fuel_type=text(build.get('fuel_type'), 40),
        seller=text(dealer.get('name'), 120), history_claims=claims,
        last_seen=text(row.get('last_seen_at_date'), 40),
        dom=dom, dom_active=dom_active, first_seen_at=first_seen)


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
    try:
        spend(settings, 'marketcheck')
    except BudgetExceeded as error:
        raise ProviderError(str(error)) from None
    payload = get_json(MARKETCHECK_URL, params, timeout)
    rows = payload.get('listings') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProviderError('Provider response unavailable or malformed.')
    return [item for item in map(parse_listing, rows[:10]) if item]


@dataclass(frozen=True)
class NeoVinMsrp:
    """The one factory MSRP figure taken from a NeoVIN decode, with the field that carried it."""
    vin: str
    amount: float
    field: str
    # msrp_label, set only when the bare `msrp` field supplied the number.
    labeled_as: str | None = None

    @property
    def source(self) -> str:
        origin = f'msrp labeled {self.labeled_as}' if self.labeled_as else self.field
        return (f'{NEOVIN_SOURCE} {origin} for VIN {self.vin}; the factory MSRP of the car as built, '
                'not a listing or asking price')

    @property
    def source_url(self) -> str:
        # The endpoint without its key: MarketCheck authenticates with a query parameter.
        return NEOVIN_URL.format(vin=self.vin)


def msrp_from_specs(payload, vin: str) -> NeoVinMsrp | None:
    """Pick the one figure we are willing to call original MSRP, in MSRP_FIELDS order."""
    if not isinstance(payload, dict):
        return None
    for field in MSRP_FIELDS:
        amount = number(payload.get(field))
        if amount:
            return NeoVinMsrp(vin=vin, amount=amount, field=field)
    # No named figure, but NeoVIN labels the bare one as the OEM or original MSRP. When the named field
    # does carry a number, the loop above has already returned it, so nothing here can contradict it.
    label, amount = payload.get('msrp_label'), number(payload.get('msrp'))
    if amount and label in MSRP_LABELS:
        return NeoVinMsrp(vin=vin, amount=amount, field='msrp', labeled_as=label)
    return None


def decode_neovin_msrp(settings: Settings, vin: str, timeout: float = 8) -> NeoVinMsrp | None:
    """One paid NeoVIN decode of a known VIN; None when it reports no factory MSRP we can stand behind."""
    vin = vin.upper()
    if not VIN.fullmatch(vin):
        raise ValueError('Invalid VIN.')
    if not settings.marketcheck_enabled:
        raise ProviderError('Licensed VIN decode provider is not configured.')
    try:
        spend(settings, 'marketcheck')
    except BudgetExceeded as error:
        raise ProviderError(str(error)) from None
    payload = get_json(NEOVIN_URL.format(vin=vin), {'api_key': settings.marketcheck_api_key}, timeout, limit=2_000_000)
    if not isinstance(payload, dict):
        raise ProviderError('Provider response unavailable or malformed.')
    echoed = payload.get('vin')
    if isinstance(echoed, str) and echoed.strip().upper() not in ('', vin):
        raise ProviderError('The VIN decode describes a different vehicle.')
    return msrp_from_specs(payload, vin)


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
    transmission: str | None = None
    drivetrain: str | None = None
    fuel_type: str | None = None

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
    horsepower = text(row.get('EngineHP'), 10)
    engine = ' '.join(p for p in (
        displacement and re.fullmatch(r'\d+(?:\.\d+)?', displacement) and f'{float(displacement):.1f}L',
        cylinders and cylinders.isdigit() and f'{cylinders} cyl',
        horsepower and re.fullmatch(r'\d+(?:\.\d+)?', horsepower) and f'{float(horsepower):.0f} hp') if p)
    style, speeds = text(row.get('TransmissionStyle'), 60), text(row.get('TransmissionSpeeds'), 4)
    transmission = f'{speeds}-speed {style}' if style and speeds and speeds.isdigit() else style
    drive = text(row.get('DriveType'), 60)
    return VinDecode(vin=vin, year=year, make=make, model=text(row.get('Model'), 80), trim=text(row.get('Trim'), 80),
                     body=text(row.get('BodyClass'), 80), engine=engine or None,
                     problem=text(row.get('ErrorText'), 300) if codes - {'0'} else None,
                     transmission=transmission, drivetrain=drive.split('/')[-1] if drive else None,
                     fuel_type=text(row.get('FuelTypePrimary'), 40))
