"""Search-excerpt normalization: site-specific record formats rewritten as "Label: value" lines.

Every rule here was derived from real excerpts (docs/parsing-notes.md records the examples and why each
rule is safe). Excerpts are untrusted text; rules only relabel values, they never invent them.

Two page kinds matter:
- single-vehicle pages (the listing itself, or a page whose URL names the VIN / a listing) may be parsed
  loosely: titles, summary sentences and unlabeled "N miles" describe that one car;
- pages listing many cars (search results, model pages) are parsed strictly: only labeled fields and
  record-structured site rules, because unlabeled text near a VIN often belongs to the neighboring card.
"""
import re
from urllib.parse import urlsplit

from .listing_url import bare_host, is_listing_url, same_listing

LABELS = (r'(?:Stock|VIN|Body(?: Style| Type)?|Vehicle Size|Type|Mileage|Odometer|Location|Price|Transmission|Engine|'
          r'Drive ?Train|Drivetrain|Exterior Color|Interior Color|Fuel Type|MPG|Year|Make|Model|Trim|Dealer|Prior Use)')
# "City, ST" or "City, Statename"; a city may start "St."/"Ft."/"Mt." but otherwise has no periods, so
# "Ft. Myers. Fort Myers, FL" yields "Fort Myers, FL".
PLACE = r"((?:(?:St|Ft|Mt)\. )?[A-Z][A-Za-z'\-]+(?: [A-Z][A-Za-z'\-]+){0,3}, (?:[A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?))\b"
# Labels written as "Label. Value." (autofinder) or in pipe tables (visor.vin).
DOTTED = r'(Drive Train|Transmission|Engine|Body Type|Exterior Color|Interior Color|Fuel Type|Dealer)'
TABLE = r'(Transmission|Drivetrain|Engine|Body Style|Exterior Color|Interior Color|Fuel Type|Mileage|Odometer|Price|Location)'

def carmax_card(text: str) -> str:
    """CarMax cards read "$40,998. About this car. Stock: N. VIN: V. Base specifications. ... City, State: X".
    An excerpt can hold neighboring cards: keep only the card around the VIN, from its price (or its
    "Stock:") up to the next card's "About this car"."""
    vin = re.search(r'VIN:?\s*[A-HJ-NPR-Z0-9]{17}', text)
    if not vin or not re.search(r'About this car|Base specifications', text):
        return text  # Not CarMax's card layout (e.g. the listing page itself): nothing to scope.
    begin = vin.start()
    stock = re.search(r'Stock:\s*\d+\.?\s*$', text[:begin])
    begin = stock.start() if stock else begin
    about = re.search(r'About this car\.?\s*$', text[:begin])
    if about:
        price = re.search(r'\$\d{1,3}(?:,\d{3})+\.?\s*$', text[:about.start()])
        begin = price.start() if price else about.start()
    after = text.find('About this car', vin.end())
    if after >= 0:
        # The next card starts at its own price, just before its "About this car".
        price = re.search(r'\$\d{1,3}(?:,\d{3})+\.?\s*$', text[:after])
        after = price.start() if price else after
    return text[begin:after if after >= 0 else None]


def vininspect_record(text: str) -> str:
    """vininspect lists records as "... VIN: V. vin checkout link. Listed for sale on: 2026-08; Price: P; Odometer: O;."
    The price and odometer before a VIN belong to the previous record ("Price: $26,605; Odometer: 50,840;. 2018
    MERCEDES-BENZ C-Class. VIN: ..."): keep only the record that starts at the VIN."""
    vin = re.search(r'[A-HJ-NPR-Z0-9]{17}', text)
    if not vin:
        return text
    start = text.rfind('VIN', max(0, vin.start() - 6), vin.start())
    rest = text[vin.end():]
    end = re.search(r'\.\s+\d{4}\s+[A-Z]', rest)
    return text[start if start >= 0 else vin.start(): vin.end() + (end.start() if end else len(rest))]


