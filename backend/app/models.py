"""Frozen v0.1 wire models; malformed input is a 422, unknowns remain null."""
from datetime import datetime, timezone
from math import isfinite
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Scalar = Annotated[float, Field(ge=0, le=1_000_000_000, allow_inf_nan=False)]
Link = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)]


def reference_url(value: str | None) -> str | None:
    """Accept only a credential-free HTTP(S) URL; anything else is refused rather than shown."""
    if not value:
        return None
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ValueError("Link must be an HTTP(S) URL without credentials")
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Link must be an HTTP(S) URL without credentials")
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Evidence(Model):
    value: Annotated[str, StringConstraints(max_length=4000)]
    source: Annotated[str, StringConstraints(max_length=2000)]
    status: Literal["seller_claim", "user_confirmed", "extracted", "synthetic"]


class Observation(Model):
    field: Short
    value: Short
    source_url: Annotated[str, StringConstraints(max_length=2048)]
    retrieved_at: Short
    observed_at: Short | None = None
    method: Literal['search', 'direct', 'licensed', 'registry'] = 'search'
    vin: Annotated[str, StringConstraints(pattern=r'^[A-HJ-NPR-Z0-9]{17}$')] | None = None


class RetrievalAttempt(Model):
    method: Short
    status: Short
    detail: Short


# Fixed label carried with every dealer block, the way NHTSA data carries its model-year scope.
DEALER_SCOPE = "Dealer Business Information (not VIN-specific)"


class DealerLink(Model):
    """A search URL built from the dealer's own name and place.

    RevRank constructs the link and stops there: it does not fetch these pages, quote reviews or
    turn them into a score.
    """
    label: Nonempty
    url: Link
    note: Short = ""

    @field_validator("url")
    @classmethod
    def link_is_reference(cls, value):
        return reference_url(value)


class DealerInfo(Model):
    """The selling business as the licensed inventory record described it, plus keyless link-outs.

    Business level only: nothing here is evidence about the individual vehicle. Every field is
    copied from a payload that was already fetched for the listing, so an absent field stays null
    instead of being guessed — a dealer name is never derived from a URL, and coordinates are
    never invented (the map link is a search query, not a pin).
    """
    scope: str = DEALER_SCOPE
    name: Short | None = None
    website: Link | None = None
    phone: Short | None = None
    street: Short | None = None
    city: Short | None = None
    state: Short | None = None
    postal_code: Short | None = None
    # Single-line rendering of whichever address parts are present; null when none are.
    address: Short | None = None
    # Where the record put the car, which is not always the selling rooftop (transfers, hubs).
    vehicle_location: Short | None = None
    maps_url: Link | None = None
    # The licensed listing this dealer record came with.
    vdp_url: Link | None = None
    source_domain: Short | None = None
    source: Short = ""
    notes: Annotated[list[Short], Field(max_length=8)] = Field(default_factory=list)
    links: Annotated[list[DealerLink], Field(max_length=4)] = Field(default_factory=list)

    @field_validator("website", "maps_url", "vdp_url")
    @classmethod
    def links_are_references(cls, value):
        return reference_url(value)


