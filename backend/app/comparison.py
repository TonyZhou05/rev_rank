"""Reproducible buyer-aware comparisons. Asking prices never establish fair value."""
from decimal import Decimal, ROUND_HALF_UP
import re
from uuid import uuid4

from .config import Settings
from .models import Candidate, Evidence, Finding, Market, Metric, Preferences, Questions, Report, now, value_text

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
    c.warnings = list(dict.fromkeys(c.warnings))[:100]
    return c


def usable(c: Candidate, field: str) -> bool:
    return getattr(c, field) is not None and (field not in c.conflicts or field in c.verified_fields) and not any(w.startswith(f"Conflicting {field}:") for w in c.warnings)


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


def create_report(candidates: list[Candidate], prefs: Preferences, settings: Settings) -> Report:
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
        if any("conflict" in w.lower() for w in c.warnings):
            q.append("Can you reconcile the conflicting source fields before I rely on the comparison?")
        questions.append(Questions(candidate_id=c.id, questions=q))
    for c in candidates:
        warnings.extend(f"{c.title}: {w}" for w in c.warnings)
    market = Market(message=(
        "MarketCheck key is configured, but no licensed adapter/data-use scope has been validated; enrichment remains unavailable."
        if settings.marketcheck_api_key else
        "No permitted market provider is configured. Candidate asking prices alone cannot establish market value."))
    summary = f"Compared {len(candidates)} distinct vehicle candidates using your supplied preferences, asking prices and field evidence."
    if prefs.budget is not None and budget_currency:
        summary += f" Budget comparisons assume {budget_currency}; fees are excluded."
    if prefs.must_haves:
        summary += " Must-have equipment is distinguished as listed or not established."
    summary += " Market valuation is unavailable; review unknowns and seller questions before deciding."
    return Report(id=str(uuid4()), created_at=now(),
                  title=" / ".join((c.make or "Unknown") + " " + (c.model or "vehicle") for c in candidates)[:300] + " comparison",
                  summary=summary, preferences=prefs, candidates=candidates, findings=findings,
                  metrics=metrics, questions=questions, market=market, warnings=list(dict.fromkeys(warnings)))
