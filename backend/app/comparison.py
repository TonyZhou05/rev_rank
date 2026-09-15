"""Reproducible buyer-aware comparisons. Asking prices never establish fair value."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
import re
from urllib.parse import quote
from uuid import uuid4

from .cancel import CancelToken
from .config import Settings
from .dealer import sanitize as sanitize_dealer
from .models import (Candidate, ConstraintCheck, Evidence, Finding, Market, Metric, NHTSAComplaint, NHTSARecall,
                     NHTSASafetyData, Preferences, Questions, Report, ShortlistEntry, now, value_text)
from .vehicle_data import NEOVIN_SOURCE, ProviderError, get_json

NHTSA = "https://api.nhtsa.gov"
NHTSA_RECALL_PAGE = "https://www.nhtsa.gov/recalls?nhtsaId={campaign}"
# Vehicle Detail Search, the page that carries the recalls and complaints tabs for one trim.
# `/vehicle/{VehicleId}` (the SafetyRatings id) returns "Page not found", so it is never linked.
# NHTSA's own links percent-encode a space in these path segments three times ("4 DR" -> "4%252520DR");
# that exact shape is what opens in a browser, so it is reproduced rather than normalised to %20.
NHTSA_TRIM_PAGE = "https://www.nhtsa.gov/vehicle/{year}/{make}/{model}/{body}/{drive}{anchor}"
# Fallback when body style or drive type is unknown: the year/make/model search landing, which
# lists recalls, investigations and complaints for the model year (no per-tab anchor available).
NHTSA_YMM_SEARCH = "https://www.nhtsa.gov/recalls?vymm={vymm}"
NHTSA_DRIVE_CODES = {"FWD", "RWD", "AWD", "4WD", "4X2", "4X4"}
# Body styles NHTSA puts in VehicleDescription; "DR" arrives as a door count plus "DR" ("4 DR").
NHTSA_BODY_WORDS = {"DR", "SUV", "VAN", "MINIVAN", "WAGON", "PICKUP", "TRUCK", "COUPE", "SEDAN",
                    "HATCHBACK", "CONVERTIBLE", "CROSSOVER"}
NHTSA_ITEM_LIMIT = 5
# Model-year safety data is optional enrichment: it is skipped rather than allowed to spend the
# request's whole budget before the analysis that needs what is left.
NHTSA_MIN_SECONDS = 15
_NHTSA_CACHE: dict = {}


def _nhtsa(url: str, params: dict, limit: int = 5_000_000):
    """Cached NHTSA API fetch, shared with the analyst's recall, complaint and rating tools."""
    key = (url, tuple(sorted(params.items())))
    if key not in _NHTSA_CACHE:
        if len(_NHTSA_CACHE) > 128:
            _NHTSA_CACHE.clear()
        _NHTSA_CACHE[key] = get_json(url, params, timeout=10, limit=limit)
    return _NHTSA_CACHE[key]


def _nhtsa_field(row: dict, *names: str) -> str:
    """NHTSA returns PascalCase keys for recalls and camelCase keys for complaints."""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _recall_items(rows: list[dict]) -> list[NHTSARecall]:
    items = []
    for row in rows[:NHTSA_ITEM_LIMIT]:
        campaign = re.sub(r"[^A-Z0-9]", "", _nhtsa_field(row, "NHTSACampaignNumber", "nhtsaCampaignNumber").upper())[:20]
        if not campaign:
            continue
        items.append(NHTSARecall(
            campaign_number=campaign,
            component=_nhtsa_field(row, "Component", "component")[:160],
            summary=_nhtsa_field(row, "Summary", "summary")[:300],
            report_date=_nhtsa_field(row, "ReportReceivedDate", "reportReceivedDate")[:40] or None,
            url=NHTSA_RECALL_PAGE.format(campaign=campaign),
        ))
    return items


def _trim_segment(value: str) -> str:
    """Encode one Vehicle Detail Search path segment the way NHTSA does (space -> %252520)."""
    return quote(str(value).strip().upper(), safe="").replace("%20", "%252520")


def nhtsa_ymm_search(year, make, model) -> str | None:
    """Year/make/model landing page on nhtsa.gov/recalls, or None when identity is incomplete."""
    if not year or not make or not model:
        return None
    return NHTSA_YMM_SEARCH.format(vymm=quote(f"{int(year)} {str(make).strip()} {str(model).strip()}", safe=""))


