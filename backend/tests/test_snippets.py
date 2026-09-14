"""Site-specific excerpt parsing. Each text mirrors a real excerpt shape (docs/parsing-notes.md); VINs,
stock numbers and places are synthetic."""
import pytest

from backend.app.extraction import extract, normalize_location
from backend.app.snippets import listed_date, single_vehicle_page, snippet_text

VIN = "WBS1H9C50HV123456"
LISTING = "https://www.carmax.com/car/26789012"


def parse(text, url, loose=None):
    loose = single_vehicle_page(url, LISTING, VIN) if loose is None else loose
    candidate, _ = extract(snippet_text(text, url), url, fetched=True, loose=loose)
    return {k: getattr(candidate, k) for k in ("year", "model", "price", "mileage", "location", "transmission",
                                               "engine", "drivetrain", "body") if getattr(candidate, k) is not None}


@pytest.mark.parametrize("url,text,expected", [
    # CarMax card: price just above "About this car"; store location in "City, State".
    ("https://www.carmax.com/cars/bmw?location=rochester+ny",
     f"$40,998. About this car. Stock: 26789012. VIN: {VIN}. Base specifications. Body: 2D Coupe; Vehicle Size: Compact; "
     "Type: Coupes; Mileage: 18,000; City, State: Canoga Park, California; Prior Use:",
     {"price": 40998, "mileage": 18000, "location": "Canoga Park, CA", "body": "2D Coupe"}),
    # CarMax cut off inside "City, State": the partial place is dropped, and the URL's search area is not used.
    ("https://www.carmax.com/cars/luxury-vehicles?location=rochester+ny",
     f"VIN: {VIN}. Base specifications. Body: 2D Coupe; Vehicle Size: Compact; Mileage: 18,000; City, State: East",
     {"mileage": 18000, "body": "2D Coupe"}),
    # TrueCar card: distance is from the shopper, the place after "transfer" is the car's.
    ("https://www.truecar.com/used-cars-for-sale/listings/bmw/body-coupe/location-x/",
     f"G Advertised price $42,500 Great price. VIN: {VIN} 313 mi away • $149 transfer • Amherst, NY",
     {"price": 42500, "location": "Amherst, NY"}),
    # Edmunds card: "Located in"; unlabeled price/mileage before the VIN may be a neighbor's and is ignored.
    ("https://www.edmunds.com/used-bmw-m2-keyport-nj",
     f"BMW M2 Base Coupe $69,333 great price 23,163 miles 6cyl. VIN: {VIN} Stock: 26789012 Certified Pre-Owned: No "
     "Close Located in Southern Pines, NC / 432 miles away from Tallahassee, FL",
     {"location": "Southern Pines, NC"}),
    # DealerRater ad page (VIN in the URL): one vehicle, described in sentences.
    (f"https://www.dealerrater.com/classifieds/2017-BMW-M2-ad-{VIN}-1/",
     f"See the used 2017 BMW M2 priced at $16998. The M2 with a VIN of {VIN} is located in Canoga Park, CA, has 128055 miles,",
     {"year": 2017, "model": "M2", "price": 16998, "mileage": 128055, "location": "Canoga Park, CA"}),
    # hypercars listing page: dealer name with "Ft." before the real place.
    ("https://hypercars.io/listing/2017-bmw-m2-1",
     f"... {VIN}. 2017 BMW M2. Listed byCarmax Ft. Myers. Fort Myers, FL 8,522 miles Automatic. Live. Asking$41,998.",
     {"year": 2017, "model": "M2", "price": 41998, "mileage": 8522, "location": "Fort Myers, FL"}),
    # autofinder page: "Label. Value." fields; the trailing "42 mi." is distance, not mileage.
    (f"https://autofinder.com/marketplace/vehicle-detail?zip=10011&vin={VIN}",
     f"MPG. 15 City / 27 Highway. Drive Train. RWD. Transmission. Automatic. Engine. 3.0L I6. VIN. {VIN}. Body Type. Coupe. "
     "Dealer. CarMax Smithtown. 42 mi.",
     {"transmission": "Automatic", "engine": "3.0L I6", "drivetrain": "RWD", "body": "Coupe"}),
    # visor.vin pipe table.
    (f"https://visor.vin/search/listings/{VIN}",
     f"| | | | | --- --- | | VIN | {VIN} | Transmission | Automatic | | Exterior Color | Alpine White | Drivetrain | RWD | "
     "| Body Style | Coupe | Assembled In | Not specified | | Engine | 3.0L I6 | Warranty Status | Login",
     {"transmission": "Automatic", "engine": "3.0L I6", "drivetrain": "RWD", "body": "Coupe"}),
    # CarGurus search page: the heading is about the page, not this car.
    ("https://www.cargurus.com/Cars/s-Used-White-BMW-M2-Monroe-d2396",
     f"{VIN}. White 2016 BMW M2 Coupe Rear-Wheel Drive Automatic. New arrival. Save this listing.", {}),
])
def test_site_formats(url, text, expected):
    assert parse(text, url) == expected


def test_dated_history_record():
    text = f"VIN: {VIN} vin checkout link Listed for sale on: 2026-08; Price: $35,000; Odometer: 39,600; Coupe body style."
    assert listed_date(text) == "2026-08"
    assert parse(text, "https://vininspect.com/vin/bmw/m2/2017/wbs1h9c5?page=3") == {"price": 35000, "mileage": 39600}


