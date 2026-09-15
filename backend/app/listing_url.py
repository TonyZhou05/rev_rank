"""Normalize pasted listing URLs and read identity hints (VIN, listing id) from them.

Users paste URLs without a scheme, with surrounding text, tracking parameters, or identity in the
fragment. Everything here is parsing only; validation and fetching stay in fetch.py.
"""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
# A scheme-less "carmax.com/car/1": never the tail of another scheme ("ftp://") or of credentials ("user@").
BARE_URL = re.compile(r"(?<![\w.:/@-])(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s<>\"']*", re.I)
TRACKING = re.compile(r"^(?:utm_\w+|refsource|ref|referrer|source|gclid|fbclid|msclkid|mc_[ce]id|_ga|srsltid|campaign|cid)$", re.I)
# Query or fragment keys that identify one listing on sites whose path is shared by every listing.
IDENTITY_KEYS = {"listing": "listing", "inventorylisting": "listing", "listingid": "listing", "vehicleid": "listing",
                 "id": "listing", "vin": "vin"}
LISTING_ID = {
    "carmax.com": r"^/car/(\d+)/?$",
    "carvana.com": r"^/vehicle/(?:lt/)?(\d+)(?:/|$)",
    "autotrader.com": r"^/cars-for-sale/vehicle(?:details)?/(\d+)",
    "kbb.com": r"^/cars-for-sale/vehicle/(\d+)",
    "cars.com": r"^/vehicledetail/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
}
VIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}", re.I)
VIN_VALUES = {**{str(d): d for d in range(10)}, **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))),
              "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def normalize_input_url(raw: str | None) -> str:
    """First URL in the pasted text, with https:// added when the scheme is missing."""
    text = (raw or "").strip()
    trim = lambda url: url.rstrip(".,;:!?)]}>'\"")
    match = HTTP_URL.search(text)
    if match:
        return trim(match.group(0))
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        return text  # Another scheme: leave it for validation to reject, never rewrite it to https.
    match = BARE_URL.search(text)
    return "https://" + trim(match.group(0)) if match else text


def bare_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")


def identity_params(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    found = {}
    for key, value in parse_qsl(parts.query) + parse_qsl(parts.fragment):
        name = IDENTITY_KEYS.get(key.lower())
        if name and value.strip():
            found[name] = value.strip()
    return found


def strip_tracking(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def identity_url(url: str) -> str:
    """The URL without query or fragment, except listing-identity parameters (no zip codes or tracking)."""
    parts = urlsplit(url)
    identity = identity_params(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(identity.items())), ""))


def listing_key(url: str) -> tuple:
    """What makes two URLs the same listing: a recognized listing id on its site, otherwise host, path,
    and identity parameters (never tracking). "/vehicle/lt/123" and "/vehicle/123/" are one Carvana listing."""
    host = bare_host(url)
    if host in LISTING_ID and (found := listing_id(url)):
        return host, "id", (("listing", found.lower()),)
    return host, urlsplit(url).path.rstrip("/"), tuple(sorted(identity_params(url).items()))


def same_listing(a: str, b: str) -> bool:
    key_a, key_b = listing_key(a), listing_key(b)
    if key_a[:2] != key_b[:2]:
        return False
    # A shared path (CarGurus) matches only when both carry the same listing identity.
    return key_a[2] == key_b[2] or not (key_a[2] or key_b[2])


def listing_id(url: str) -> str | None:
    host = bare_host(url)
    pattern = LISTING_ID.get(host)
    match = re.match(pattern, urlsplit(url).path, re.I) if pattern else None
    return match.group(1) if match else identity_params(url).get("listing")


def vin_check_digit_ok(vin: str) -> bool:
    vin = vin.upper()
    total = sum(VIN_VALUES[c] * w for c, w in zip(vin, VIN_WEIGHTS))
    return vin[8] == ("X" if total % 11 == 10 else str(total % 11))


def url_vin(url: str) -> str | None:
    """A VIN embedded in the URL (TrueCar, Edmunds, Carfax, Autolist). US-sold VINs carry a check digit,
    which rejects look-alike 17-character tokens."""
    parts = urlsplit(url)
    tokens = re.split(r"[/?&=#_.+,;:-]", f"{parts.path}?{parts.query}#{parts.fragment}")
    vins = {t.upper() for t in tokens
            if VIN.fullmatch(t) and re.search(r"\d", t) and re.search(r"[A-Z]", t, re.I) and vin_check_digit_ok(t)}
    return vins.pop() if len(vins) == 1 else None