def _trim_parts(description, make) -> tuple[str, str, str] | None:
    """Split a SafetyRatings VehicleDescription into (model, body, drive) path segments.

    "2020 Toyota Camry 4 DR FWD" with make "Toyota" gives ("CAMRY", "4 DR", "FWD"). The model is
    read from the description rather than from our own field so multi-word trims stay in the model
    segment ("2020 BMW M2 Competition 2 DR RWD" keeps "M2 COMPETITION"). Returns None whenever the
    body style or drive type cannot be identified; callers then fall back to the search landing.
    """
    tokens = re.sub(r"\s+", " ", str(description or "")).strip().upper().split()
    if len(tokens) < 4 or tokens[-1] not in NHTSA_DRIVE_CODES:
        return None
    if re.fullmatch(r"(19|20)\d{2}", tokens[0]):
        tokens = tokens[1:]
    make_tokens = str(make or "").strip().upper().split()
    if make_tokens and tokens[:len(make_tokens)] == make_tokens:
        tokens = tokens[len(make_tokens):]
    drive, tokens = tokens[-1], tokens[:-1]
    body_start = len(tokens) - 1
    if tokens[body_start] not in NHTSA_BODY_WORDS:
        return None
    if tokens[body_start] == "DR" and body_start and tokens[body_start - 1].isdigit():
        body_start -= 1
    model_tokens, body_tokens = tokens[:body_start], tokens[body_start:]
    if not model_tokens or not body_tokens:
        return None
    return " ".join(model_tokens), " ".join(body_tokens), drive


def nhtsa_vehicle_page(year, make, model, description=None, anchor: str = "") -> str | None:
    """Best usable NHTSA consumer page for a model year: trim deep link when the body style and
    drive type are known, otherwise the year/make/model search landing."""
    if not year or not make or not model:
        return None
    parts = _trim_parts(description, make)
    if not parts:
        return nhtsa_ymm_search(year, make, model)
    trim_model, body, drive = parts
    return NHTSA_TRIM_PAGE.format(year=int(year), make=_trim_segment(make), model=_trim_segment(trim_model),
                                  body=_trim_segment(body), drive=_trim_segment(drive), anchor=anchor)


def _complaint_items(rows: list[dict]) -> list[NHTSAComplaint]:
    """NHTSA publishes no stable permalink per ODI number, so `url` stays null and the
    UI links complaint rows through `complaints_url` (the model-year page) instead."""
    items = []
    for row in rows[:NHTSA_ITEM_LIMIT]:
        odi = re.sub(r"[^0-9]", "", _nhtsa_field(row, "odiNumber", "ODINumber"))[:12]
        if not odi:
            continue
        items.append(NHTSAComplaint(
            odi_number=odi,
            component=_nhtsa_field(row, "components", "Component", "component")[:160],
            summary=_nhtsa_field(row, "summary", "Summary")[:300],
            date_filed=_nhtsa_field(row, "dateComplaintFiled", "DateComplaintFiled")[:40] or None,
        ))
    return items


def _nhtsa_rows(url: str, params: dict, key: str) -> list[dict] | None:
    """One NHTSA endpoint's rows, or None when that endpoint failed (as opposed to returning none)."""
    try:
        return [r for r in (_nhtsa(url, params).get(key) or []) if isinstance(r, dict)]
    except Exception:  # Optional enrichment: no NHTSA failure may take the comparison down.
        return None


def fetch_nhtsa_safety(year: int, make: str, model: str) -> NHTSASafetyData | None:
    """Fetch NHTSA model-year safety data (recalls, complaints, ratings).

    Returns structured data with fixed scope label. Never invents counts: an endpoint that failed
    leaves its count null (shown as unavailable), and the others still stand. None only when every
    endpoint failed. VIN-level recall status is OUT OF SCOPE.
    """
    params = {"make": make, "model": model, "modelYear": year}
    recall_rows = _nhtsa_rows(f"{NHTSA}/recalls/recallsByVehicle", params, "results")
    complaint_rows = _nhtsa_rows(f"{NHTSA}/complaints/complaintsByVehicle", params, "results")
    path = f"{NHTSA}/SafetyRatings/modelyear/{int(year)}/make/{quote(make, safe='')}/model/{quote(model, safe='')}"
    variant_rows = _nhtsa_rows(path, {}, "Results")
    if recall_rows is None and complaint_rows is None and variant_rows is None:
        return None
    variants = [v for v in variant_rows or [] if str(v.get("VehicleId", "")).isdigit()]

    # A variant description unlocks the trim deep link; without one the URLs stay on the
    # year/make/model landing, which still works for unrated model years.
    description = next((str(v.get("VehicleDescription", "")) for v in variants if v.get("VehicleDescription")), None)
    recalls_url = nhtsa_vehicle_page(year, make, model, description, "#recalls")
    complaints_url = nhtsa_vehicle_page(year, make, model, description, "#complaints")
    overall_rating = frontal_rating = side_rating = rollover_rating = None
    if variants:
        row = (_nhtsa_rows(f"{NHTSA}/SafetyRatings/VehicleId/{int(variants[0]['VehicleId'])}", {}, "Results") or [{}])[0]
        overall_rating = str(row.get("OverallRating")) if row.get("OverallRating") else None
        frontal_rating = str(row.get("OverallFrontCrashRating")) if row.get("OverallFrontCrashRating") else None
        side_rating = str(row.get("OverallSideCrashRating")) if row.get("OverallSideCrashRating") else None
        rollover_rating = str(row.get("RolloverRating")) if row.get("RolloverRating") else None

    return NHTSASafetyData(
        year=year, make=make, model=model,
        recalls_count=None if recall_rows is None else len(recall_rows),
        complaints_count=None if complaint_rows is None else len(complaint_rows),
        overall_rating=overall_rating, frontal_rating=frontal_rating,
        side_rating=side_rating, rollover_rating=rollover_rating,
        recalls_url=recalls_url, complaints_url=complaints_url,
        recalls=_recall_items(recall_rows or []), complaints=_complaint_items(complaint_rows or [])
    )

