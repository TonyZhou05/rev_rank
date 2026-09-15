"""Listing recovery with conservative identity binding and explicit disagreements.

Order: licensed inventory (structured, provider-dated) -> private browse of the buyer-supplied
VDP (rendered HTML) -> search excerpts (undated) -> NHTSA VIN decode. Browse runs only when
the feature flag is on, Direct was blocked/failed/thin, and MarketCheck missed or is
unavailable. A MarketCheck hit is never replaced by browse. Licensed and search do not
re-request the blocked page. Browse opens only that one user-supplied URL.
"""
from dataclasses import dataclass
import hashlib
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .browse import PASTE_HINT, BrowseError, browse_listing, browse_vdp_allowed
from .cancel import DISCONNECTED, TIMEOUT, CancelToken, Cancelled
from .config import Settings
from .dealer import from_listing as dealer_from_listing
from .extraction import apply_market_units, extract
from .fetch import FetchError, validated_url
from .listing_url import bare_host, identity_params, identity_url, is_listing_url, listing_id, normalize_input_url, same_listing, strip_tracking
from .models import Candidate, Evidence, ImportRequest, ImportResponse, Observation, RetrievalAttempt, now, value_text
from .search import search, SearchError
from .snippets import FOCUSED_QUERY, listed_date, single_vehicle_page, snippet_text
from .vehicle_data import InventoryListing, ProviderError, VinDecode, decode_neovin_msrp, decode_vin, inventory_search

VIN = re.compile(r'(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])', re.I)
FIELDS = ('make', 'model', 'year', 'trim', 'generation', 'price', 'currency', 'mileage',
          'mileage_unit', 'transmission', 'body', 'engine', 'drivetrain', 'fuel_type', 'location', 'features', 'history')