class Candidate(Model):
    id: Nonempty
    title: Nonempty
    make: Short | None = None
    model: Short | None = None
    trim: Short | None = None
    generation: Short | None = None
    year: Annotated[int, Field(strict=True, ge=1886, le=datetime.now().year + 2)] | None = None
    price: Scalar | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "UNK"
    mileage: Scalar | None = None
    mileage_unit: Literal["mi", "km"] = "mi"
    transmission: Short | None = None
    body: Short | None = None
    engine: Short | None = None
    drivetrain: Short | None = None
    fuel_type: Short | None = None
    location: Short | None = None
    features: Annotated[list[Nonempty], Field(max_length=100)] = Field(default_factory=list)
    history: Short | None = None
    source_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    source_kind: Literal["synthetic", "user", "listing"]
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    warnings: Annotated[list[Short], Field(max_length=100)] = Field(default_factory=list)
    verified_fields: Annotated[list[Nonempty], Field(max_length=40)] = Field(default_factory=list)
    retrieval_method: Literal['direct', 'search', 'licensed', 'registry', 'paste', 'synthetic'] = 'direct'
    observations: Annotated[list[Observation], Field(max_length=150)] = Field(default_factory=list)
    conflicts: Annotated[list[Short], Field(max_length=30)] = Field(default_factory=list)
    # A6: Days-on-market from licensed inventory only; null otherwise (never extra paid calls)
    dom: Annotated[int, Field(ge=0, le=100000)] | None = None
    dom_active: Annotated[int, Field(ge=0, le=100000)] | None = None
    first_seen_at: Short | None = None
    # Original (factory) MSRP: buyer-entered, or decoded from a known VIN by MarketCheck NeoVIN.
    # Never scraped, never LLM-guessed, and never a listing's own msrp (that often repeats the asking price).
    msrp: Scalar | None = None
    # Derived at compare time: (price/msrp)*100 when both are set, the currency is known, and the MSRP is
    # buyer-confirmed or NeoVIN-sourced; NOT user-editable
    percent_of_msrp: Annotated[float, Field(ge=0, le=10000, allow_inf_nan=False)] | None = None
    # A5: NHTSA model-year safety data attached at compare time
    nhtsa_safety: dict | None = None
    # The selling business from the licensed inventory payload already fetched for this listing;
    # null for every other retrieval path. Never a vehicle-level fact and never a dealer rating.
    dealer: DealerInfo | None = None

    @field_validator("price", "mileage", mode="before")
    @classmethod
    def numbers_not_booleans(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("Use a JSON number or null")
        return value

    @field_validator("source_url")
    @classmethod
    def source_is_reference(cls, value):
        if value:
            from urllib.parse import urlsplit
            try:
                parts = urlsplit(value)
                if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
                    raise ValueError()
            except ValueError:
                raise ValueError("source_url must be an HTTP(S) URL without credentials")
        return value

    @field_validator("evidence")
    @classmethod
    def bounded_evidence(cls, value):
        if len(value) > 50 or any(len(k) > 80 for k in value):
            raise ValueError("Too many evidence fields or overlong field name")
        if "vin" in value and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", value["vin"].value.upper()):
            raise ValueError("VIN evidence must contain a valid 17-character VIN")
        return value

    @field_validator("verified_fields")
    @classmethod
    def valid_verified_fields(cls, value):
        editable = {"title", "make", "model", "trim", "generation", "year", "price", "currency",
                    "mileage", "mileage_unit", "transmission", "body", "engine", "drivetrain", "fuel_type",
                    "location", "features", "history", "msrp"}
        if set(value) - editable:
            raise ValueError("verified_fields contains an unknown or non-editable field")
        return list(dict.fromkeys(value))


class Preferences(Model):
    budget: Scalar | None = None
    annual_mileage: Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)] = 10000
    ownership_years: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)] = 3
    location: Short = ""
    priorities: Annotated[list[Nonempty], Field(max_length=20)] = Field(default_factory=list)
    must_haves: Annotated[list[Nonempty], Field(max_length=30)] = Field(default_factory=list)
    # Odometer ceiling the buyer will accept, in the candidate's own unit; null means no ceiling.
    max_mileage: Scalar | None = None
    transmission: Literal["manual", "automatic"] | None = None
    # Things the buyer rules out. A listing that stays silent is never treated as passing one.
    excludes: Annotated[list[Nonempty], Field(max_length=30)] = Field(default_factory=list)

    @field_validator("budget", "annual_mileage", "ownership_years", "max_mileage", mode="before")
    @classmethod
    def finite_numbers(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)):
            raise ValueError("Use a finite JSON number")
        return value


# The only fields the constraint chat may write. A listing fact is never one of them.
CONSTRAINT_FIELDS = ("budget", "annual_mileage", "ownership_years", "max_mileage",
                     "transmission", "location", "must_haves", "excludes", "priorities")
ConstraintField = Literal["budget", "annual_mileage", "ownership_years", "max_mileage",
                          "transmission", "location", "must_haves", "excludes", "priorities"]


class Constraint(Model):
    """One preference the chat recognised, with the buyer's own words behind it."""
    field: ConstraintField
    label: Short
    value: Short
    # A contiguous phrase from the buyer's message. Empty when the value was carried in unchanged.
    quote: Short = ""
    source: Literal["rules", "llm"]


class ConstraintRequest(Model):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    preferences: Preferences = Field(default_factory=Preferences)


class ConstraintResponse(Model):
    mode: Literal["llm", "rules"]
    preferences: Preferences
    constraints: Annotated[list[Constraint], Field(max_length=60)] = Field(default_factory=list)
    # Composed from the accepted constraints, never model prose.
    reply: Annotated[str, StringConstraints(max_length=2000)]
    unmapped: Annotated[list[Short], Field(max_length=10)] = Field(default_factory=list)
    notes: Annotated[list[Short], Field(max_length=10)] = Field(default_factory=list)