@pytest.mark.parametrize("raw,expected", [("Canoga Park, California", "Canoga Park, CA"), ("Madison, Tennessee; Prior", "Madison, TN"),
                                          ("Fort Myers, FL", "Fort Myers, FL"), ("Austin, TX, US", "Austin, TX"),
                                          ("Synthetic example · Austin, TX", "Synthetic example · Austin, TX")])
def test_location_normalization(raw, expected):
    assert normalize_location(raw) == expected


def test_dated_history_never_fills_current_values(monkeypatch):
    from backend.app import retrieval
    from backend.app.config import Settings
    from backend.app.models import ImportRequest, ImportResponse
    from backend.app.search import SearchResult
    monkeypatch.setattr(retrieval, "search", lambda q, s, timeout=10, domain=None: [
        SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=f"Stock: 26789012. VIN: {VIN}. Mileage: 40,047; Body: 2D Coupe"),
        SearchResult(url="https://vininspect.com/vin/bmw/m2/2017/wbs1h9c5?page=3",
                     text=f"VIN: {VIN} Listed for sale on: 2026-08; Price: $35,000; Odometer: 39,600;")])
    candidate = retrieval.recover_listing(ImportRequest(url=LISTING), Settings(search_api_key="t"),
                                          ImportResponse(status="blocked", message="403")).candidate
    assert candidate.price is None and candidate.mileage == 40047
    assert not any("different mileage" in w for w in candidate.warnings)
    dated = [o for o in candidate.observations if o.observed_at == "2026-08"]
    assert {(o.field, o.value) for o in dated} >= {("price", "35000.0"), ("mileage", "39600.0")}


def test_carmax_excerpt_is_scoped_to_the_vins_card():
    text = ("Type: SUVs; Mileage: 61,200; City, State: Miami Lakes, Florida; Prior Use: Rental. "
            f"$40,998. About this car. Stock: 26789012. VIN: {VIN}. Base specifications. Body: 2D Coupe; "
            "Mileage: 18,000; City, State: Rochester, New York; Prior Use: Personal. $30,000. About this car. Stock: 111.")
    assert parse(text, "https://www.carmax.com/cars/bmw?location=miami+fl") == {
        "price": 40998, "mileage": 18000, "location": "Rochester, NY", "body": "2D Coupe"}


def test_focused_location_query_runs_only_when_location_is_missing(monkeypatch):
    from backend.app import retrieval
    from backend.app.config import Settings
    from backend.app.models import ImportRequest, ImportResponse
    from backend.app.search import SearchResult
    calls = []

    def search(query, settings, timeout=10, domain=None):
        calls.append((query, domain))
        if query.endswith('"City, State"'):
            return [SearchResult(url="https://www.carmax.com/cars/bmw", text=f"VIN: {VIN}. Base specifications. Mileage: 18,000; "
                                                                             "City, State: Rochester, New York; Prior Use:")]
        # Earlier queries already fill the per-site cap with distinct CarMax excerpts that stop before "City, State".
        return [SearchResult(url=f"https://www.carmax.com/cars/bmw/m2?p={i}",
                             text=f"Stock: 26789012. VIN: {VIN}. Base specifications. Mileage: 18,000; Type: Coupes {i}") for i in range(4)]
    monkeypatch.setattr(retrieval, "search", search)
    candidate = retrieval.recover_listing(ImportRequest(url=LISTING), Settings(search_api_key="t"),
                                          ImportResponse(status="blocked", message="403")).candidate
    assert candidate.location == "Rochester, NY"
    assert calls[-1] == (f'"{VIN}" "City, State"', "carmax.com") and len(calls) == 4


def test_provider_elision_ends_a_field():
    text = f"About this car. Stock: 26789012. VIN: {VIN}. Base specifications. Body: 4D Sport Utility .. Vehicle ... City, State: Rochester, New York; Prior Use:"
    assert parse(text, "https://www.carmax.com/cars/honda") == {"body": "4D Sport Utility", "location": "Rochester, NY"}


def test_vininspect_neighbor_record_and_price_hint(monkeypatch):
    # Real C43 shape: the previous VIN's record ($26,605 / 50,840) precedes this VIN's record in one excerpt.
    from backend.app import retrieval
    from backend.app.config import Settings
    from backend.app.models import ImportRequest, ImportResponse
    from backend.app.search import SearchResult
    history = (f"Price: $26,605; Odometer: 50,840;. 2017 BMW M2. VIN: {VIN}. vin checkout link. "
               "Listed for sale on: 2026-08; Price: $33,140; Odometer: 38,330;.")
    assert "26,605" not in snippet_text(history, "https://vininspect.com/vin/bmw/m2/2017/wbs1h9c5")
    monkeypatch.setattr(retrieval, "search", lambda q, s, timeout=10, domain=None: [
        SearchResult(url="https://www.carmax.com/cars/bmw/m2", text=f"Stock: 26789012. VIN: {VIN}. Base specifications. Mileage: 39,017"),
        SearchResult(url="https://vininspect.com/vin/bmw/m2/2017/wbs1h9c5", text=history)])
    candidate = retrieval.recover_listing(ImportRequest(url=LISTING), Settings(search_api_key="t"),
                                          ImportResponse(status="blocked", message="403")).candidate
    # No current price: unknown, not "sources disagree", with the dated past listing as a hint.
    assert candidate.price is None and "price" not in candidate.conflicts
    assert candidate.evidence["last_listed_price"].value == "$33,140 (2026-08)"
