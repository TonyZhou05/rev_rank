"""Listing recovery with conservative identity binding and explicit disagreements.

Order: licensed inventory (structured, provider-dated) -> search excerpts (undated) ->
NHTSA VIN decode as an identity cross-check. None of these re-requests the blocked page.
"""
from dataclasses import dataclass
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .config import Settings
from .extraction import extract
from .fetch import FetchError, validated_url
from .models import Candidate, Evidence, ImportRequest, ImportResponse, Observation, RetrievalAttempt, now, value_text
from .search import search, SearchError
from .vehicle_data import InventoryListing, ProviderError, VinDecode, decode_vin, inventory_search

VIN = re.compile(r'(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])', re.I)
FIELDS = ('make', 'model', 'year', 'trim', 'generation', 'price', 'currency', 'mileage',
          'mileage_unit', 'transmission', 'location', 'features', 'history')
HISTORY_LABELS = {'direct': 'Seller-reported, not independently verified: ',
                  'licensed': 'Dealer-reported via licensed inventory, not independently verified: ',
                  'search': 'Search-reported, date unknown: '}


class Stop(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class Record:
    candidate: Candidate
    source_url: str
    method: str
    observed_at: str | None = None
    # The seller's own listing (fresh direct page or its licensed record) outranks syndicated copies.
    primary: bool = False


def identity_seed(url: str):
    parts = urlsplit(url)
    host = (parts.hostname or '').removeprefix('www.')
    pattern = {'carmax.com': r'^/car/(\d+)/?$', 'carvana.com': r'^/vehicle/(\d+)/?$'}.get(host)
    match = re.match(pattern, parts.path) if pattern else None
    return host, match.group(1) if match else None


def bare_host(url: str) -> str:
    return (urlsplit(url).hostname or '').removeprefix('www.')


def same_listing(a: str, b: str) -> bool:
    return bare_host(a) == bare_host(b) and urlsplit(a).path.rstrip('/') == urlsplit(b).path.rstrip('/')


def budget(deadline: float, cap: float) -> float:
    return max(.1, min(cap, deadline - time.monotonic()))


def listing_candidate(row: InventoryListing) -> Candidate:
    source = f'Licensed inventory record for {row.source_url}; provider last seen {row.last_seen or "date unknown"}'[:2000]
    candidate = Candidate(id=str(uuid4()), title=(row.heading or 'Licensed inventory listing')[:300],
                          source_kind='listing', source_url=row.source_url, retrieval_method='licensed')
    values = dict(year=row.year, make=row.make, model=row.model, trim=row.trim, price=row.price,
                  mileage=row.miles, transmission=row.transmission, location=row.location)
    # MarketCheck's default US market reports prices in USD and mileage in miles.
    if row.price is not None:
        values['currency'] = 'USD'
    if row.miles is not None:
        values['mileage_unit'] = 'mi'
    if row.history_claims:
        values['history'] = 'Dealer website states: ' + '; '.join(row.history_claims)
    for field, value in values.items():
        if value is None:
            continue
        try:
            setattr(candidate, field, value)
        except ValueError:
            continue
        candidate.evidence[field] = Evidence(value=value_text(value)[:4000], source=source,
                                             status='seller_claim' if field == 'history' else 'extracted')
    candidate.evidence['vin'] = Evidence(value=row.vin, source=source, status='extracted')
    return candidate


def licensed_records(url, host, stock, target, settings, attempts, deadline):
    canonical = url.split('?')[0]

    def lookup(label, **query):
        if time.monotonic() >= deadline:
            return []
        try:
            rows = inventory_search(settings, timeout=budget(deadline, 10), **query)
        except ProviderError as error:
            attempts.append(RetrievalAttempt(method='licensed', status='failed', detail=f'{label}: {error}'[:1000]))
            return []
        attempts.append(RetrievalAttempt(method='licensed', status='completed', detail=f'{label}: {len(rows)} listings received.'))
        return rows

    # Identity comes only from the seller's own listing: exact listing URL, else seller-scoped stock number.
    own = [r for r in lookup('Listing URL lookup', vdp_url=canonical) if same_listing(r.source_url, canonical)]
    if not own and stock:
        own = [r for r in lookup('Seller stock lookup', stock_no=stock)
               if r.stock_no == stock and bare_host(r.source_url) == host]
    vins = {r.vin for r in own}
    if len(vins) > 1:
        raise Stop('identity_conflict', 'Licensed inventory associates this listing with different VINs. Enter the correct VIN before recovery.')
    if vins and target and vins != {target}:
        raise Stop('identity_conflict', 'Licensed inventory lists a different VIN for this listing than the one supplied. Confirm vehicle identity.')
    target = target or next(iter(vins), None)
    rows = list(own)
    if target:
        rows += lookup('VIN lookup', vin=target)
    own_urls = {r.source_url for r in own}
    records, seen = [], set()
    for row in rows:
        if row.vin != target or row.source_url in seen:
            continue
        seen.add(row.source_url)
        records.append(Record(listing_candidate(row), row.source_url, 'licensed', row.last_seen,
                              primary=row.source_url in own_urls or same_listing(row.source_url, canonical)))
    return records, target


def snippet_text(text: str) -> str:
    # Strip common Markdown decoration without removing record boundaries.
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*]\s+)', '', text).replace('**', '')
    # Excerpts flatten "Label: value; Label: value." onto one line; the extractor reads one label per line.
    text = re.sub(r'\bCity, State\s*:', 'Location:', text)
    text = re.sub(r'\bAsking\s*(?=(?:US)?\$)', 'Price: ', text)
    lines = re.sub(r'[.;]\s+(?=[A-Z][A-Za-z ]{1,24}:)', '\n', text).split('\n')
    # Excerpts are cut mid-sentence; a trailing "Location: Madison," is a truncated value, not a fact.
    if len(lines) > 1 and lines[-1].rstrip().endswith((',', '...', '…')):
        lines.pop()
    return '\n'.join(lines)