VERSION = "revrank-rules/0.1"
KM_PER_MILE = Decimal("1.609344")


def dec(value) -> Decimal:
    return Decimal(str(value))


def fmt(value, places=0) -> str:
    value = dec(value).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    return f"{value:,.{places}f}"


def equivalent(field: str, value, previous: str) -> bool:
    if field in ("year", "price", "mileage"):
        try:
            return dec(value) == dec(previous.replace(",", ""))
        except Exception:
            return False
    return value_text(value) == previous


def normalize(candidate: Candidate) -> Candidate:
    c = candidate.model_copy(deep=True)
    fields = ("title", "make", "model", "trim", "generation", "year", "price", "currency",
              "mileage", "mileage_unit", "transmission", "body", "engine", "drivetrain", "fuel_type",
              "location", "features", "history")
    for field in fields:
        value = getattr(c, field)
        prior = c.evidence.get(field)
        verified = field in c.verified_fields
        changed = prior and not equivalent(field, value, prior.value)
        if changed:
            c.warnings.append(f"User changed {field}; previous evidence: {prior.value[:120]} ({prior.source[:180]}).")
        if value is None or value == []:
            if prior:
                c.evidence.pop(field)
            continue
        if verified or changed or (prior is None and field not in ("currency", "mileage_unit")):
            source = "User-confirmed input (not independent verification)" if verified else "User-supplied input (unverified)"
            if prior and (changed or verified):
                source += f"; previous evidence: {prior.value[:200]} from {prior.source[:400]}"
            c.evidence[field] = Evidence(value=value_text(value), source=source,
                status="user_confirmed" if verified else "extracted")
        if verified:
            c.warnings = [w for w in c.warnings if not w.startswith((f"Missing {field};", f"Conflicting {field}:"))]
    if c.currency != "UNK" and "currency" in c.verified_fields:
        c.warnings = [w for w in c.warnings if not w.startswith("Currency is unknown;")]
    if "mileage_unit" in c.verified_fields:
        c.warnings = [w for w in c.warnings if not w.startswith("Mileage unit is unconfirmed;")]
    if c.source_kind == "synthetic" and not any("SYNTHETIC" in w for w in c.warnings):
        c.warnings.append("SYNTHETIC: this candidate is an invented demonstration, not real inventory.")
    if "observed_at" not in c.evidence:
        c.evidence["observed_at"] = Evidence(value=now(), source="Report input received; original observation date unknown", status="extracted")
    if "price_type" not in c.evidence:
        c.evidence["price_type"] = Evidence(value="asking", source="Candidate input interpreted as an asking price, never a sale", status="extracted")
    # Address line, map link and lookup links are rebuilt from the reported name and address, so a
    # report never shows a dealer link that arrived with the request. A block with no business left
    # in it becomes null rather than an empty card.
    c.dealer = sanitize_dealer(c.dealer)
    c.warnings = list(dict.fromkeys(c.warnings))[:100]
    return c


def usable(c: Candidate, field: str) -> bool:
    return getattr(c, field) is not None and (field not in c.conflicts or field in c.verified_fields) and not any(w.startswith(f"Conflicting {field}:") for w in c.warnings)


def msrp_sourced(c: Candidate) -> bool:
    """An MSRP the buyer confirmed, or the factory MSRP a NeoVIN decode of this VIN supplied.
    A scraped, listing-reported or LLM-suggested figure still does not count."""
    if "msrp" in c.verified_fields:
        return True
    evidence = c.evidence.get("msrp")
    return bool(evidence and evidence.source.startswith(NEOVIN_SOURCE))


def known_unit(c: Candidate) -> bool:
    return ("mileage_unit" in c.evidence and c.evidence["mileage_unit"].value == c.mileage_unit
            and usable(c, "mileage_unit"))


def asking(c: Candidate) -> bool:
    return c.evidence.get("price_type") is not None and c.evidence["price_type"].value.lower() == "asking"


def money(c: Candidate) -> str:
    if c.price is None:
        return "Unknown"
    if not usable(c, "price") or not usable(c, "currency"):
        return "Conflicting — review"
    return f"{c.currency} {fmt(c.price, 2)}" + (" (currency unconfirmed)" if c.currency == "UNK" else "")


def requirement_match(c: Candidate, wanted: str) -> str:
    text = re.sub(r"\s+", " ", wanted.strip().casefold())
    aliases = {"manual transmission": "manual", "automatic transmission": "automatic", "carplay": "apple carplay"}
    text = aliases.get(text, text)
    evidence = c.features + ([c.transmission] if c.transmission else [])
    pattern = re.compile(r"(?<!\w)" + re.escape(text) + r"(?!\w)")
    for entry in evidence:
        lowered = entry.casefold()
        if pattern.search(lowered):
            if re.search(r"\b(no|not|without|absent|lacks|lacking|unavailable|optional|unknown)\b", lowered):
                return "not established"
            return "listed"
    return "not established"