class ImportRequest(Model):
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)] | None = None
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200000)] | None = None
    vin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r'^[A-HJ-NPR-Z0-9]{17}$')] | None = None
    recover: bool = True
    # Debug switch: which recovery provider may be called. "auto" tries MarketCheck, then search only on a miss.
    recovery_source: Literal["auto", "marketcheck", "search"] = "auto"

    @model_validator(mode="after")
    def has_content(self):
        if not self.url and not self.text:
            raise ValueError("Provide a URL or pasted listing text")
        return self


RecoveryStatus = Literal[
    "recovered",         # Successfully recovered from licensed inventory or search
    "identity_only",     # Only NHTSA VIN decode succeeded; listing details unknown
    "identity_conflict", # Sources disagree on VIN or identity
    "not_found",         # No matching listing found
    "not_listing",       # URL is a search/category page, not a single listing
    "failed",            # Recovery attempted but failed (provider error)
    "disabled",          # Recovery was disabled or URL invalid
    "unavailable",       # No recovery provider configured
]


class ImportResponse(Model):
    status: Literal["success", "partial", "restricted", "unsupported", "blocked", "failed"]
    candidate: Candidate | None = None
    message: str
    attempts: list[RetrievalAttempt] = Field(default_factory=list)
    recovery_status: RecoveryStatus | None = None


class CompareRequest(Model):
    candidates: Annotated[list[Candidate], Field(min_length=2, max_length=3)]
    preferences: Preferences

    @field_validator("candidates")
    @classmethod
    def distinct_ids(cls, values):
        if len({c.id for c in values}) != len(values):
            raise ValueError("Candidate ids must be unique")
        return values


class Finding(Model):
    title: Short
    detail: Annotated[str, StringConstraints(max_length=5000)]
    candidate_ids: list[str]
    evidence_fields: list[str]


class Metric(Model):
    label: str
    values: list[str]


class Questions(Model):
    candidate_id: str
    questions: list[str]


class Market(Model):
    status: str = "unavailable"
    message: str
    comparables: list[dict] = Field(default_factory=list)


class Claim(Model):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=700)]
    # Ids of tool results fetched during the analysis run that support the text.
    citations: Annotated[list[Short], Field(min_length=1, max_length=12)]


class VehicleAnalysis(Model):
    candidate_id: Short
    summary: Claim | None = None
    # The report calls these green and red flags; up to five each, and only ones that were cited.
    strengths: Annotated[list[Claim], Field(max_length=5)] = Field(default_factory=list)
    risks: Annotated[list[Claim], Field(max_length=5)] = Field(default_factory=list)


class ComparisonPoint(Model):
    topic: Short
    claim: Claim
    favors: Short | None = None


class AIQuestion(Model):
    candidate_id: Short
    text: Short


class SourceRef(Model):
    id: Short
    label: Short
    url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    detail: Annotated[str, StringConstraints(max_length=1500)] = ""


class RankedVehicle(Model):
    """One position in the model's re-rank. The reason is citation-gated like any other claim."""
    candidate_id: Short
    position: Annotated[int, Field(ge=1, le=3)]
    claim: Claim


class AIAnalysis(Model):
    status: Literal["complete", "partial", "unavailable"]
    message: Short = ""
    model: Short = ""
    verdict: Claim | None = None
    vehicles: list[VehicleAnalysis] = Field(default_factory=list)
    comparisons: Annotated[list[ComparisonPoint], Field(max_length=8)] = Field(default_factory=list)
    questions: Annotated[list[AIQuestion], Field(max_length=12)] = Field(default_factory=list)
    # Empty unless the model ordered every car and every reason passed the citation gate.
    ranking: Annotated[list[RankedVehicle], Field(max_length=3)] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    tool_calls: int = 0
    dropped_claims: int = 0


class NHTSARecall(Model):
    campaign_number: Short = ""
    component: Short = ""
    summary: Annotated[str, StringConstraints(max_length=1000)] = ""
    report_date: Short | None = None
    url: Annotated[str, StringConstraints(max_length=2048)] | None = None


class NHTSAComplaint(Model):
    odi_number: Short = ""
    component: Short = ""
    summary: Annotated[str, StringConstraints(max_length=1000)] = ""
    date_filed: Short | None = None
    url: Annotated[str, StringConstraints(max_length=2048)] | None = None


