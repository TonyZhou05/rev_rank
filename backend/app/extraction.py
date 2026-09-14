"""Conservative extraction: JSON-LD first, labeled text second, no specification lookup."""
from html.parser import HTMLParser
import json
import re
from uuid import uuid4

from pydantic import ValidationError

from .models import Candidate, Evidence, now, value_text

VERSION = "revrank-extract/0.1"
EDITABLE = ("make", "model", "trim", "generation", "year", "price", "currency", "mileage",
            "mileage_unit", "transmission", "body", "engine", "drivetrain", "fuel_type", "location", "features", "history")
MISSING = ("make", "model", "year", "price", "mileage", "transmission", "location", "history")
LABELS = {
    "make": r"make|manufacturer|brand", "model": r"model",
    "trim": r"trim|variant", "generation": r"generation", "year": r"year|model year",
    "price": r"asking price|price", "mileage": r"mileage|odometer",
    "transmission": r"transmission|gearbox", "location": r"location",
    "body": r"body style|body type|body", "engine": r"engine", "drivetrain": r"drivetrain|drive train|drive type",
    "fuel_type": r"fuel type",
    "history": r"history|service history|accident history",
    "features": r"features|options|equipment", "vin": r"vin",
}
# Known makes only; multi-word names first so "Land Rover" is not read as make "Land".
MAKES = ("Alfa Romeo", "Aston Martin", "Land Rover", "Mercedes-Benz", "Rolls-Royce", "Acura", "Audi", "BMW",
         "Buick", "Cadillac", "Chevrolet", "Chrysler", "Dodge", "Fiat", "Ford", "Genesis", "GMC", "Honda",
         "Hyundai", "Infiniti", "Jaguar", "Jeep", "Kia", "Lexus", "Lincoln", "Lucid", "Maserati", "Mazda",
         "MINI", "Mitsubishi", "Nissan", "Polestar", "Porsche", "Ram", "Rivian", "Subaru", "Tesla", "Toyota",
         "Volkswagen", "Volvo")
MULTIWORD_MODELS = ("Range Rover", "Grand Cherokee", "Grand Wagoneer", "Grand Caravan", "Santa Fe", "Santa Cruz",
                    "Model 3", "Model S", "Model X", "Model Y", "Town & Country", "Mustang Mach-E",
                    "GR Supra", "GR Corolla", "718 Cayman", "718 Boxster")
TITLE = re.compile(r"\b((?:19|20)\d{2})\s+(" + "|".join(re.escape(m) for m in MAKES) + r")\s+((?:GR\s+|718\s+)?[A-Za-z0-9][\w-]*(?:\s+[A-Za-z0-9][\w&-]*)?)", re.I)
# Retail summary sentence, e.g. "Used 2025 Audi A5 Sportback S line for $29590 with 41239 miles".
SUMMARY = re.compile(
    r"\b(?:Used|New|Certified(?: Pre-Owned)?)\s+((?:19|20)\d{2})\s+(" + "|".join(re.escape(m) for m in MAKES) + r")"
    r"\s+(\S+)((?:\s+(?!for\b)\S+){0,12}?)\s+for\s+((?:US|CA|C)?\$\s?[\d,]+(?:\.\d{1,2})?)"
    r"\s+with\s+([\d,]+)\s+(miles|mi|km)\b", re.I)


class Document(HTMLParser):
    def __init__(self, raw: str):
        super().__init__(convert_charrefs=True)
        self.parts, self.scripts = [], []
        self.hidden = 0
        self.ld = False
        self.script = []
        self.feed(raw)
        if self.ld and self.script:
            self.scripts.append("".join(self.script))
        self.text = "\n".join(p.strip() for p in self.parts if p.strip())

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag == "script":
            self.ld = dict(attrs).get("type", "").lower() == "application/ld+json"
            self.script = []

    def handle_endtag(self, tag):
        if tag == "script" and self.ld:
            self.scripts.append("".join(self.script))
            self.ld = False
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if self.ld:
            self.script.append(data)
        elif not self.hidden:
            self.parts.append(data)