NEGATED_IN_LISTING = re.compile(r"\b(no|not|without|absent|lacks|lacking|never|free of|zero)\b")


def exclusion_match(c: Candidate, unwanted: str) -> tuple[str, str]:
    """Whether something the buyer ruled out shows up in the reviewed evidence.

    Silence is `not_established`, never a pass: a listing that does not mention a salvage title has
    not established that the title is clean.
    """
    text = re.sub(r"\s+", " ", unwanted.strip().casefold())
    pattern = re.compile(r"(?<!\w)" + re.escape(text) + r"(?!\w)")
    haystack = [v for v in (c.title, c.make, c.model, c.trim, c.generation, c.body, c.engine,
                            c.drivetrain, c.fuel_type, c.transmission, c.history) if v] + c.features
    for entry in haystack:
        lowered = entry.casefold()
        if not pattern.search(lowered):
            continue
        if NEGATED_IN_LISTING.search(lowered):
            return "meets", f"The listing states this is not present: \u201c{entry[:160]}\u201d. That remains a seller claim."
        return "conflicts", f"\u201c{unwanted}\u201d appears in the supplied evidence: \u201c{entry[:160]}\u201d."
    return "not_established", (f"The supplied evidence does not mention \u201c{unwanted}\u201d. "
                               "Absence from a listing is not proof; ask the seller.")


def transmission_match(c: Candidate, wanted: str) -> tuple[str, str]:
    families = {"manual": ("manual", "stick", "mt", "6mt", "5mt"),
                "automatic": ("automatic", "auto", "cvt", "dct", "dual-clutch", "dual clutch", "pdk", "tiptronic", "at")}
    if not c.transmission or not usable(c, "transmission"):
        return "unknown", "The supplied evidence does not confirm the transmission."
    text = re.sub(r"[^a-z0-9 ]", " ", c.transmission.casefold())
    words = set(text.split())
    hit = lambda key: any(term in words or term in text for term in families[key])
    if hit(wanted):
        return "meets", f"Listed transmission: {c.transmission}."
    other = "automatic" if wanted == "manual" else "manual"
    if hit(other):
        return "conflicts", f"Listed transmission is {c.transmission}, not {wanted}."
    return "unknown", f"Listed transmission \u201c{c.transmission}\u201d does not clearly say {wanted} or {other}."


def constraint_checks(c: Candidate, prefs: Preferences) -> list[ConstraintCheck]:
    """One check per stated constraint. Priorities and location are weights, not pass/fail tests."""
    checks: list[ConstraintCheck] = []

    def add(field, constraint, status, detail):
        checks.append(ConstraintCheck(field=field, constraint=constraint[:1000], status=status, detail=detail[:600]))

    if prefs.budget is not None:
        label = f"Budget {fmt(prefs.budget)}"
        if usable(c, "price") and usable(c, "currency") and c.currency != "UNK" and asking(c):
            gap = dec(prefs.budget) - dec(c.price)
            add("budget", label, "meets" if gap >= 0 else "conflicts",
                f"Asking price {c.currency} {fmt(c.price)} is {fmt(abs(gap))} {'under' if gap >= 0 else 'over'} the "
                f"stated budget (budget currency assumed {c.currency}; taxes and fees excluded).")
        else:
            add("budget", label, "unknown",
                "The asking price, its currency or its price type is unknown or conflicting, so budget fit is not calculated.")
    if prefs.max_mileage is not None:
        label = f"Mileage at most {fmt(prefs.max_mileage)}"
        if usable(c, "mileage") and known_unit(c):
            gap = dec(prefs.max_mileage) - dec(c.mileage)
            add("max_mileage", label, "meets" if gap >= 0 else "conflicts",
                f"Odometer {fmt(c.mileage)} {c.mileage_unit} is {fmt(abs(gap))} {c.mileage_unit} "
                f"{'under' if gap >= 0 else 'over'} the stated ceiling (compared in the listing's own unit).")
        else:
            add("max_mileage", label, "unknown",
                "The odometer reading or its unit is unknown or conflicting, so the mileage ceiling is not applied.")
    if prefs.transmission:
        status, detail = transmission_match(c, prefs.transmission)
        add("transmission", f"Transmission {prefs.transmission}", status, detail)
    for wanted in prefs.must_haves:
        listed = requirement_match(c, wanted) == "listed"
        add("must_haves", f"Must have {wanted}", "meets" if listed else "not_established",
            f"\u201c{wanted}\u201d is listed in the supplied equipment or transmission; confirm it on the actual car."
            if listed else
            f"\u201c{wanted}\u201d is not in the supplied equipment or transmission. Absence from a listing is not "
            "proof the car lacks it; ask the seller.")
    for unwanted in prefs.excludes:
        status, detail = exclusion_match(c, unwanted)
        add("excludes", f"No {unwanted}", status, detail)
    return checks