# The VIN encodes engine, drive type and fuel reliably; listings abbreviate them ("Engine: Gas").
# Transmission, trim and body stay listing-first: VINs often do not encode a manual gearbox or trim wording.
REGISTRY_PREFERRED = ('engine', 'drivetrain', 'fuel_type')
HISTORY_LABELS = {'direct': 'Seller-reported, not independently verified: ',
                  'browse': 'Seller-reported from a private browse of the listing you supplied, not independently verified: ',
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
    # A dated past listing (vininspect "Listed for sale on: 2026-08"): evidence of history, never today's values.
    historical: bool = False


def identity_seed(url: str):
    return bare_host(url), listing_id(url)


def budget(deadline: float, cap: float) -> float:
    return max(.1, min(cap, deadline - time.monotonic()))


def listing_candidate(row: InventoryListing, past: bool = False) -> Candidate:
    kind = 'Expired licensed inventory record' if past else 'Licensed inventory record'
    seen = f'provider last seen {row.last_seen or "date unknown"}'
    source = f'{kind} for {row.source_url}; {seen}{"; no longer in active inventory" if past else ""}'[:2000]
    candidate = Candidate(id=str(uuid4()), title=(row.heading or 'Licensed inventory listing')[:300],
                          source_kind='listing', source_url=row.source_url, retrieval_method='licensed',
                          # A6: DOM fields from MarketCheck payload (0 extra paid calls)
                          dom=row.dom, dom_active=row.dom_active, first_seen_at=row.first_seen_at,
                          # Dealer identity from the same payload; also 0 extra paid calls.
                          dealer=dealer_from_listing(row))
    values = dict(year=row.year, make=row.make, model=row.model, trim=row.trim, price=row.price,
                  mileage=row.miles, transmission=row.transmission, location=row.location, body=row.body,
                  engine=row.engine, drivetrain=row.drivetrain, fuel_type=row.fuel_type)
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
    # Only listing identity leaves the server: no zip codes, tracking or other query parameters.
    canonical = identity_url(url)
    seller_page = lambda row: same_listing(row.source_url, url)
    seller_stock = lambda row: row.stock_no == stock and bare_host(row.source_url) == host

    def lookup(label, usable, **query):
        """One paid lookup, reported by what it produced rather than by its HTTP outcome.

        `completed` means rows this listing can be built from. A provider that answered with nothing,
        or with nothing that is this car, is `not_found`: calling that completed made a dead end read
        as a step that had worked.
        """
        if time.monotonic() >= deadline:
            return []
        try:
            rows = inventory_search(settings, timeout=budget(deadline, 10), **query)
        except ProviderError as error:
            attempts.append(RetrievalAttempt(method='licensed', status='failed', detail=f'{label}: {error}'[:1000]))
            return []
        kept = [row for row in rows if usable(row)]
        detail = (f'{label}: {len(rows)} listings received, {len(kept)} matching this listing.' if kept
                  else f'{label}: {len(rows)} listings received, none of them this listing.' if rows
                  else f'{label}: the provider holds no listing under this identity.')
        attempts.append(RetrievalAttempt(method='licensed', status='completed' if kept else 'not_found', detail=detail))
        return rows

    # Each lookup is a paid call, so stop at the first one that finds the seller's own listing.
    # A known VIN goes first: one call returns the seller's record and its syndicated copies.
    # Copies are usable even when the seller's own page is not among them, so they count as a hit.
    rows = lookup('VIN lookup', lambda row: row.vin == target, vin=target) if target else []
    own = [r for r in rows if seller_page(r)]
    # Identity comes only from the seller's own listing: exact listing URL, else seller-scoped stock number.
    if not own:
        own = [r for r in lookup('Listing URL lookup', seller_page, vdp_url=canonical) if seller_page(r)]
    if not own and stock:
        own = [r for r in lookup('Seller stock lookup', seller_stock, stock_no=stock) if seller_stock(r)]
    # Active inventory drops a car the moment it stops being listed, so nothing above can find a
    # delisted listing. One scoped past-inventory call still binds its identity, and the buyer gets a
    # dated history instead of nothing. It is spent only when every active lookup came back empty.
    expired = []
    if not own and not rows and settings.past_inventory_enabled:
        expired = [r for r in lookup('Past inventory lookup', seller_page, vdp_url=canonical,
                                     source=host, past=True) if seller_page(r)]
    vins = {r.vin for r in own + expired}
    if len(vins) > 1:
        raise Stop('identity_conflict', 'Licensed inventory associates this listing with different VINs. Enter the correct VIN before recovery.')
    if vins and target and vins != {target}:
        raise Stop('identity_conflict', 'Licensed inventory lists a different VIN for this listing than the one supplied. Confirm vehicle identity.')
    # When the VIN came from the seller's record, no VIN lookup follows: syndicated copies are not worth a call.
    target = target or next(iter(vins), None)
    rows = own + expired + rows
    own_urls = {r.source_url for r in own + expired}
    gone = {r.source_url for r in expired}
    records, seen = [], set()
    for row in rows:
        if row.vin != target or row.source_url in seen:
            continue
        seen.add(row.source_url)
        records.append(Record(listing_candidate(row, past=row.source_url in gone), row.source_url, 'licensed',
                              row.last_seen, primary=row.source_url in own_urls or same_listing(row.source_url, url),
                              historical=row.source_url in gone))
    return records, target


SOLD = "The seller's indexed page says this vehicle is no longer available. This does not confirm a sale."
# Licensed inventory answered and held nothing under this listing's identity. The provider indexes
# active inventory, so a car that has stopped being listed simply drops out of it. That is a gap in
# coverage or a car that is gone, and neither is a sale.
LICENSED_MISS = ('Licensed inventory holds no active record of this listing, so it may already be sold or '
                 'removed. This does not confirm a sale.')
# Only the past-inventory endpoint had it. That endpoint also infers sales; RevRank does not read or
# repeat that inference, because a listing leaving the market is not evidence that it sold.
PAST_ONLY = ('Licensed inventory holds only an expired record of this listing: it has left active '
             'inventory, so it may be sold or removed. This does not confirm a sale. Its price and '
             'mileage are shown as a dated past listing, never as current values.')


def has_field(text: str, source_url: str, field: str) -> bool:
    candidate, _ = extract(snippet_text(text, source_url), source_url, fetched=True, loose=False)
    return getattr(candidate, field) is not None


def has_details(text: str, source_url: str) -> bool:
    candidate, _ = extract(snippet_text(text, source_url), source_url, fetched=True)
    # A title alone ("2014 Honda Civic") says nothing about this listing; stop only once its price or mileage is known.
    return any(getattr(candidate, field) is not None for field in ('price', 'mileage'))


def search_records(url, host, stock, target, request, settings, attempts, deadline):
    # Remove query strings before sending URLs to a third-party search service.
    canonical = strip_tracking(url).split('?')[0]
    def vin_queries(vin):
        return [f'"{vin}"', f'"{vin}" price']
    # Seller-scoped queries: an unscoped stock number or URL mostly matches unrelated pages.
    # A scheme-less quoted URL matches index entries more reliably than the full https://www form.
    listing = f'"{canonical.split("://", 1)[-1].removeprefix("www.")}"'
    # A path shared by every listing (identity in the query) is useless as a search phrase.
    plan = [f'"{stock}" {host}'] + ([] if identity_params(url) else [listing]) if stock else [listing]
    # Without a VIN, the listing's own indexed summary is the only evidence; its excerpt varies
    # between calls, so a third phrasing is tried only if the first two gave no vehicle details.
    if stock:
        plan.append(f'{stock}')
    queries = vin_queries(target) if target else plan
    known_vin = bool(target)
    bound, seen, per_host = [], set(), {}
    ambiguous = False
    removed = False
    focused = False
    for query_index in range(4):
        if query_index >= len(queries) or time.monotonic() >= deadline:
            break
        try:
            scoped = host if not target or queries[query_index] not in vin_queries(target) else None
            hits = search(queries[query_index], settings, timeout=min(10, deadline-time.monotonic()), domain=scoped)
        except SearchError as error:
            attempts.append(RetrievalAttempt(method='search', status='failed', detail=str(error)[:1000]))
            if not bound:
                # Carry the provider's own reason: an exhausted key or a rate limit is the operator's
                # to fix, and "search failed" alone sends the buyer looking for a listing problem.
                raise Stop('failed', f'Search could not recover this listing. {error} Paste the VIN and listing text.')
            break
        eligible, relevant = [], 0
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
            exact = same_listing(source_url, url)
            mentions = bool(stock and re.search(r'(?<!\w)' + re.escape(stock) + r'(?!\w)', hit.text)) or canonical in hit.text
            about = exact or mentions or bool(target and target in {v for v in vins})
            relevant += about
            if exact and not removed and re.search(r'no longer available|has been sold|vehicle you were interested in is not available', hit.text, re.I):
                removed = True
                attempts.append(RetrievalAttempt(method='search', status='removed', detail=SOLD))
            if len(vins) > 1 or (not vins and not exact):
                # Only pages about this listing can make its identity ambiguous; unrelated pages are noise.
                ambiguous = ambiguous or (len(vins) > 1 and about)
                continue
            vin = next(iter(vins), None)
            if vin and target and vin != target:
                ambiguous = ambiguous or about
                if not request.vin and stock and re.search(r'(?<!\d)' + re.escape(stock) + r'(?!\d)', hit.text) and source_host.removeprefix('www.') == host:
                    raise Stop('identity_conflict', 'The seller associates this stock number with different VINs. Confirm identity before continuing.')
                continue
            if vin and not target:
                stock_bound = bool(stock and re.search(r'(?<!\d)' + re.escape(stock) + r'(?!\d)', hit.text)
                                   and (source_host.removeprefix('www.') == host or host.split('.')[0].lower() in hit.text.lower()))
                if not stock_bound and canonical not in hit.text and not exact:
                    continue
            eligible.append((vin, source_url, hit.text, exact))
        attempts.append(RetrievalAttempt(method='search', status='completed',
                                         detail=f'Query {query_index + 1}: {len(hits)} excerpts, {relevant} about this listing.'))
        if not target:
            identities = {item[0] for item in eligible if item[0]}
            if len(identities) > 1:
                raise Stop('identity_conflict', 'Sources associate this listing with different VINs. Enter the correct VIN before recovery.')
            if identities:
                target = next(iter(identities))
                # The pending exact-URL query would only repeat this identity evidence.
                queries = queries[:query_index + 1] + vin_queries(target)
        for vin, source_url, text, exact in eligible:
            # The same card is repeated on many inventory pages: identical text adds nothing new.
            token = re.sub(r'\s+', ' ', text).strip()
            # Cap each site so one publisher's many pages cannot crowd out other sources; the focused query
            # was spent on exactly the missing field, so its results are not capped.
            capped = per_host.get(bare_host(source_url), 0) >= 3 and not (focused and query_index == len(queries) - 1)
            if (vin == target or (vin is None and exact)) and token not in seen and not capped:
                bound.append((source_url, text))
                seen.add(token)
                per_host[bare_host(source_url)] = per_host.get(bare_host(source_url), 0) + 1
        # Fixed VIN queries end the plan, plus at most one seller-focused query for a missing location;
        # never an open-ended research loop.
        if target and query_index == len(queries) - 1 and not focused and host in FOCUSED_QUERY and not any(
                has_field(text, source_url, 'location') for source_url, text in bound):
            queries.append(f'"{target}" {FOCUSED_QUERY[host]}')
            focused = True
        elif target and queries[query_index] in (vin_queries(target)[-1], f'"{target}" {FOCUSED_QUERY.get(host)}'):
            break
        if not target and any(has_details(text, source_url) for source_url, text in bound if not listed_date(text)):
            break
    if not bound:
        if removed:
            raise Stop('not_found', SOLD)
        # With the VIN already known, other VINs only mean nothing matched it.
        if ambiguous and not known_vin:
            raise Stop('identity_conflict', 'Pages about this listing name different or multiple vehicles. Confirm the VIN or paste the listing text.')
        raise Stop('not_found', 'Search found no page about this listing; it may be sold or not indexed. Enter its VIN or paste the listing text.')
    records = []
    for source_url, text in bound[:10]:
        # Unlabeled text ("2021 BMW M4s for sale", "23,163 miles") on a page listing many cars may describe the
        # page or a neighboring card: loose parsing only for single-vehicle pages (see snippets.py).
        candidate, _ = extract(snippet_text(text, source_url), source_url, fetched=True,
                               loose=single_vehicle_page(source_url, url, target))
        candidate = apply_market_units(candidate, source_url)
        # The seller's own pages outrank syndicated copies; a dated record keeps its date, others are unknown.
        dated = listed_date(text)
        records.append(Record(candidate, source_url, 'search', observed_at=dated, primary=bare_host(source_url) == host,
                              historical=bool(dated)))
    return records, target


CORE_FIELDS = ('year', 'make', 'model', 'price', 'mileage')
# Research checklist: listing fields only from a browsed VDP. History, options, and
# drivetrain copy stay off this path so browse cannot become a review-body scrape.
_BROWSE_EVIDENCE = frozenset((*CORE_FIELDS, 'trim', 'currency', 'mileage_unit', 'location',
                             'vin', 'stock_no', 'listing_id'))
_BROWSE_CLEAR = (
    'generation', 'transmission', 'body', 'engine', 'drivetrain', 'fuel_type',
    'features', 'history', 'msrp',
)


def _paste_detail(detail: str) -> str:
    text = (detail or '').strip()
    return text if PASTE_HINT in text else f'{text} {PASTE_HINT}'.strip()


def _listing_fields_only(candidate: Candidate) -> Candidate:
    """Keep YMMT, price, miles, location, and VIN evidence; drop the rest of the extract."""
    candidate.generation = None
    candidate.transmission = None
    candidate.body = None
    candidate.engine = None
    candidate.drivetrain = None
    candidate.fuel_type = None
    candidate.features = []
    candidate.history = None
    candidate.msrp = None
    candidate.dealer = None
    candidate.dom = None
    candidate.dom_active = None
    candidate.evidence = {key: value for key, value in candidate.evidence.items() if key in _BROWSE_EVIDENCE}
    return candidate


def browse_records(url, host, target, request, settings, attempts, token, deadline):
    """Open only the buyer-supplied listing URL; feed structured listing fields in as a primary record."""
    allowed, refused = browse_vdp_allowed(url)
    if not allowed:
        attempts.append(RetrievalAttempt(method='browse', status='refused', detail=_paste_detail(refused)[:1000]))
        return [], target
    if time.monotonic() >= deadline:
        attempts.append(RetrievalAttempt(method='browse', status='timeout',
                                         detail=_paste_detail('Private browse was not started; the import time limit had already been reached.')))
        return [], target
    try:
        page = browse_listing(url, settings, token=token, timeout=budget(deadline, settings.browser_timeout_seconds))
    except Cancelled as stop:
        attempts.append(RetrievalAttempt(
            method='browse', status='timeout' if stop.reason == TIMEOUT else 'cancelled',
            detail=_paste_detail('Private browse was stopped because the request was cancelled or ran out of time.')))
        if stop.reason == DISCONNECTED:
            raise
        return [], target
    except BrowseError as error:
        attempts.append(RetrievalAttempt(method='browse', status=error.status, detail=_paste_detail(error.message)[:1000]))
        return [], target
    except FetchError as error:
        attempts.append(RetrievalAttempt(method='browse', status=error.status, detail=_paste_detail(error.message)[:1000]))
        return [], target
    digest = hashlib.sha256(page.text.encode('utf-8', errors='replace')).hexdigest()[:16]
    candidate, _ = extract(page.text, page.url, fetched=True)
    candidate = _listing_fields_only(apply_market_units(candidate, page.url))
    if any(w.startswith(('Conflicting vin:', 'Multiple structured products found')) for w in candidate.warnings):
        attempts.append(RetrievalAttempt(
            method='browse', status='failed',
            detail=_paste_detail('The browsed page shows several vehicles, so none of its details were used for this listing.')))
        return [], target
    vin_ev = candidate.evidence.get('vin')
    page_vin = vin_ev.value.upper() if vin_ev else None
    if page_vin and target and page_vin != target:
        raise Stop('identity_conflict', 'The listing page VIN differs from the VIN you entered. Confirm vehicle identity.')
    if page_vin:
        target = page_vin
    if not any(getattr(candidate, field) is not None for field in CORE_FIELDS):
        attempts.append(RetrievalAttempt(
            method='browse', status='not_found',
            detail=_paste_detail('Private browse opened the listing but found no year, make, model, price or mileage.')))
        return [], target
    stock = listing_id(request.url) or listing_id(page.url)
    if stock and 'stock_no' not in candidate.evidence:
        candidate.evidence['stock_no'] = Evidence(
            value=stock, source='Listing identity in the URL you supplied', status='extracted')
    observed = now()
    for evidence in candidate.evidence.values():
        evidence.source = (
            f'user_vdp_browse of {page.url} at {observed}; content_hash={digest}; '
            f'seller-reported, not independently verified. {evidence.source}'
        )[:2000]
    candidate.retrieval_method = 'browse'
    candidate.source_kind = 'listing'
    candidate.source_url = request.url
    attempts.append(RetrievalAttempt(
        method='browse', status='completed',
        detail=f'user_vdp_browse extracted listing fields from {page.url} at {observed}; content_hash={digest}.'))
    return [Record(candidate, page.url, 'browse', primary=True)], target


def attach_original_msrp(candidate: Candidate | None, vin: str | None, settings: Settings,
                         attempts: list[RetrievalAttempt], timeout: float = 8) -> Candidate | None:
    """Fill Original MSRP from one NeoVIN decode of a bound VIN.

    A listing's own MSRP is unreliable (it often repeats the asking price), so the factory figure comes
    from the licensed VIN decode instead. It is a sourced suggestion, not a verified fact: the buyer can
    still change it on the review page, and a value already on the candidate is never overwritten.
    """
    if candidate is None or not vin or not settings.neovin_msrp_enabled:
        return candidate
    # One decode per VIN: an MSRP the buyer entered, or one an earlier step already decoded, stands.
    if candidate.msrp is not None or 'msrp' in candidate.evidence:
        return candidate
    try:
        found = decode_neovin_msrp(settings, vin, timeout=timeout)
    except (ProviderError, ValueError) as error:
        attempts.append(RetrievalAttempt(method='licensed', status='failed', detail=f'NeoVIN MSRP decode: {error}'[:1000]))
        return candidate
    if found is None:
        attempts.append(RetrievalAttempt(method='licensed', status='not_found',
                                         detail='NeoVIN decode reported no OEM, original or combined MSRP for this VIN.'))
        return candidate
    candidate.msrp = found.amount
    candidate.evidence['msrp'] = Evidence(value=value_text(found.amount), source=found.source, status='extracted')
    candidate.observations = (candidate.observations + [Observation(
        field='msrp', value=value_text(found.amount), source_url=found.source_url, retrieved_at=now(),
        method='licensed', vin=found.vin)])[:150]
    attempts.append(RetrievalAttempt(method='licensed', status='completed',
                                     detail=f'NeoVIN decode reported {found.field} {found.amount:,.0f} as the original MSRP.'))
    return candidate


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


def registry_build(decoded: VinDecode | None) -> dict:
    # Build details the VIN encodes; listing wording differs ("Stingray 3LT" vs "Premium 3LT"),
    # so these fill gaps but never create conflicts.
    if not decoded:
        return {}
    return {k: v for k, v in (('trim', decoded.trim), ('transmission', decoded.transmission), ('body', decoded.body),
                              ('engine', decoded.engine), ('drivetrain', decoded.drivetrain), ('fuel_type', decoded.fuel_type))
            if v is not None}


def recover_listing(request: ImportRequest, settings: Settings, original: ImportResponse,
                    token: CancelToken | None = None) -> ImportResponse:
    result = original.model_copy(deep=True)
    def finish(status, detail):
        result.recovery_status = status
        result.attempts.append(RetrievalAttempt(method='recovery', status=status, detail=detail))
        result.message += ' ' + detail
        return result
    if not request.recover:
        return finish('disabled', 'Recovery was disabled for this import.')
    if token is not None:
        try:
            token.check()
        except Cancelled as stop:
            if stop.reason == DISCONNECTED:
                raise
            return finish('failed', 'Import ran out of time before recovery could start.')
    target = request.vin
    single = original.candidate and not any(w.startswith(('Conflicting vin:', 'Multiple structured products found')) for w in original.candidate.warnings)
    if not target and single and original.candidate.evidence.get('vin'):
        target = original.candidate.evidence['vin'].value.upper()
    # A known VIN can still be decoded when no listing source is configured or none matches.
    identity_only = bool(target and settings.vin_decode_enabled)
    source = request.recovery_source
    use_licensed = settings.marketcheck_enabled and source in ('auto', 'marketcheck')
    browse_configured = settings.browser_recovery_enabled and source in ('auto', 'browse')
    # Research checklist: browse only after Direct fail and a MarketCheck miss/unavailable.
    # Restricted/unsupported stay Direct-policy misses. Explicit `browse` source skips MC.
    thin_or_blocked = original.status in ('blocked', 'failed', 'partial')
    use_browse = browse_configured and (source == 'browse' or thin_or_blocked)
    use_search = settings.search_enabled and source in ('auto', 'search')
    if source != 'auto' and not (use_licensed or use_search or browse_configured):
        if source == 'browse':
            name = 'private browser (REVRANK_BROWSER_RECOVERY_ENABLED)'
        elif source == 'marketcheck':
            name = 'MarketCheck (REVRANK_MARKETCHECK_API_KEY)'
        else:
            name = 'Search (REVRANK_SEARCH_PROVIDER and REVRANK_SEARCH_API_KEY)'
        return finish('unavailable', f'The selected recovery source, {name}, is not configured on the server. Choose another source.')
    if not (settings.search_enabled or settings.marketcheck_enabled or identity_only or settings.browser_recovery_enabled):
        return finish('unavailable', 'Recovery needs a licensed inventory key (REVRANK_MARKETCHECK_API_KEY), a search provider key (REVRANK_SEARCH_PROVIDER and REVRANK_SEARCH_API_KEY), or REVRANK_BROWSER_RECOVERY_ENABLED=true for a private browse of the listing you supplied. With REVRANK_VIN_DECODE_ENABLED=true, entering the VIN also recovers year/make/model.')
    raw = normalize_input_url(request.url)
    try:
        validated_url(raw)
    except FetchError:
        return finish('disabled', 'Invalid or private input URLs are not sent to recovery providers.')
    # The raw URL keeps fragment identity (CarGurus "#listing=") that validation strips.
    url = raw
    if is_listing_url(url) is False and not request.vin:
        # A marketplace search or model page lists many cars; recovering it would pick one at random.
        return finish('not_listing', "This link is a search or category page, not one car's listing. "
                                     "Open the car's own listing page on the site and paste that link.")
    host, stock = identity_seed(url)
    if token is not None and token.timeout:
        left = token.remaining()
        if left < 1:
            return finish('failed', 'Import ran out of time before recovery could start.')
        deadline = time.monotonic() + left
    else:
        deadline = time.monotonic() + 30
    records = []
    # What licensed inventory answered, kept for the outcome message. Without it a later search
    # failure is all the buyer reads, and a licensed lookup that held nothing reads as progress.
    preface = ''
    try:
        if use_licensed:
            records, target = licensed_records(url, host, stock, target, settings, result.attempts, deadline)
        if not records:
            licensed_failed = any(a.method == 'licensed' and a.status == 'failed' for a in result.attempts)
            licensed_used = use_licensed
            if use_browse:
                if licensed_used and not licensed_failed:
                    preface = LICENSED_MISS + ' '
                records, target = browse_records(url, host, target, request, settings, result.attempts, token, deadline)
            if not records:
                browse_attempt = next((a for a in reversed(result.attempts) if a.method == 'browse'), None)
                if use_search:
                    if licensed_used and not licensed_failed:
                        preface = LICENSED_MISS + ' '
                    records, target = search_records(url, host, stock, target, request, settings, result.attempts, deadline)
                elif licensed_failed:
                    raise Stop('failed', _paste_detail('Licensed inventory lookup failed.'))
                elif use_licensed and not use_browse:
                    raise Stop('not_found', _paste_detail(LICENSED_MISS))
                elif use_browse:
                    status = browse_attempt.status if browse_attempt else 'not_found'
                    detail = _paste_detail(browse_attempt.detail if browse_attempt else 'Private browse found no listing details.')
                    if status in ('blocked', 'failed', 'timeout', 'cancelled'):
                        raise Stop('failed', detail)
                    raise Stop('not_found', detail)
    except Stop as stop:
        # An identity conflict is about which car this is, not about who holds a record of it.
        detail = preface + stop.detail if stop.status in ('not_found', 'failed') else stop.detail
        if not (identity_only and stop.status in ('not_found', 'failed')):
            return finish(stop.status, detail)
        result.attempts.append(RetrievalAttempt(method='recovery', status=stop.status, detail=detail))

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
    build = registry_build(decoded)
    core = ('year', 'make', 'model', 'price', 'mileage')
    removed = any(a.status == 'removed' for a in result.attempts)
    if not official and not any(getattr(r.candidate, f) is not None for r in records for f in core):
        return finish('not_found', SOLD if removed else "The listing's indexed page was found but its excerpt had no vehicle details. "
                                                          'Try Refresh, enter the VIN, or paste the listing text.')
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
        specs = {**official, **build}
        observations.extend(Observation(field=field, value=value_text(value)[:1000], source_url=decoded.source_url,
                                        retrieved_at=now(), method='registry', vin=target)
                            for field, value in specs.items() if value is not None)
    licensed = any(r.method == 'licensed' for r in records)
    browsed = any(r.method == 'browse' for r in records)
    merged = Candidate(id=str(uuid4()), title='Recovered vehicle — review details', source_kind='listing',
                       source_url=request.url,
                       retrieval_method='licensed' if licensed else 'browse' if browsed else 'search' if records else 'registry',
                       observations=observations[:150])
    if target:
        merged.evidence['vin'] = Evidence(value=target, source='Exact VIN bound to this listing by user input, seller listing, or seller/stock association', status='extracted')
    stock_ev = next((r.candidate.evidence['stock_no'] for r in records
                     if r.method == 'browse' and 'stock_no' in r.candidate.evidence), None)
    if stock_ev:
        merged.evidence['stock_no'] = stock_ev
    merged.evidence['price_type'] = Evidence(value='asking', source='Listing evidence; not a transaction', status='extracted')
    history_method = None
    for field in FIELDS:
        options = [(r, getattr(r.candidate, field), r.candidate.evidence[field]) for r in records if not r.historical
                   and field in r.candidate.evidence and getattr(r.candidate, field) not in (None, [], 'UNK')]
        values = {value_text(v) for _, v, _ in options}
        primary_values = {value_text(v) for r, v, _ in options if r.primary}
        # Only records that may supply today's value can make it disputed; dated history cannot.
        warned = any(any(w.startswith(f'Conflicting {field}:') for w in r.candidate.warnings) for r in records if not r.historical)
        registry = official.get(field, build.get(field))
        if field == 'mileage' and options:
            # An odometer only goes up. Show the seller's reading (the site the user pasted): the one most of its
            # excerpts agree on, the higher on a tie, so a single leaked neighbor card cannot win. A lower
            # reading elsewhere is just older; only a higher one is reported as a disagreement.
            seller = [(r, v, e) for r, v, e in options if r.primary]
            pool = seller or options
            support = {float(v): sum(float(o[1]) == float(v) for o in pool) for _, v, _ in pool}
            record, value, evidence = max(pool, key=lambda o: (support[float(o[1])], float(o[1])))
            merged.mileage = value
            merged.evidence['mileage'] = Evidence(value=value_text(value), source=evidence.source[:2000], status=evidence.status)
            higher = sorted({float(v) for r, v, _ in options if float(v) > float(value)})
            if higher:
                merged.conflicts.append('mileage')
                merged.warnings.append(f"Conflicting mileage: another source reports {higher[-1]:,.0f}, higher than the "
                                       f"{'seller' if seller else 'shown'} reading of {float(value):,.0f}. Confirm the current odometer.")
            continue
        if field in official and any(r.primary and not agrees(registry, v) for r, v, _ in options):
            # The seller's own data disagreeing with the VIN decode may mean the wrong VIN was bound.
            merged.conflicts.append(field)
            merged.warnings.append(f'Conflicting {field}: the NHTSA VIN decode reports {registry}, but the seller listing differs. Confirm the VIN and this value.')
        elif field in official and any(not agrees(registry, v) for _, v, _ in options):
            # Year, make and model are encoded in the VIN; a third-party page that disagrees is the likelier error.
            setattr(merged, field, registry)
            merged.evidence[field] = Evidence(value=value_text(registry), source=f'NHTSA vPIC decode of VIN {target}', status='extracted')
            others = sorted({value_text(v) for _, v, _ in options if not agrees(registry, v)})
            merged.warnings.append(f"Another source reports {field} {', '.join(others)[:200]}; showing the NHTSA VIN decode ({registry}). See source observations.")
        elif field in REGISTRY_PREFERRED and registry is not None:
            setattr(merged, field, registry)
            merged.evidence[field] = Evidence(value=value_text(registry), source=f'NHTSA vPIC decode of VIN {target}', status='extracted')
        elif warned or (len(values) > 1 and len(primary_values) != 1):
            merged.conflicts.append(field)
            merged.warnings.append(f'Conflicting {field}: source observations disagree; value withheld until reviewed.')
        elif options:
            record, value, evidence = next((o for o in options if o[0].primary), options[0]) if primary_values else options[0]
            setattr(merged, field, value)
            suffix = '; matches NHTSA VIN decode' if field in official else ''
            merged.evidence[field] = Evidence(value=value_text(value), source=(evidence.source + suffix)[:2000], status=evidence.status)
            if field == 'history':
                history_method = record.method
            if len(values) > 1:
                merged.warnings.append(f"Other sources report a different {field}; showing the seller listing's value. See source observations.")
        elif registry is not None:
            setattr(merged, field, registry)
            merged.evidence[field] = Evidence(value=value_text(registry), source=f'NHTSA vPIC decode of VIN {target}', status='extracted')
    if merged.price is None and 'price' not in merged.conflicts:
        # No current price anywhere: the latest dated past listing is context for the buyer, never the price.
        past = sorted((r for r in records if r.historical and r.candidate.price is not None), key=lambda r: r.observed_at or '')
        if past:
            latest = past[-1]
            merged.evidence['last_listed_price'] = Evidence(
                value=f'${latest.candidate.price:,.0f} ({latest.observed_at})', status='extracted',
                source=f'{latest.source_url} · listed for sale {latest.observed_at}; a past listing, not the current price')
            merged.warnings.append(f'No current price was found. A past listing shows {latest.candidate.price:,.0f} in {latest.observed_at} '
                                   f'({bare_host(latest.source_url)}); confirm the current price with the seller.')
    # Coupled numeric fields are unusable when their units disagree.
    if 'currency' in merged.conflicts:
        merged.price = None
    if 'mileage_unit' in merged.conflicts:
        merged.mileage = None
    # The dealer block travels with the seller's own licensed record only. A syndicated copy of the
    # same VIN may name a marketplace rather than the selling rooftop, so it leaves the block null
    # instead of attributing the car to the wrong business.
    seller_record = next((r for r in records if r.method == 'licensed' and r.primary and not r.historical
                          and r.candidate.dealer), None)
    if seller_record:
        merged.dealer = seller_record.candidate.dealer
    merged.title = ' '.join(str(getattr(merged, f)) for f in ('year', 'make', 'model', 'trim') if getattr(merged, f)) or merged.title
    methods = {r.method for r in records}
    merged.warnings.append('Recovery supplemented a blocked or incomplete direct import; see original retrieval attempts.')
    if not records:
        merged.warnings.append('Only the NHTSA VIN decode succeeded. It identifies the vehicle build, not this listing; enter price, mileage, and condition from the listing.')
    expired_only = bool(records) and all(r.historical for r in records)
    if expired_only:
        merged.warnings.append(PAST_ONLY)
    elif 'licensed' in methods:
        merged.warnings.append("Licensed inventory values are dated by the provider's last-seen time, not a live availability check. Confirm price and availability with the seller.")
    if 'browse' in methods:
        merged.warnings.append('Private browse opened only the listing URL you supplied. It is not a live availability check, and an access challenge is reported as blocked rather than bypassed.')
    if 'search' in methods:
        merged.warnings.append('Search observation dates are unknown. Price, availability, and seller history require current confirmation.')
    if len(records) > 1:
        merged.warnings.append('Multiple sources may repeat one seller feed; they are not independent confirmations.')
    if removed:
        merged.warnings.append(SOLD)
    if not target:
        if 'browse' in methods:
            merged.warnings.append('VIN unknown: identity rests on a private browse of the listing URL you supplied. Enter the VIN to cross-check the vehicle.')
        else:
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
    # The bound VIN unlocks the factory MSRP; the recovery-source switch still decides who may be called.
    # An expired-only recovery has no price for an MSRP to be a percentage of, so it does not buy the decode.
    if use_licensed and not expired_only:
        attach_original_msrp(merged, target, settings, result.attempts, timeout=budget(deadline, 8))
    result.candidate = merged
    result.status = 'partial'
    if not records:
        result.recovery_status = 'identity_only'
        result.message = 'Recovered year/make/model from the NHTSA VIN decode only. Enter the listing price, mileage, and condition before comparing.'
        return result
    result.recovery_status = 'recovered'
    if expired_only:
        # Identity and a dated history, but nothing current. Say that before the buyer reads a price.
        result.message = ('Recovered this vehicle from an expired licensed inventory record: it has left active '
                          'inventory, which does not confirm a sale. Nothing here is a current price or mileage; '
                          'enter them from the seller, or paste the listing text.')
        return result
    found = 'matching VIN evidence' if target else "the listing you supplied (VIN unknown)"
    if licensed:
        origin = 'licensed inventory'
    elif browsed:
        origin = 'a private browse of the listing you supplied'
    else:
        origin = 'search'
    result.message = (f'Recovered {found} from {origin}. '
                      'Review sources, conflicts, and dates before comparing.')
    return result