US_STATES = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
             "Connecticut": "CT", "Delaware": "DE", "District Of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
             "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
             "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
             "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
             "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
             "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
             "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
             "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}


def normalize_location(value: str) -> str:
    """"Canoga Park, California … $36" -> "Canoga Park, CA"; anything not a US city/state stays as written."""
    match = re.match(r"\s*([A-Z][A-Za-z.'\- ]{1,40}?),\s*([A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)\b", value)
    if match:
        state = match.group(2)
        code = state if state in US_STATES.values() else US_STATES.get(state.title())
        if code:
            return f"{match.group(1).strip()}, {code}"
    return value.strip()


def scalar(value):
    if isinstance(value, dict):
        return value.get("name", value.get("value"))
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return value
    return None


def number(value):
    value = scalar(value)
    if isinstance(value, (int, float)):
        return value if 0 <= value <= 1_000_000_000 else None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
            return float(cleaned)
    return None


def money(text):
    """Recognize explicit asking values, never monthly installments or ambiguous decimals."""
    if re.search(r"(?:/mo\b|per month|monthly|/month|down payment|biweekly|weekly|from\b|starting\b|\d\s*[-–]\s*\d)", text, re.I):
        return None, None
    currency = None
    currency_match = re.search(r"\b(USD|CAD|EUR|GBP|AUD|JPY|CHF)\b", text, re.I)
    if currency_match:
        currency = currency_match.group(1).upper()
    for sign, code in (("US$", "USD"), ("C$", "CAD"), ("CA$", "CAD"), ("A$", "AUD"), ("€", "EUR"), ("£", "GBP")):
        if sign in text:
            currency = code
    # A sentence-final period may follow the amount, but never a digit or ",ddd"/".d" continuation:
    # "$71,998." is 71998, and a longer number is never truncated to its prefix ("71").
    match = re.search(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\d|[.,]\d)", text)
    return (number(match.group(1)), currency) if match else (None, currency)


def distance(value):
    if isinstance(value, dict):
        n = number(value)
        unit = str(value.get("unitCode", value.get("unitText", ""))).lower()
    else:
        text = str(value)
        match = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*(mi|mile|miles|km|kilometers?|kilometres?)?\s*", text, re.I)
        if not match:
            return None, None
        n, unit = number(match.group(1)), (match.group(2) or "").lower()
    if unit in ("smi", "mi", "mile", "miles"):
        return n, "mi"
    if unit in ("kmt", "km", "kilometer", "kilometers", "kilometre", "kilometres"):
        return n, "km"
    return n, None


