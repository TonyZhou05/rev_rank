"""Dealer link-out shell: identity from the licensed payload, links constructed without a key.

Everything here comes from the MarketCheck inventory record that was already fetched for a
listing, so a dealer block costs no extra paid call. Nothing is scraped, no review site is read,
and no dealer score exists: the module maps reported fields and builds public search URLs.

Two rules shape the code. A field the record did not carry stays null rather than being inferred
(a dealer name is never taken from a hostname), and a map link is a search query over the reported
name and address, never a coordinate pin.
"""
from urllib.parse import urlencode, urlsplit

from .fetch import FetchError, validated_url
from .models import DealerInfo, DealerLink

MAPS_SEARCH = "https://www.google.com/maps/search/?"
BBB_SEARCH = "https://www.bbb.org/search?"
# DealerRater has no name-search URL, only an area search, so the link is offered as one.
DEALERRATER_SEARCH = "https://www.dealerrater.com/consumer/search/dealer/?"
LOOKUP_NOTE = ("Outbound search link, opens on their site. RevRank does not read, quote or score "
               "these pages.")
SCOPE_NOTE = ("Dealer details are as the licensed inventory record reported them. They describe "
              "the business, not this VIN.")
NAME_ONLY_NOTE = "The record carried no dealer address, so the map link searches the name alone."
US_ZIP_LENGTH = 5


def clean(value, limit: int = 300) -> str | None:
    """Trim a reported string; anything that is not usable text becomes null."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:limit]
    return text or None


def safe_link(value) -> str | None:
    """Keep a link only when it is a plain, credential-free HTTP(S) URL on its standard port."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url, _, _ = validated_url(value)
    except FetchError:
        return None
    return url


def host_of(url: str | None) -> str | None:
    if not url:
        return None
    return (urlsplit(url).hostname or "").removeprefix("www.") or None


def address_line(street=None, city=None, state=None, postal_code=None) -> str | None:
    """One-line address from whichever parts exist; null when none do."""
    locality = ", ".join(part for part in (clean(city, 120), clean(state, 40)) if part)
    zip_code = clean(postal_code, 20)
    if zip_code:
        locality = f"{locality} {zip_code}".strip()
    return ", ".join(part for part in (clean(street, 200), locality) if part) or None


def maps_url(name=None, street=None, city=None, state=None, postal_code=None) -> str | None:
    """Keyless Google Maps search over the reported name and address.

    A search query is the honest shape here: the record's own text is handed to Maps rather than
    resolved to a coordinate we would then be asserting.
    """
    parts = [clean(name, 200), clean(street, 200), clean(city, 120), clean(state, 40), clean(postal_code, 20)]
    query = " ".join(part for part in parts if part)
    if not query:
        return None
    return MAPS_SEARCH + urlencode({"api": 1, "query": query})


def lookup_links(name=None, city=None, state=None, postal_code=None) -> list[DealerLink]:
    """Public search pages for the dealer, constructed from its name and place.

    These are starting points for the buyer's own diligence, not evidence RevRank has gathered.
    """
    name, city, state = clean(name, 200), clean(city, 120), clean(state, 40)
    zip_code = clean(postal_code, 20)
    links: list[DealerLink] = []
    if name:
        location = ", ".join(part for part in (city, state) if part)
        query = {"find_country": "USA", "find_text": name}
        if location:
            query["find_loc"] = location
        links.append(DealerLink(label="Look up on BBB", url=BBB_SEARCH + urlencode(query),
                                note=LOOKUP_NOTE))
    if zip_code and len(zip_code) >= US_ZIP_LENGTH and zip_code[:US_ZIP_LENGTH].isdigit():
        area = zip_code[:US_ZIP_LENGTH]
        links.append(DealerLink(
            label=f"DealerRater dealers near {area}",
            url=DEALERRATER_SEARCH + urlencode({"PostalCode": area, "Type": "ZIP",
                                                "ManufacturerName": "Used-Car-Dealer"}),
            note=f"{LOOKUP_NOTE} DealerRater has no name search, so this covers the {area} area."))
    return links


def dealer_info(*, name=None, website=None, phone=None, street=None, city=None, state=None,
                postal_code=None, vdp_url=None, source: str = "", car_location=None) -> DealerInfo | None:
    """Assemble one dealer block, or null when the record identified no business at all."""
    name, website, phone = clean(name, 200), safe_link(website), clean(phone, 60)
    street, city, state = clean(street, 200), clean(city, 120), clean(state, 40)
    postal_code, vdp_url = clean(postal_code, 20), safe_link(vdp_url)
    if not any((name, website, phone, street, city, state, postal_code)):
        return None
    address = address_line(street, city, state, postal_code)
    notes = [SCOPE_NOTE]
    if name and not address:
        notes.append(NAME_ONLY_NOTE)
    # car_location is where the record puts the car; the dealer address is the selling rooftop.
    place = ", ".join(part for part in (city, state) if part)
    location = clean(car_location, 120)
    if location and place and location.casefold() != place.casefold():
        notes.append(f"The record places the car in {location}, not at this rooftop. "
                     "Confirm where the car actually is before travelling.")
    return DealerInfo(
        name=name, website=website, phone=phone, street=street, city=city, state=state,
        postal_code=postal_code, address=address, vehicle_location=location,
        maps_url=maps_url(name, street, city, state, postal_code),
        vdp_url=vdp_url, source_domain=host_of(website) or host_of(vdp_url),
        source=clean(source, 1000) or "", notes=notes[:8],
        links=lookup_links(name, city, state, postal_code)[:4])


def from_listing(row) -> DealerInfo | None:
    """Dealer block for one licensed inventory row; no provider call of any kind."""
    record = getattr(row, "dealer", None)
    if record is None:
        return None
    seen = f" (provider last seen {row.last_seen})" if getattr(row, "last_seen", None) else ""
    return dealer_info(
        name=record.name, website=record.website, phone=record.phone,
        street=record.street, city=record.city, state=record.state, postal_code=record.postal_code,
        vdp_url=row.source_url, car_location=getattr(row, "location", None),
        source=f"Dealer as reported by the licensed inventory record for {row.source_url}{seen}")


def sanitize(dealer: DealerInfo | None) -> DealerInfo | None:
    """Rebuild the constructed parts of a dealer block from its reported fields.

    Report building runs this over every candidate, so the address line, map link and lookup links
    in a report are always the ones this code derives from the reported name and address — never a
    link that arrived with the request.
    """
    if dealer is None:
        return None
    return dealer_info(
        name=dealer.name, website=dealer.website, phone=dealer.phone, street=dealer.street,
        city=dealer.city, state=dealer.state, postal_code=dealer.postal_code,
        vdp_url=dealer.vdp_url, source=dealer.source, car_location=dealer.vehicle_location)
