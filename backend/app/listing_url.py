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


def is_listing_url(url: str) -> bool | None:
    """True/False on known marketplaces; None when the site's URL scheme is unknown (a dealer site)."""
    if bare_host(url) not in MARKETPLACES:
        return None
    return bool(listing_id(url) or url_vin(url))