# Sites whose single-listing URLs we can recognize (by listing id or a VIN in the URL).
MARKETPLACES = frozenset(LISTING_ID) | {"truecar.com", "edmunds.com", "carfax.com", "autolist.com", "cargurus.com"}

# Independent-dealer inventory / VDP sections (Dealer.com, DealerOn, Dealer Inspire, …).
# Rooftops are not listed by hostname. Identity is (a) a check-digit VIN anywhere in the
# URL, or (b) a conservative VDP path plus a vehicle token (stock/id or year-make-model slug).
_DEALER_SECTION = (
    r"inventory|new-inventory|used-inventory|certified-inventory|"
    r"new-vehicles?|used-vehicles?|certified-pre-owned|"
    r"vehicle-details?|vehicledetail|vdps?|"
    r"used-cars?|new-cars?|autos"
)
DEALER_INVENTORY_PREFIX = re.compile(rf"^/(?:{_DEALER_SECTION})(?:/|$)", re.I)
DEALER_INDEX_TAIL = frozenset({
    "", "new", "used", "certified", "cpo", "pre-owned", "all", "search", "shop", "browse", "results",
})
# Sitemap / feed / inventory-API paths are bulk harvest, not a single VDP.
DEALER_BULK_PATH = re.compile(
    r"(?:/sitemap\b|sitemap\.xml|\.xml$|/feed\b|/robots\.txt$|/api/|/graphql)", re.I)
# ?q= / filters / pagination without a VIN is an SRP even on an inventory path.
DEALER_SRP_QUERY = frozenset({"q", "query", "search", "page", "start", "sort", "filter", "make", "model"})
# condition-year-make-model-… without requiring a VIN in the slug.
DEALER_VDP_SLUG = re.compile(r"(?:^|-)(?:19|20)\d{2}-(?:[a-z0-9]+-){2,}", re.I)
# Stock or listing id: digits required, not a model-year alone.
DEALER_VEHICLE_TOKEN = re.compile(r"^(?!(?:19|20)\d{2}$)[a-z0-9]{4,}$", re.I)


def dealer_vdp_slug(url: str) -> str | None:
    """Vehicle slug under a dealer inventory/VDP section; '' on an index; None when not that section."""
    path = urlsplit(url).path.rstrip("/")
    match = DEALER_INVENTORY_PREFIX.match(path)
    if not match:
        return None
    parts = [p for p in path[match.end():].split("/") if p]
    if parts and parts[0].lower() in {"new", "used", "certified", "cpo", "pre-owned"} and len(parts) > 1:
        parts = parts[1:]
    if not parts:
        return ""
    if len(parts) == 1 and parts[0].lower() in DEALER_INDEX_TAIL:
        return ""
    return parts[-1]


def _dealer_srp_query(url: str) -> bool:
    return any(key.lower() in DEALER_SRP_QUERY for key, _ in parse_qsl(urlsplit(url).query))


def is_dealer_vdp_url(url: str) -> bool | None:
    """True/False for dealer VDP shape; None when the path is not a VDP/inventory family and has no VIN.

    (a) A single check-digit VIN in path or query on a non-bulk URL.
    (b) Conservative inventory/VDP path plus a vehicle token, and not an SRP/index.
    """
    if DEALER_BULK_PATH.search(urlsplit(url).path):
        return False
    if url_vin(url):
        return True
    slug = dealer_vdp_slug(url)
    if slug is None:
        return None
    if not slug or _dealer_srp_query(url):
        return False
    if DEALER_VDP_SLUG.search(slug) or DEALER_VEHICLE_TOKEN.fullmatch(slug):
        return True
    return False


def is_dealer_listing_url(url: str) -> bool | None:
    """Alias for is_dealer_vdp_url (browse / listing identity)."""
    return is_dealer_vdp_url(url)


def is_listing_url(url: str) -> bool | None:
    """True/False on known marketplaces and dealer VDP shapes; None when the URL scheme is unknown."""
    if bare_host(url) in MARKETPLACES:
        return bool(listing_id(url) or url_vin(url))
    return is_dealer_vdp_url(url)