def search_records(url, host, stock, target, request, settings, attempts, deadline):
    # Remove query strings before sending URLs to a third-party search service.
    canonical = url.split('?')[0]
    queries = [f'"{target}"'] if target else ([f'"{stock}" "{host}"', f'"{canonical}"'] if stock else [f'"{canonical}"'])
    bound, seen, per_host = [], set(), {}
    ambiguous = False
    for query_index in range(3):
        if query_index >= len(queries) or time.monotonic() >= deadline:
            break
        try:
            hits = search(queries[query_index], settings, timeout=min(10, deadline-time.monotonic()))
        except SearchError as error:
            attempts.append(RetrievalAttempt(method='search', status='failed', detail=str(error)[:1000]))
            if not bound:
                raise Stop('failed', 'Search could not recover this listing. Paste the VIN and listing text.')
            break
        attempts.append(RetrievalAttempt(method='search', status='completed', detail=f'Query {query_index + 1}: {len(hits)} evidence excerpts received.'))
        eligible = []
        for hit in hits[:30]:
            try:
                source_url, _, _ = validated_url(hit.url)
            except FetchError:
                continue
            # No raw page fetching here. Exclude local-name references as well.
            source_host = urlsplit(source_url).hostname or ''
            if '.' not in source_host or source_host.endswith(('.local', '.internal', '.test')):
                continue
            vins = {v.upper() for v in VIN.findall(hit.text)}
            # The exact listing URL is the seller's own page as indexed: the URL binds identity even
            # without a VIN. Any other page must name exactly one VIN.
            exact = same_listing(source_url, canonical)
            if len(vins) > 1 or (not vins and not exact):
                ambiguous = ambiguous or len(vins) > 1
                continue
            vin = next(iter(vins), None)
            if vin and target and vin != target:
                ambiguous = True
                if not request.vin and stock and re.search(r'(?<!\d)' + re.escape(stock) + r'(?!\d)', hit.text) and source_host.removeprefix('www.') == host:
                    raise Stop('identity_conflict', 'The seller associates this stock number with different VINs. Confirm identity before continuing.')
                continue
            if vin and not target:
                stock_bound = bool(stock and re.search(r'(?<!\d)' + re.escape(stock) + r'(?!\d)', hit.text)
                                   and (source_host.removeprefix('www.') == host or host.split('.')[0].lower() in hit.text.lower()))
                if not stock_bound and canonical not in hit.text and not exact:
                    continue
            eligible.append((vin, source_url, hit.text, exact))
        if not target:
            identities = {item[0] for item in eligible if item[0]}
            if len(identities) > 1:
                raise Stop('identity_conflict', 'Sources associate this listing with different VINs. Enter the correct VIN before recovery.')
            if identities:
                target = next(iter(identities))
                queries.append(f'"{target}"')
        for vin, source_url, text, exact in eligible:
            token = (source_url, text)
            # Cap each site so one publisher's many inventory pages cannot crowd out other sources.
            if (vin == target or (vin is None and exact)) and token not in seen and per_host.get(bare_host(source_url), 0) < 3:
                bound.append((source_url, text))
                seen.add(token)
                per_host[bare_host(source_url)] = per_host.get(bare_host(source_url), 0) + 1
        # A VIN query is sufficient; never do an open-ended research loop.
        if target and queries[query_index] == f'"{target}"':
            break
    if not bound:
        if ambiguous:
            raise Stop('identity_conflict', 'Search evidence names different or multiple vehicles. Confirm the VIN or paste one listing only.')
        raise Stop('not_found', 'No unambiguous matching vehicle was found. Enter its VIN or paste listing text.')
    records = []
    for source_url, text in bound[:10]:
        candidate, _ = extract(snippet_text(text), source_url, fetched=True)
        records.append(Record(candidate, source_url, 'search'))
    return records, target