def ld_nodes(value, depth=0):
    if depth > 12:
        return
    if isinstance(value, list):
        for item in value[:100]:
            yield from ld_nodes(item, depth + 1)
    elif isinstance(value, dict):
        kind = value.get("@type", [])
        kinds = [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []
        if any(str(k).split("/")[-1] in ("Vehicle", "Car", "Product", "Motorcycle") for k in kinds):
            yield value
        for key, child in value.items():
            if key not in ("offers", "brand", "manufacturer"):
                yield from ld_nodes(child, depth + 1)


class Builder:
    def __init__(self, source: str, kind: str):
        self.source, self.kind = source, kind
        self.values, self.evidence, self.warnings = {}, {}, []
        self.conflicts = set()

    def add(self, field: str, value, via: str):
        if value is None or value == "" or value == []:
            return
        if field in ("price", "mileage") and number(value) is None:
            self.warnings.append(f"Invalid {field} ignored; review the original listing.")
            return
        if isinstance(value, str):
            # Dangling separators ("4D Sport Utility ..", "Coupe;") are formatting, not part of the value.
            value = value.strip().rstrip(" .,;:…").strip()[:1000] if field not in ("history", "features") else value.strip()[:1000]
            if not value:
                return
        if field == "year":
            try:
                value = int(value)
                if not 1886 <= value <= 2100:
                    return
            except (TypeError, ValueError):
                return
        if field == "location":
            value = normalize_location(str(value))
        if field == "vin":
            value = str(value).upper()
            if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", value):
                self.warnings.append("Invalid VIN was not retained.")
                return
        if field in self.values and self.values[field] != value:
            self.conflicts.add(field)
            self.warnings.append(f"Conflicting {field}: {value_text(self.values[field])[:200]} versus {value_text(value)[:200]}; first value retained for review.")
            return
        self.values[field] = value
        self.evidence[field] = Evidence(value=value_text(value), source=f"{self.source} · {via}"[:2000],
                                        status="seller_claim" if self.kind == "listing" else "extracted")

    def candidate(self) -> Candidate:
        values = {k: v for k, v in self.values.items() if k in EDITABLE}
        title = " ".join(str(values[k]) for k in ("year", "make", "model", "trim") if values.get(k))
        title = title or self.values.get("title", "Imported listing — details need review")
        values["currency"] = values.get("currency", "UNK")
        values["mileage_unit"] = values.get("mileage_unit", "mi")
        for field in MISSING:
            if values.get(field) is None:
                self.warnings.append(f"Missing {field}; confirm with the seller or enter it manually.")
        if values["currency"] == "UNK":
            self.warnings.append("Currency is unknown; a bare $ does not establish USD or CAD. Price comparisons are withheld.")
        if "mileage_unit" not in self.evidence:
            self.warnings.append("Mileage unit is unconfirmed; mi is only the editor default. Mileage calculations are withheld until confirmed.")
        if not values.get("generation") or not values.get("trim"):
            self.warnings.append("Generation/variant matching is unverified; no external specifications were inferred.")
        self.warnings.append("Extracted listing text and seller disclosures are not independent vehicle-history verification.")
        self.evidence["observed_at"] = Evidence(value=now(), source=self.source, status="extracted")
        self.evidence["extraction_version"] = Evidence(value=VERSION, source="RevRank deterministic extractor", status="extracted")
        self.evidence["price_type"] = Evidence(value="asking", source=self.source, status="extracted")
        try:
            return Candidate(
                id=str(uuid4()), title=str(title)[:300], source_kind=self.kind,
                source_url=self.source if self.kind == "listing" else None,
                evidence=self.evidence, warnings=list(dict.fromkeys(self.warnings))[:100], **values)
        except ValidationError:
            # Malformed source data must not become a server error; validate field by field.
            clean = dict(values)
            for key, value in values.items():
                try:
                    Candidate(id="probe", title="probe", source_kind="user", **{key: value})
                except ValidationError:
                    clean.pop(key, None)
                    self.evidence.pop(key, None)
                    self.warnings.append(f"Invalid source {key} discarded.")
            return Candidate(id=str(uuid4()), title=str(title)[:300], source_kind=self.kind,
                             source_url=self.source if self.kind == "listing" else None,
                             evidence=self.evidence, warnings=self.warnings[:100], **clean)


def parse_node(node: dict, builder: Builder):
    via = "JSON-LD"
    mapping = {"make": ("brand", "manufacturer"), "model": ("model",), "trim": ("vehicleConfiguration",),
               "generation": ("generation",), "year": ("vehicleModelDate", "modelDate", "productionDate"),
               "transmission": ("vehicleTransmission",), "vin": ("vehicleIdentificationNumber",),
               "title": ("name",)}
    for field, keys in mapping.items():
        for key in keys:
            value = scalar(node.get(key))
            if field == "year" and isinstance(value, str):
                match = re.match(r"^(\d{4})(?:-\d{2}-\d{2})?$", value)
                value = int(match.group(1)) if match else None
            builder.add(field, value, via + "." + key)
    offers = node.get("offers", [])
    for offer in offers if isinstance(offers, list) else [offers]:
        if not isinstance(offer, dict):
            continue
        price = number(offer.get("price"))
        currency = scalar(offer.get("priceCurrency"))
        builder.add("price", price, via + ".offers.price")
        if isinstance(currency, str) and re.fullmatch(r"[A-Za-z]{3}", currency):
            builder.add("currency", currency.upper(), via + ".offers.priceCurrency")
        place = offer.get("availableAtOrFrom")
        if isinstance(place, dict):
            builder.add("location", address_text(place.get("address", place.get("name"))), via + ".offers.availableAtOrFrom")
    if node.get("mileageFromOdometer") is not None:
        mileage, unit = distance(node["mileageFromOdometer"])
        builder.add("mileage", mileage, via + ".mileageFromOdometer")
        builder.add("mileage_unit", unit, via + ".mileageFromOdometer.unit")
    if node.get("address"):
        builder.add("location", address_text(node["address"]), via + ".address")
    props = node.get("additionalProperty", [])
    if not isinstance(props, list):
        props = [props]
    features = []
    for prop in props[:100]:
        if not isinstance(prop, dict):
            continue
        name, value = str(prop.get("name", "")).strip(), prop.get("value")
        key = name.lower()
        if key in ("vin", "history", "generation", "trim", "location", "transmission"):
            builder.add(key, scalar(value), via + ".additionalProperty")
        elif name and value not in (False, None, "", "false", "No", "no"):
            features.append(name if value is True else f"{name}: {scalar(value)}")
    if features:
        builder.add("features", features[:100], via + ".additionalProperty")
    # Description is visible source text too; only labeled conservative fields are parsed.
    if isinstance(node.get("description"), str):
        parse_text(Document(node["description"]).text, builder, "JSON-LD.description")


def address_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return ", ".join(str(scalar(value[k])) for k in ("addressLocality", "addressRegion", "addressCountry")
                         if value.get(k) and scalar(value[k]))
    return None


def parse_text(text: str, builder: Builder, via="text", loose=True):
    for field, label in LABELS.items():
        for match in re.finditer(r"(?im)^\s*(?:" + label + r")\s*[:=]\s*([^\n\r]{1,1000})", text):
            raw = match.group(1).strip()
            if field == "price":
                amount, currency = money(raw)
                builder.add("price", amount, via + ": " + raw[:120])
                builder.add("currency", currency, via)
            elif field == "mileage":
                amount, unit = distance(raw)
                builder.add("mileage", amount, via)
                builder.add("mileage_unit", unit, via)
            elif field == "features":
                features = [p.strip()[:300] for p in re.split(r"[,;|]", raw) if p.strip()]
                builder.add(field, features[:100], via)
            elif field == "year":
                if re.fullmatch(r"\d{4}", raw):
                    builder.add(field, int(raw), via)
            else:
                builder.add(field, raw, via)
    # Conservative title recognizer: "YEAR MAKE MODEL" for known makes only; never infer trims/specs.
    for match in (TITLE.finditer(text) if loose else ()):
        builder.add("year", int(match.group(1)), via + ".title")
        builder.add("make", next(m for m in MAKES if m.lower() == match.group(2).lower()), via + ".title")
        words = match.group(3).split()
        size = next((len(m.split()) for m in MULTIWORD_MODELS if [w.lower() for w in words[:len(m.split())]] == m.lower().split()), 1)
        # Preserve model wording rather than guessing an alias mapping.
        builder.add("model", " ".join(words[:size]), via + ".title")
    for match in (SUMMARY.finditer(text) if loose else ()):
        summary = via + ".summary"
        builder.add("year", int(match.group(1)), summary)
        builder.add("make", next(m for m in MAKES if m.lower() == match.group(2).lower()), summary)
        # The model/trim split is positional (first word, or a known multi-word model); the rest is trim wording.
        words = (match.group(3) + match.group(4)).split()
        size = next((len(m.split()) for m in MULTIWORD_MODELS if [w.lower() for w in words[:len(m.split())]] == m.lower().split()), 1)
        builder.add("model", " ".join(words[:size]), summary)
        builder.add("trim", " ".join(words[size:]) or None, summary)
        amount, currency = money(match.group(5))
        builder.add("price", amount, summary)
        builder.add("currency", currency, summary)
        amount, unit = distance(match.group(6) + " " + match.group(7))
        builder.add("mileage", amount, summary)
        builder.add("mileage_unit", unit, summary)
    # Strongly signaled standalone price / distance, without interpreting an arbitrary number.
    # Only on single-vehicle text: on a page listing many cars an unlabeled number may be a neighbor's.
    if loose and "price" not in builder.values:
        for line in text.splitlines():
            if re.fullmatch(r"\s*(?:(?:USD|CAD|EUR|GBP|AUD)\s*|(?:US|CA|C|A)?[$€£])\s*[\d,]+(?:\.\d{1,2})?\s*(?:USD|CAD|EUR|GBP|AUD)?\s*", line, re.I):
                amount, currency = money(line)
                builder.add("price", amount, via)
                builder.add("currency", currency, via)
    if loose and "mileage" not in builder.values:
        # "502 mi away" / "within 50 miles" are distances to the shopper, not the odometer.
        for match in re.finditer(r"(?<!within )(?<!\w)([\d,]+(?:\.\d+)?)\s+(miles|mi|km|kilometers|kilometres)\b"
                                 r"(?!\s*(?:away|from|radius|distance|range|of\b))", text, re.I):
            amount, unit = distance(match.group(0))
            builder.add("mileage", amount, via)
            builder.add("mileage_unit", unit, via)


def extract(text: str, source_url: str | None = None, fetched=False, loose=True) -> tuple[Candidate, str]:
    document = Document(text)
    builder = Builder(source_url if fetched else "User-pasted listing text", "listing" if fetched else "user")
    scripts = document.scripts[:50]
    if text.lstrip().startswith(("{", "[")):
        scripts = [text] + scripts
    node_count = 0
    for script in scripts:
        try:
            nodes = list(ld_nodes(json.loads(script)))
        except (ValueError, RecursionError):
            builder.warnings.append("Malformed JSON-LD ignored; conservative text extraction used.")
            continue
        for node in nodes:
            node_count += 1
            if node_count > 20:
                break
            parse_node(node, builder)
    if node_count > 1:
        builder.warnings.append("Multiple structured products found; fields may conflict. Review that this page describes one vehicle.")
    parse_text(document.text, builder, loose=loose)
    candidate = builder.candidate()
    if source_url and not fetched:
        try:
            candidate.source_url = source_url
        except ValidationError:
            candidate.warnings.append("Supplied URL is not a valid source reference and was discarded; pasted text was still processed.")
    candidate.warnings.append("Source page content is not retained; only extracted fields and short evidence references enter a saved report.")
    return candidate, document.text


# US-only marketplaces: a bare "$" there is USD and odometers are in miles. Other sites stay unknown.
US_MARKETPLACES = frozenset({"carmax.com", "carvana.com", "cargurus.com", "cars.com", "autotrader.com", "truecar.com",
                             "edmunds.com", "kbb.com", "autolist.com", "carfax.com", "capitalone.com", "dealerrater.com",
                             "visor.vin", "autofinder.com"})


def apply_market_units(candidate: Candidate, url: str | None) -> Candidate:
    from urllib.parse import urlsplit
    host = (urlsplit(url or "").hostname or "").removeprefix("www.")
    if host not in US_MARKETPLACES:
        return candidate
    source = f"Inferred from source: {host} is a US marketplace listing prices in USD and odometers in miles"
    if candidate.price is not None and candidate.currency == "UNK":
        candidate.currency = "USD"
        candidate.evidence["currency"] = Evidence(value="USD", source=source, status="extracted")
        candidate.warnings = [w for w in candidate.warnings if not w.startswith("Currency is unknown;")]
    if candidate.mileage is not None and "mileage_unit" not in candidate.evidence:
        candidate.mileage_unit = "mi"
        candidate.evidence["mileage_unit"] = Evidence(value="mi", source=source, status="extracted")
        candidate.warnings = [w for w in candidate.warnings if not w.startswith("Mileage unit is unconfirmed;")]
    return candidate


def import_status(candidate: Candidate) -> str:
    complete = all(getattr(candidate, k) is not None for k in ("make", "model", "year", "price", "mileage"))
    complete = complete and candidate.currency != "UNK" and "mileage_unit" in candidate.evidence
    conflicts = any("conflict" in w.lower() for w in candidate.warnings)
    return "success" if complete and not conflicts else "partial"