def build_shortlist(candidates: list[Candidate], prefs: Preferences) -> list[ShortlistEntry]:
    """Order the shortlist by how the buyer's own constraints read against reviewed evidence.

    Conflicts first, then items that cannot be established, then met constraints, then the lower
    asking price when every price is comparable. Every entry carries the checks behind it; there is
    no composite score, and nothing here is a condition, value or reliability judgement.
    """
    comparable_prices = (len({c.currency for c in candidates}) == 1 and all(
        c.currency != "UNK" and usable(c, "price") and asking(c) for c in candidates))
    by_car = [(c, constraint_checks(c, prefs)) for c in candidates]
    # With nothing stated, the import order stands: a price tiebreak would imply a preference
    # the buyer never expressed.
    tiebreak = comparable_prices and any(checks for _, checks in by_car)
    rows = []
    for index, (c, checks) in enumerate(by_car):
        meets = sum(check.status == "meets" for check in checks)
        conflicts = sum(check.status == "conflicts" for check in checks)
        open_items = sum(check.status in ("not_established", "unknown") for check in checks)
        price = float(c.price) if tiebreak and c.price is not None else 0.0
        rows.append((conflicts, open_items, -meets, price, index, c, checks, meets))
    rows.sort(key=lambda row: row[:5])
    entries = []
    for position, row in enumerate(rows, start=1):
        conflicts, open_items, _, _, _, c, checks, meets = row
        total = len(checks)
        if not total:
            rationale = ("You have not stated any constraints yet, so this is the order you imported the cars. "
                         "Use the constraint chat to say what matters, then refresh the report.")
        else:
            rationale = (f"Meets {meets} of your {total} stated constraint{'s' if total != 1 else ''}; "
                         f"{open_items} cannot be established from the reviewed evidence; {conflicts} conflict"
                         f"{'s' if conflicts == 1 else ''} with it. This ordering reflects constraint fit only: "
                         "it is not a value, condition or reliability judgement, and it uses asking prices.")
            if tiebreak:
                rationale += " Equal constraint fit is broken by the lower asking price."
        entries.append(ShortlistEntry(candidate_id=c.id, position=position, meets=meets, conflicts=conflicts,
                                      open_items=open_items, checks=checks, rationale=rationale))
    return entries


# Caveats for the report's two deliberately empty sections. The frontend picks these out of
# `warnings` by topic, so each one names the evidence its section needs and states no figure.
DEPRECIATION_CAVEAT = (
    "Depreciation and future sell value are not computed. A resale figure needs dated, licensed transaction "
    "evidence and generation/variant cohort matching; today's asking prices for cars of different ages are not "
    "a depreciation curve, so no number is estimated from your hold period or annual mileage.")
CONDITION_CAVEAT = (
    "Condition and feature-versus-price are not scored. Weighing condition or option content against an asking "
    "price needs a pre-purchase inspection or condition report and a permitted option-value source; listing "
    "photos, seller claims and an unverified equipment list establish neither, so no score is shown.")