def normalized(value) -> str:
    return re.sub(r'[^a-z0-9]', '', value_text(value).casefold())


def agrees(official, value) -> bool:
    # Registry names are coarser than listing names ("Camaro" vs "Camaro ZL1").
    a, b = normalized(official), normalized(value)
    return a == b or (bool(a) and bool(b) and (a.startswith(b) or b.startswith(a)))


def registry_values(decoded: VinDecode | None) -> dict:
    if not decoded:
        return {}
    return {k: v for k, v in (('year', decoded.year), ('make', decoded.make), ('model', decoded.model)) if v is not None}


def recover_listing(request: ImportRequest, settings: Settings, original: ImportResponse) -> ImportResponse:
    result = original.model_copy(deep=True)
    def finish(status, detail):
        result.recovery_status = status
        result.attempts.append(RetrievalAttempt(method='recovery', status=status, detail=detail))
        result.message += ' ' + detail
        return result
    if not request.recover:
        return finish('disabled', 'Recovery was disabled for this import.')
    target = request.vin
    if not target and original.candidate and original.candidate.evidence.get('vin'):
        target = original.candidate.evidence['vin'].value.upper()
    # A known VIN can still be decoded when no listing source is configured or none matches.
    identity_only = bool(target and settings.vin_decode_enabled)
    if not (settings.search_enabled or settings.marketcheck_enabled or identity_only):
        return finish('unavailable', 'Recovery needs a licensed inventory key (REVRANK_MARKETCHECK_API_KEY) or a search provider key (REVRANK_SEARCH_PROVIDER and REVRANK_SEARCH_API_KEY) on the server. With REVRANK_VIN_DECODE_ENABLED=true, entering the VIN also recovers year/make/model.')
    try:
        url, _, _ = validated_url(request.url or '')
    except FetchError:
        return finish('disabled', 'Invalid or private input URLs are not sent to recovery providers.')
    host, stock = identity_seed(url)
    deadline = time.monotonic() + 30
    records = []
    try:
        if settings.marketcheck_enabled:
            records, target = licensed_records(url, host, stock, target, settings, result.attempts, deadline)
        if not records:
            if settings.search_enabled:
                records, target = search_records(url, host, stock, target, request, settings, result.attempts, deadline)
            elif any(a.method == 'licensed' and a.status == 'failed' for a in result.attempts):
                raise Stop('failed', 'Licensed inventory lookup failed. Paste the VIN and listing text.')
            elif settings.marketcheck_enabled:
                raise Stop('not_found', 'No matching licensed inventory listing was found. Enter its VIN or paste listing text.')
    except Stop as stop:
        if not (identity_only and stop.status in ('not_found', 'failed')):
            return finish(stop.status, stop.detail)
        result.attempts.append(RetrievalAttempt(method='recovery', status=stop.status, detail=stop.detail))

    # Keep original direct evidence only when it independently names this VIN.
    # It participates in conflict detection; unbound partial pages cannot bleed in.
    if original.candidate and original.candidate.evidence.get('vin') and original.candidate.evidence['vin'].value.upper() == target:
        records.insert(0, Record(original.candidate, original.candidate.source_url or request.url, 'direct', primary=True))

    decoded = None
    if settings.vin_decode_enabled and target:
        try:
            decoded = decode_vin(target, timeout=budget(deadline, 8))
            result.attempts.append(RetrievalAttempt(method='registry', status='completed' if decoded else 'not_found',
                                                    detail='NHTSA VIN decode ' + ('returned vehicle identity.' if decoded else 'returned no make for this VIN.')))
        except ProviderError as error:
            result.attempts.append(RetrievalAttempt(method='registry', status='failed', detail=f'NHTSA VIN decode: {error}'[:1000]))
    official = registry_values(decoded)
    if not records and not official:
        failed = any(a.method == 'registry' and a.status == 'failed' for a in result.attempts)
        return finish('failed' if failed else 'not_found', 'No listing source or VIN decode identified this vehicle. Paste the listing text.')

    observations = []
    for record in records:
        for field in FIELDS:
            value = getattr(record.candidate, field)
            if field in record.candidate.evidence and value not in (None, [], 'UNK'):
                observations.append(Observation(field=field, value=value_text(value)[:1000], source_url=record.source_url,
                                                retrieved_at=now(), observed_at=record.observed_at, method=record.method, vin=target))
    if decoded:
        specs = {**official, 'trim': decoded.trim, 'body': decoded.body, 'engine': decoded.engine}
        observations.extend(Observation(field=field, value=value_text(value)[:1000], source_url=decoded.source_url,
                                        retrieved_at=now(), method='registry', vin=target)
                            for field, value in specs.items() if value is not None)
    licensed = any(r.method == 'licensed' for r in records)
    merged = Candidate(id=str(uuid4()), title='Recovered vehicle — review details', source_kind='listing',
                       source_url=request.url, retrieval_method='licensed' if licensed else 'search' if records else 'registry',
                       observations=observations[:150])
    if target:
        merged.evidence['vin'] = Evidence(value=target, source='Exact VIN bound to this listing by user input, seller listing, or seller/stock association', status='extracted')
    merged.evidence['price_type'] = Evidence(value='asking', source='Listing evidence; not a transaction', status='extracted')
    history_method = None
    for field in FIELDS:
        options = [(r, getattr(r.candidate, field), r.candidate.evidence[field]) for r in records
                   if field in r.candidate.evidence and getattr(r.candidate, field) not in (None, [], 'UNK')]
        values = {value_text(v) for _, v, _ in options}
        primary_values = {value_text(v) for r, v, _ in options if r.primary}
        warned = any(any(w.startswith(f'Conflicting {field}:') for w in r.candidate.warnings) for r in records)
        registry = official.get(field)
        if registry is not None and any(not agrees(registry, v) for _, v, _ in options):
            merged.conflicts.append(field)
            merged.warnings.append(f'Conflicting {field}: the NHTSA VIN decode reports {registry}, but a listing source differs. Confirm the VIN and this value.')
        elif warned or (len(values) > 1 and len(primary_values) != 1):
            merged.conflicts.append(field)
            merged.warnings.append(f'Conflicting {field}: source observations disagree; value withheld until reviewed.')
        elif options:
            record, value, evidence = next((o for o in options if o[0].primary), options[0]) if primary_values else options[0]
            setattr(merged, field, value)
            suffix = '; matches NHTSA VIN decode' if registry is not None else ''
            merged.evidence[field] = Evidence(value=value_text(value), source=(evidence.source + suffix)[:2000], status=evidence.status)
            if field == 'history':
                history_method = record.method
            if len(values) > 1:
                merged.warnings.append(f"Other sources report a different {field}; showing the seller listing's value. See source observations.")
        elif registry is not None:
            setattr(merged, field, registry)
            merged.evidence[field] = Evidence(value=value_text(registry), source=f'NHTSA vPIC decode of VIN {target}', status='extracted')
    # Coupled numeric fields are unusable when their units disagree.
    if 'currency' in merged.conflicts:
        merged.price = None
    if 'mileage_unit' in merged.conflicts:
        merged.mileage = None
    merged.title = ' '.join(str(getattr(merged, f)) for f in ('year', 'make', 'model', 'trim') if getattr(merged, f)) or merged.title
    methods = {r.method for r in records}
    merged.warnings.append('Recovery supplemented a blocked or incomplete direct import; see original retrieval attempts.')
    if not records:
        merged.warnings.append('Only the NHTSA VIN decode succeeded. It identifies the vehicle build, not this listing; enter price, mileage, and condition from the listing.')
    if 'licensed' in methods:
        merged.warnings.append("Licensed inventory values are dated by the provider's last-seen time, not a live availability check. Confirm price and availability with the seller.")
    if 'search' in methods:
        merged.warnings.append('Search observation dates are unknown. Price, availability, and seller history require current confirmation.')
    if len(records) > 1:
        merged.warnings.append('Multiple sources may repeat one seller feed; they are not independent confirmations.')
    if not target:
        merged.warnings.append("VIN unknown: identity rests on the listing URL's own indexed summary. Enter the VIN to cross-check the vehicle.")
    if decoded and decoded.problem:
        merged.warnings.append(f'NHTSA VIN decode flagged this VIN: {decoded.problem} Confirm the VIN.'[:1000])
    if merged.currency == 'UNK':
        merged.warnings.append('Currency is unknown; confirm before comparing prices.')
    if 'mileage_unit' not in merged.evidence:
        merged.warnings.append('Mileage unit is unconfirmed; mi is only the editor default.')
    # Source-reported history must never be promoted to current verification.
    if merged.history:
        merged.history = HISTORY_LABELS.get(history_method, HISTORY_LABELS['search']) + merged.history[:900]
        merged.evidence['history'].value = merged.history
    result.candidate = merged
    result.status = 'partial'
    if not records:
        result.recovery_status = 'identity_only'
        result.message = 'Recovered year/make/model from the NHTSA VIN decode only. Enter the listing price, mileage, and condition before comparing.'
        return result
    result.recovery_status = 'recovered'
    found = 'matching VIN evidence' if target else "the listing's indexed summary (VIN unknown)"
    result.message = (f'Recovered {found} from {"licensed inventory" if licensed else "search"}. '
                      'Review sources, conflicts, and dates before comparing.')
    return result