class NHTSASafetyData(Model):
    """Model-year safety data (not VIN-specific); scope label always present."""
    scope: str = "Model-Year Safety Data (not VIN-specific)"
    year: int | None = None
    make: str | None = None
    model: str | None = None
    recalls_count: int | None = None
    complaints_count: int | None = None
    overall_rating: str | None = None
    frontal_rating: str | None = None
    side_rating: str | None = None
    rollover_rating: str | None = None
    # Model-year pages for the clickable counts; never a VIN-specific or /vehicle/{VehicleId} link.
    recalls_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    complaints_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    recalls: Annotated[list[NHTSARecall], Field(max_length=10)] = Field(default_factory=list)
    complaints: Annotated[list[NHTSAComplaint], Field(max_length=10)] = Field(default_factory=list)


class ConstraintCheck(Model):
    """How one stated constraint reads against one car's reviewed evidence.

    `not_established` means the listing is silent, which is never shown as a "no"; `unknown` means
    the field is missing, conflicting or in an unusable unit.
    """
    field: ConstraintField
    constraint: Short
    status: Literal["meets", "conflicts", "not_established", "unknown"]
    detail: Annotated[str, StringConstraints(max_length=600)]


class ShortlistEntry(Model):
    """Deterministic constraint-fit position. The checks are the whole basis; there is no score."""
    candidate_id: Short
    position: Annotated[int, Field(ge=1, le=3)]
    meets: Annotated[int, Field(ge=0, le=100)]
    conflicts: Annotated[int, Field(ge=0, le=100)]
    open_items: Annotated[int, Field(ge=0, le=100)]
    checks: Annotated[list[ConstraintCheck], Field(max_length=80)] = Field(default_factory=list)
    rationale: Annotated[str, StringConstraints(max_length=900)]


# Fixed label for the search-derived dealer block: what it is, and what it is not.
DEALER_SIGNAL_SCOPE = "Dealer business signals from search excerpts (allegations and public records, not verified)"


class DealerSignal(Model):
    """One search excerpt about the selling business, kept as the provider returned it.

    RevRank never fetches these pages: the title, snippet and date are the search provider's own,
    which is why an excerpt is evidence of what a page says and nothing more. Review platforms are
    excluded upstream, so no rating or review text reaches this model.
    """
    id: Nonempty
    # regulator: a .gov page. board: a consumer complaint board. news: a dated article elsewhere.
    category: Literal["regulator", "board", "news"]
    label: Short
    url: Link
    host: Short
    excerpt: Short
    # Only when the provider dated the page; search excerpts are otherwise undated.
    published: Short | None = None
    query: Short = ""

    @field_validator("url")
    @classmethod
    def link_is_reference(cls, value):
        return reference_url(value)


class DealerSignals(Model):
    """Thin, cited dealer flags plus the excerpts they came from.

    A flag is only ever a reading of the excerpts below it, never a verdict on the business and
    never a score: nothing here is aggregated into a number or a star rating.
    """
    scope: str = DEALER_SIGNAL_SCOPE
    status: Literal["complete", "partial", "unavailable", "disabled"]
    message: Short = ""
    dealer_name: Short | None = None
    model: Short = ""
    searches: Annotated[int, Field(ge=0, le=10)] = 0
    # Provider credits the searches cost, as the provider prices them.
    credits: Annotated[int, Field(ge=0, le=40)] = 0
    signals: Annotated[list[DealerSignal], Field(max_length=12)] = Field(default_factory=list)
    green: Annotated[list[Claim], Field(max_length=3)] = Field(default_factory=list)
    red: Annotated[list[Claim], Field(max_length=3)] = Field(default_factory=list)
    caveats: Annotated[list[Short], Field(max_length=8)] = Field(default_factory=list)
    dropped_claims: Annotated[int, Field(ge=0, le=100)] = 0


class Report(Model):
    id: str
    created_at: str
    title: str
    summary: str
    analysis_mode: Literal["llm", "rules"] = "rules"
    preferences: Preferences
    candidates: list[Candidate]
    findings: list[Finding]
    metrics: list[Metric]
    questions: list[Questions]
    market: Market
    warnings: list[str]
    ai_analysis: AIAnalysis | None = None
    cross_model: bool = False
    nhtsa_data: dict[str, NHTSASafetyData] = Field(default_factory=dict)
    # Keyed by candidate id. Server-authored during the report run, never accepted from a request.
    dealer_signals: dict[str, DealerSignals] = Field(default_factory=dict)
    # Deterministic constraint-fit order; always present, and the fallback when the model has no ranking.
    shortlist: Annotated[list[ShortlistEntry], Field(max_length=3)] = Field(default_factory=list)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def value_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)