def create_report(candidates: list[Candidate], prefs: Preferences, settings: Settings,
                  token: CancelToken | None = None) -> Report:
    warnings = [
        "Prices are seller asking prices, not completed transactions. No fair-value, depreciation or repair-cost estimate is supplied.",
        "Seller claims and user-confirmed inputs are not independently verified. Missing history never means clean history.",
        f"Calculation/prompt version: {VERSION}; Decimal arithmetic, miles × 1.609344 = km.",
    ]
    unique, by_vin = [], {}
    for raw in candidates:
        c = normalize(raw)
        vin = c.evidence.get("vin")
        if vin and vin.value.upper() in by_vin:
            first = by_vin[vin.value.upper()]
            message = f"Duplicate VIN: {c.title} ({c.id}) represents the same vehicle as {first.title}; only the first candidate is compared."
            differences = [f for f in ("price", "currency", "mileage", "year", "make", "model", "trim")
                           if getattr(c, f) != getattr(first, f)]
            if differences:
                message += " Duplicate sources disagree on " + ", ".join(differences) + "; resolve before deciding."
            warnings.append(message)
            first.warnings.append(message[:1000])
            # Preserve the second source as evidence, without counting a second vehicle.
            first.evidence["duplicate_source"] = Evidence(
                value=(c.source_url or c.title)[:4000], source="Deduplicated submitted candidate " + c.id,
                status="extracted")
            continue
        if vin:
            by_vin[vin.value.upper()] = c
        unique.append(c)
    candidates = unique
    ids = [c.id for c in candidates]
    findings = []
    def add(title, detail, selected, fields):
        findings.append(Finding(title=title, detail=detail, candidate_ids=selected, evidence_fields=fields))

    if len(candidates) < 2:
        warnings.append("Only one distinct vehicle remains after VIN deduplication; add a different vehicle for a meaningful comparison.")
    if any(c.source_kind == "synthetic" for c in candidates):
        warnings.append("SYNTHETIC DEMO DATA included: invented asking prices, mileage and equipment are not market observations.")

    # Currency groups never cross-convert without an explicit dated FX source.
    currencies = {c.currency for c in candidates}
    for currency in sorted(currencies - {"UNK"}):
        group = [c for c in candidates if c.currency == currency and usable(c, "price")
                 and usable(c, "currency") and asking(c)]
        if len(group) > 1:
            lowest, highest = min(group, key=lambda c: c.price), max(group, key=lambda c: c.price)
            difference = dec(highest.price) - dec(lowest.price)
            if difference:
                add("Asking-price difference",
                    f"{lowest.title} asks {currency} {fmt(difference, 2)} less than {highest.title}. "
                    "This is an asking-price difference across the supplied vehicles, not evidence of a better deal.",
                    [lowest.id, highest.id], ["price", "currency", "price_type"])
            else:
                add("Equal asking prices", f"These candidates each ask {currency} {fmt(lowest.price, 2)}; price alone does not distinguish them.",
                    [c.id for c in group], ["price", "currency", "price_type"])
    budget_currency = next(iter(currencies)) if len(currencies) == 1 and "UNK" not in currencies else None
    budget_values = []
    if prefs.budget is not None and budget_currency and all(usable(c, "currency") for c in candidates):
        warnings.append(f"Budget currency is assumed to be {budget_currency}, the shared candidate currency; the v0.1 preference input has no currency field.")
        for c in candidates:
            if usable(c, "price") and asking(c):
                delta = dec(prefs.budget) - dec(c.price)
                detail = (f"{budget_currency} {fmt(abs(delta), 2)} " + ("under" if delta >= 0 else "over") + " budget")
                budget_values.append(detail)
                add("Budget fit · " + c.title[:100],
                    detail + ". Taxes, registration, shipping, financing and inspection costs are excluded.",
                    [c.id], ["price", "currency"])
            else:
                budget_values.append("Unknown / conflicting asking price")
    else:
        budget_values = ["Not calculated"] * len(candidates)
        if prefs.budget is not None:
            warnings.append("Budget comparison withheld because currencies are mixed, unknown or conflicting. No exchange rate is assumed.")
    metrics = [Metric(label="Asking price", values=[money(c) for c in candidates]),
               Metric(label="Budget headroom", values=budget_values),
               Metric(label="Model year", values=[str(c.year) if c.year else "Unknown" for c in candidates]),
               Metric(label="Mileage as supplied", values=[
                   f"{fmt(c.mileage)} {c.mileage_unit}" if usable(c, "mileage") and known_unit(c)
                   else "Unknown / unit unconfirmed / conflicting" for c in candidates]),
               Metric(label="Transmission", values=[c.transmission or "Unknown" for c in candidates]),
               Metric(label="Engine", values=[c.engine or "Unknown" for c in candidates]),
               Metric(label="Drivetrain", values=[c.drivetrain or "Unknown" for c in candidates]),
               Metric(label="Body", values=[c.body or "Unknown" for c in candidates]),
               Metric(label="Fuel Type", values=[c.fuel_type or "Unknown" for c in candidates]),
               Metric(label="Generation / trim", values=[
                   " / ".join((c.generation or "Unknown generation", c.trim or "Unknown trim")) for c in candidates]),
               Metric(label="Location", values=[c.location or "Unknown" for c in candidates])]

    normalized_mileage = {c.id: dec(c.mileage) * (KM_PER_MILE if c.mileage_unit == "mi" else 1)
                          for c in candidates if usable(c, "mileage") and known_unit(c)}
    metrics.append(Metric(label="Mileage normalized to km", values=[
        fmt(normalized_mileage[c.id]) + " km" if c.id in normalized_mileage else "Not calculated" for c in candidates]))
    if len(normalized_mileage) > 1:
        low_id, high_id = min(normalized_mileage, key=normalized_mileage.get), max(normalized_mileage, key=normalized_mileage.get)
        if low_id != high_id:
            low, high = next(c for c in candidates if c.id == low_id), next(c for c in candidates if c.id == high_id)
            add("Mileage difference",
                f"{low.title} has {fmt(normalized_mileage[high_id] - normalized_mileage[low_id])} fewer km than {high.title} after unit conversion. "
                "Lower mileage alone does not establish condition or maintenance costs.", [low_id, high_id], ["mileage", "mileage_unit"])
    units = {c.mileage_unit for c in candidates if known_unit(c)}
    if len(units) == 1 and all(known_unit(c) for c in candidates):
        unit = next(iter(units))
        usage = dec(prefs.annual_mileage) * dec(prefs.ownership_years)
        warnings.append(f"Annual mileage is assumed to use {unit}, the shared candidate unit. This is a usage scenario, not a resale forecast.")
        metrics.append(Metric(label=f"Projected odometer after {fmt(prefs.ownership_years, 1)} years", values=[
            f"{fmt(dec(c.mileage) + usage)} {unit}" if usable(c, "mileage") else "Unknown" for c in candidates]))
        add("Your ownership usage",
            f"At {fmt(prefs.annual_mileage)} {unit} per year for {fmt(prefs.ownership_years, 1)} years, "
            f"you would add {fmt(usage)} {unit}. Obtain maintenance schedules and service records for that usage; costs are unknown.",
            ids, ["mileage", "mileage_unit"])
    else:
        warnings.append("Future odometer calculation withheld: annual_mileage has no unit in the contract and candidate units are mixed or unconfirmed.")

    for wanted in prefs.must_haves:
        values = [requirement_match(c, wanted) for c in candidates]
        metrics.append(Metric(label="Must-have: " + wanted, values=values))
        for c, value in zip(candidates, values):
            add("Must-have · " + wanted[:100],
                f"{c.title}: {wanted} is {value} in the supplied equipment/transmission. "
                + ("Confirm it on the actual vehicle." if value == "listed" else "Absence from the listing is not proof the vehicle lacks it; ask the seller."),
                [c.id], ["features", "transmission"])

    # Constraints the buyer stated in the chat, each as its own metric row and finding.
    if prefs.max_mileage is not None:
        checks = [next(check for check in constraint_checks(c, prefs) if check.field == "max_mileage") for c in candidates]
        metrics.append(Metric(label=f"Mileage ceiling: {fmt(prefs.max_mileage)}",
                              values=[{"meets": "within", "conflicts": "over", "unknown": "unknown"}[check.status] for check in checks]))
        for c, check in zip(candidates, checks):
            add("Mileage ceiling · " + c.title[:100], check.detail, [c.id], ["mileage", "mileage_unit"])
    if prefs.transmission:
        checks = [next(check for check in constraint_checks(c, prefs) if check.field == "transmission") for c in candidates]
        metrics.append(Metric(label=f"Transmission wanted: {prefs.transmission}",
                              values=[{"meets": "matches", "conflicts": "does not match", "unknown": "unknown"}[check.status] for check in checks]))
        for c, check in zip(candidates, checks):
            add("Transmission · " + c.title[:100], check.detail, [c.id], ["transmission"])
    for unwanted in prefs.excludes:
        results = [exclusion_match(c, unwanted) for c in candidates]
        metrics.append(Metric(label="Exclude: " + unwanted,
                              values=[{"meets": "listing denies it", "conflicts": "present",
                                       "not_established": "not established"}[status] for status, _ in results]))
        for c, (status, detail) in zip(candidates, results):
            add("Exclusion · " + unwanted[:100], f"{c.title}: {detail}", [c.id], ["features", "history", "title"])

    priorities = " ".join(prefs.priorities).casefold()
    if any(k in priorities for k in ("performance", "sport", "handling", "track")):
        add("Performance evidence gap",
            "The inputs do not include independently validated power, weight, braking or condition measurements. "
            "Model names and sporty trim labels cannot establish which actual vehicle performs better; arrange comparable test drives.",
            ids, ["make", "model", "trim", "generation"])
    if any(k in priorities for k in ("practical", "daily", "comfort", "family")):
        add("Daily-use fit",
            "Compare the listed equipment and transmission against your daily needs, and verify seating, cargo access and ride comfort in person. "
            "No seating dimensions or comfort scores were inferred from model names.",
            ids, ["features", "transmission"])
    if any(k in priorities for k in ("reliab", "ownership", "maint", "value", "resale")):
        add("Ownership uncertainty",
            "Service records, independent inspection and dated permitted market evidence are needed before judging reliability, total ownership cost or resale value.",
            ids, ["history", "year", "mileage"])
    if prefs.location:
        add("Location and travel",
            f"Buyer location: {prefs.location}. Listing locations are shown as supplied; no distance, travel cost, tax jurisdiction or availability was inferred.",
            ids, ["location"])
    add("Equipment and history need verification",
        "Listed equipment and disclosed history retain source evidence. Unknown service or accident history is an open question, "
        "and user confirmation records an input review rather than independent verification.", ids, ["features", "history"])

    questions = []
    for c in candidates:
        q = ["Can you provide service invoices, title/accident disclosures and an independent pre-purchase inspection?",
             "What is the complete out-the-door price, including taxes, fees and any mandatory add-ons?"]
        if not c.evidence.get("vin"):
            q.append("What is the VIN, and does it match the vehicle, title and listing?")
        if not c.generation or not c.trim:
            q.append("Can you confirm the exact generation, trim and factory option/build sheet?")
        if not known_unit(c):
            q.append("Is the displayed odometer in miles or kilometers?")
        for wanted in prefs.must_haves:
            q.append(f"Can you demonstrate and document this requirement on the actual car: {wanted}?")
        for unwanted in prefs.excludes:
            q.append(f"Can you confirm in writing, with documentation, that this car has no {unwanted}?")
        if prefs.transmission and transmission_match(c, prefs.transmission)[0] != "meets":
            q.append(f"Is this car a {prefs.transmission}, and can you show the transmission on a test drive?")
        if prefs.max_mileage is not None and not (usable(c, "mileage") and known_unit(c)):
            q.append("What is the current odometer reading, and is it displayed in miles or kilometers?")
        if any("conflict" in w.lower() for w in c.warnings):
            q.append("Can you reconcile the conflicting source fields before I rely on the comparison?")
        questions.append(Questions(candidate_id=c.id, questions=q))
    for c in candidates:
        warnings.extend(f"{c.title}: {w}" for w in c.warnings)

    # percent_of_msrp is derived here, never supplied as an input, and only from a sourced MSRP:
    # one the buyer confirmed or one a NeoVIN decode of the VIN reported.
    msrp_values = []
    for c in candidates:
        # NeoVIN reports the US-market factory MSRP in USD; no exchange rate is assumed.
        foreign = "msrp" not in c.verified_fields and c.currency != "USD"
        if c.msrp is not None and c.price is not None and usable(c, "price") and c.currency != "UNK":
            if not c.msrp:
                c.percent_of_msrp = None
                msrp_values.append("MSRP not usable")
            elif msrp_sourced(c) and foreign:
                c.percent_of_msrp = None
                msrp_values.append(f"Not calculated: MSRP is USD, price is {c.currency}")
            elif msrp_sourced(c) and dec(c.price) > dec(c.msrp) * 100:
                # Over 10,000% (the field's own ceiling) is a typo in the MSRP, not a price position.
                c.percent_of_msrp = None
                msrp_values.append("MSRP looks wrong (under 1% of the asking price)")
            elif msrp_sourced(c):
                pct = float((dec(c.price) / dec(c.msrp)) * 100)
                c.percent_of_msrp = round(pct, 2)
                msrp_values.append(f"{fmt(pct, 1)}%")
            else:
                c.percent_of_msrp = None
                msrp_values.append("MSRP not confirmed")
        else:
            c.percent_of_msrp = None
            msrp_values.append("N/A")
    metrics.append(Metric(label="% of original MSRP", values=msrp_values))

    # Compute cross_model: true if any make/model differs (case-insensitive trim)
    def norm(s):
        return (s or "").strip().casefold()
    make_models = [(norm(c.make), norm(c.model)) for c in candidates]
    cross_model = len(set(make_models)) > 1

    # A5: Deterministic NHTSA model-year safety data, one lookup per distinct model year, run
    # side by side: each is up to four sequential NHTSA calls, and the analysis needs the time left.
    nhtsa_data = {}
    identities = {(c.year, c.make, c.model) for c in candidates if c.year and c.make and c.model}
    if identities and not (token is not None and (token.cancelled or token.remaining() < NHTSA_MIN_SECONDS)):
        with ThreadPoolExecutor(max_workers=len(identities)) as pool:
            safety_by_identity = dict(zip(identities, pool.map(lambda key: fetch_nhtsa_safety(*key), identities)))
        for c in candidates:
            safety = safety_by_identity.get((c.year, c.make, c.model))
            if safety:
                nhtsa_data[c.id] = safety
                c.nhtsa_safety = safety.model_dump()

    # Deterministic constraint-fit order. The optional model may re-rank with citations on top of
    # this; when it cannot, this ordering is what the report shows.
    shortlist = build_shortlist(candidates, prefs)
    by_id = {entry.candidate_id: entry for entry in shortlist}
    if any(entry.checks for entry in shortlist):
        metrics.append(Metric(label="Constraint fit", values=[
            f"{by_id[c.id].meets} met · {by_id[c.id].open_items} open · {by_id[c.id].conflicts} conflicting"
            for c in candidates]))
        # Deliberately avoids the words the report's placeholder sections filter on, so this
        # caveat stays with the shortlist instead of being filed under condition-versus-price.
        warnings.append("The shortlist order counts how many of your stated constraints each car meets. It is not a "
                        "quality, value or reliability score, and a constraint a listing never mentions is counted as "
                        "unestablished rather than met.")
    warnings.append(DEPRECIATION_CAVEAT)
    warnings.append(CONDITION_CAVEAT)

    market = Market(message=(
        "MarketCheck key is configured, but no licensed adapter/data-use scope has been validated; enrichment remains unavailable."
        if settings.marketcheck_api_key else
        "No permitted market provider is configured. Candidate asking prices alone cannot establish market value."))
    summary = f"Compared {len(candidates)} distinct vehicle candidates using your supplied preferences, asking prices and field evidence."
    if prefs.budget is not None and budget_currency:
        summary += f" Budget comparisons assume {budget_currency}; fees are excluded."
    if prefs.must_haves:
        summary += " Must-have equipment is distinguished as listed or not established."
    if any(entry.checks for entry in shortlist):
        summary += " The shortlist is ordered by how many of your stated constraints each car meets."
    summary += (" Market valuation, depreciation and condition-versus-price are unavailable; review unknowns and "
                "seller questions before deciding.")
    return Report(id=str(uuid4()), created_at=now(),
                  title=" / ".join((c.make or "Unknown") + " " + (c.model or "vehicle") for c in candidates)[:300] + " comparison",
                  summary=summary, preferences=prefs, candidates=candidates, findings=findings,
                  metrics=metrics, questions=questions, market=market, warnings=list(dict.fromkeys(warnings)),
                  cross_model=cross_model, nhtsa_data=nhtsa_data, shortlist=shortlist)