# (pattern, replacement) or text -> text rules per host, applied before the generic label splitting.
SITE_RULES: dict[str, list] = {
    # CarMax cards: "$40,998. About this car. Stock: 70181882. VIN: ..." - the price shown just above
    # "About this car" belongs to the same card. Two glued prices ("$62,998$63,998") stay unlabeled.
    "carmax.com": [carmax_card, (r'(?<![\d,$])\$(\d{1,3}(?:,\d{3})+)\.?\s+About this car\.', r'\nPrice: $\1\nAbout this car.'),
                   (r'\bCity, State\s*:', 'Location:')],
    # TrueCar cards: "76 mi away • $0 transfer • East Haven, CT" - distance is from the shopper; the
    # place after "transfer" is where the car is.
    "truecar.com": [(r'\bmi away\s*•\s*\$[\d,]+\s*transfer\s*•\s*' + PLACE, r'\nLocation: \1\n')],
    # Edmunds cards: "Located in Southern Pines, NC / 432 miles away from Tallahassee, FL".
    "edmunds.com": [(r'\bLocated in ' + PLACE, r'\nLocation: \1\n')],
    # DealerRater ad pages: "...priced at $16998. ... is located in Canoga Park, CA, has 128055 miles".
    "dealerrater.com": [(r'\bpriced at (\$[\d,]+)', r'\nPrice: \1\n'), (r'\bis located in ' + PLACE, r'\nLocation: \1\n'),
                        (r'\bhas ([\d,]+) miles\b', r'\nMileage: \1 miles\n')],
    # autofinder pages: "Dealer. CarMax Smithtown. 42 mi." - the trailing distance is from the shopper.
    "autofinder.com": [(r'(\bDealer\.\s+[^.]+\.)\s*\d[\d,]*\s*mi\b\.?', r'\1')],
    # vininspect history: one record per VIN, dated (see listed_date).
    "vininspect.com": [vininspect_record],
    # hypercars listing pages: "Listed byCarmax Ft. Myers. Fort Myers, FL 8,522 miles".
    "hypercars.io": [(r'Listed by[^\n]*?' + PLACE, r'\nLocation: \1\n'), (r'\b([\d,]+) miles\b', r'\nMileage: \1 miles\n')],
}


def single_vehicle_page(source_url: str, listing_url: str, vin: str | None) -> bool:
    """Whether a source page is about exactly one vehicle (see module docstring)."""
    path = urlsplit(source_url).path
    return (same_listing(source_url, listing_url) or bool(vin and vin.lower() in source_url.lower())
            or is_listing_url(source_url) is True
            or bool(re.search(r'/(?:listing|vehicle-details?|vehicledetail|vdp|classifieds)/', path, re.I)))


def listed_date(text: str) -> str | None:
    """A dated record ("Listed for sale on: 2026-08", vininspect) observed at that month, not today."""
    match = re.search(r'Listed for sale on:\s*(\d{4}-\d{2})', text)
    return match.group(1) if match else None


def snippet_text(text: str, source_url: str | None = None) -> str:
    # Strip common Markdown decoration without removing record boundaries.
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*]\s+)', '', text).replace('**', '')
    # The provider joins non-adjacent passages with " ... ": that gap ends whatever field precedes it
    # ("Body: 4D Sport Utility ... City, State"). A trailing "..." at the very end is handled below.
    text = re.sub(r'\s+(?:\.{2,}|…)(?=\s)', '\n', text)
    for rule in SITE_RULES.get(bare_host(source_url or ''), []):
        text = rule(text) if callable(rule) else re.sub(rule[0], rule[1], text)
    text = re.sub(r'\bCity, State\s*:', 'Location:', text)
    text = re.sub(r'\|\s*' + TABLE + r'\s*\|\s*([^|\n]+?)\s*(?=\|)', r'\n\1: \2\n', text)
    text = re.sub(r'\b' + DOTTED + r'\.\s+((?:[^.\n]|\.(?=\d)){1,40})\.', r'\n\1: \2\n', text)
    text = re.sub(r'\bAsking\s*(?=(?:US)?\$)', 'Price: ', text)
    # Only explicit price labels; "price $9,641 below market" is a difference, never a price.
    text = re.sub(r'\b(?:Advertised|Listed|Sale|Internet)\s+price\s*[.:]?\s*(?=(?:US)?\$\s?\d)', 'Price: ', text, flags=re.I)
    # Excerpts flatten "Label: value; Label: value." onto one line; the extractor reads one label per line.
    text = re.sub(r'[.;]\s+(?=[A-Z][A-Za-z #]{1,24}:)', '\n', text)
    # Some excerpts separate fields with spaces only ("Body: Coupe Vehicle Size: Compact Mileage: 30,368");
    # known listing labels still start a new field.
    # ("Body Type", "Fuel Type" and "Drive Type" are one label, not "Body" + "Type").
    text = re.sub(r'(?<!Body)(?<!Fuel)(?<!Drive)[ \t]+(?=' + LABELS + r'\s*:)', '\n', text)
    # A semicolon ends a field ("Odometer: 39,600; Coupe body style").
    text = re.sub(r';\s*', '\n', text)
    lines = [line.strip() for line in text.split('\n')]
    # Excerpts are cut mid-sentence: drop only the cut-off fragment ("Mileage: 30,368 City," keeps the
    # mileage; "Location: Madison," loses the unfinished city).
    lines[-1] = re.sub(r'(?:\s+[A-Z][^:\n]*?)?\s*(?:,|\.\.\.|…)\s*$', '', lines[-1])
    # A location without its state ("Location: East Haven" cut off before ", Connecticut") is partial.
    lines = [line for line in lines if not re.fullmatch(r'Location:\s*(?:[^,]*)', line)]
    return '\n'.join(line for line in lines if line)


# A seller label that centers a search excerpt on the car's own record, used when the location is still
# missing after the regular queries ("City, State" sits at the end of a CarMax card and is often cut off).
FOCUSED_QUERY = {"carmax.com": '"City, State"'}
