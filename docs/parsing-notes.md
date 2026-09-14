# Parsing notes: where each field really comes from

Recorded 2026-09-13 from 60 real search excerpts: exact-VIN and VIN + "price" queries for six
vehicles, run through the configured provider (Tavily). Raw excerpts are kept locally in
`.local/eval/snippets.json`. The rules are in `backend/app/snippets.py`, and each rule's excerpt shape
is a regression test in `backend/tests/test_snippets.py`. Update all three together.

## First principle: page kind decides how much to trust unlabeled text

| Page kind | How to recognize it | Parsing |
| --- | --- | --- |
| Single vehicle | the input listing itself; a URL containing the VIN (visor.vin, DealerRater ad, Capital One, autofinder `?vin=`, Edmunds `/vin/`); a recognized listing URL; a `/listing/`, `/vehicle-details/`, `/vdp/`, `/classifieds/` path | loose: labels, titles ("2017 BMW M2"), summary sentences, unlabeled "N miles" |
| Many vehicles | search, model, and inventory pages (CarMax `/cars/...`, Edmunds `/used-...-city-st`, CarGurus `/Cars/l-...`, Cars.com `/shopping/...`) | strict: labeled fields and record-structured site rules only |

Why this matters: on Edmunds search pages the text *before* a VIN often belongs to the previous
card. For example, `2018 BMW M4 Base Convertible $41,995 ... VIN: WBS33BA06NCJ75401` is attached to a
2022 M4, and `BMW M4 Base Coupe $69,333 ... 23,163 miles` is attached to a convertible. CarGurus
market-analysis headings ("2021 BMW M4s for sale") describe the page, not the VIN beside them.

## Location

**The URL `?location=` parameter is the shopper's search area, never the car's location.** One
Wrangler appeared on CarMax pages for `?location=burbank+ca` and `?location=san+fernando+ca`, while its
record said `City, State: Canoga Park, California`. The Camaro was on `?location=franklin+tn` but
located in Madison, Tennessee. Use location only from inside the vehicle's record:

| Site | Excerpt shape | Rule |
| --- | --- | --- |
| CarMax | `City, State: Canoga Park, California; Prior Use:` | label, scoped to the VIN's own card (see below); often cut off (`City, State: East`), so a place without its state is dropped |
| TrueCar | `313 mi away • $149 transfer • Amherst, NY` | the place after "transfer"; "mi away" is distance from the shopper |
| Edmunds | `Located in Southern Pines, NC / 432 miles away from Tallahassee, FL` | the place after "Located in"; the second place is the shopper's |
| DealerRater | `is located in Canoga Park, CA, has 128055 miles` | sentence on the single-vehicle ad page |
| hypercars | `Listed byCarmax Ft. Myers. Fort Myers, FL 8,522 miles` | the place before the mileage; the dealer name "Ft. Myers" is not the place |
| autofinder, Cars.com, Capital One | `Dealer. CarMax Smithtown.`, `More details from CarMax Canoga Park` | dealer name only, without a state; recorded but not used as location |
| Carvana | `Used 2014 Honda Civic LX Sedan 4D for $15990 with 44186 miles` | no location at all: Carvana delivers and its summaries never say where the car is; location stays unknown |

**CarMax card scoping.** A card reads `$40,998. About this car. Stock: N. VIN: V. Base specifications.
... City, State: X`. One excerpt can hold neighboring cards: the M2's excerpts also contained "Miami
Lakes, Florida", and the Wrangler's "Buena Park", which belong to other cars. Only the span from the
VIN card's price (or its `Stock:`) to the next card's price and `About this car` is parsed.

**Focused query.** "City, State" ends a CarMax card, so excerpts often stop before it. When the regular
queries find no location, recovery spends one more seller-scoped query, `"<VIN>" "City, State"` on
carmax.com, which centers the excerpt on that field. That makes four queries at most.

**Stopping early.** Without a VIN (Carvana), recovery stops querying only once an excerpt of the
listing's own page gives its price or mileage. A title-only excerpt ("Title: 2014 Honda Civic |
Carvana") is not enough.

Places are normalized to `City, ST` ("Canoga Park, California" and "Canoga Park, CA" agree).
Locations legitimately differ over time because CarMax transfers cars between stores. For example, the
Camaro showed Madison, TN (CarMax), Southern Pines, NC (Edmunds), and Fort Myers, FL (hypercars). The
seller's own value wins; the others remain visible as observations.

## Price

| Site | Excerpt shape | Rule |
| --- | --- | --- |
| CarMax | `$40,998. About this car. Stock: 70181882. VIN: ...` | the price just before "About this car" belongs to that card; glued prices (`$62,998$63,998`) and `$1,091/mo` are not used |
| TrueCar | `Advertised price $62,998 Great price` | "Advertised price" label |
| DealerRater | `priced at $16998` | sentence on the single-vehicle page |
| hypercars | `Asking$71,998` | "Asking" label |
| vininspect | `Listed for sale on: 2026-08; Price: $35,000; Odometer: 39,600` | a dated past listing: kept as an observation with observed_at = that month, and never used to fill today's price, mileage or location (for the M2 it showed $35,000 while CarMax asks $40,998). Records are scoped at their VIN: an excerpt can start with the previous car's `Price: $26,605; Odometer: 50,840;.` (the C43, carmax.com/car/28033756). When no current price exists, the latest past listing appears as a separate "last listed" hint |
| Edmunds / CarGurus search pages | `$69,333 great price $5,929 below market`, `average price of $64,880.00` | ignored: neighbor cards, deltas, or market averages |

## Mileage, transmission, engine, drivetrain, body

| Site | Excerpt shape | Notes |
| --- | --- | --- |
| CarMax | `Mileage: 40,047; ... Body: 2D Coupe; Vehicle Size: Compact; Type: Coupes` | fields sometimes separated by spaces only; split on known labels, and keep "Body Type" as one label |
| visor.vin | `\| Transmission \| Automatic \| \| Drivetrain \| RWD \| \| Engine \| 3.0L I6 \|` | pipe table |
| autofinder | `Drive Train. RWD. Transmission. Automatic. Engine. 6.2L V8. ... Dealer. CarMax Smithtown. 42 mi.` | "Label. Value." (a period before a digit stays in the value); the trailing "42 mi." is distance, not mileage |
| Cars.com | `Engine: Gas. Stock #: 28741361` | "Engine" holds the fuel type; the VIN decode supplies the real engine |
| Any | several mileage readings for one VIN | an odometer only goes up: show the seller's reading (the pasted site): the value most of its excerpts agree on, the higher on a tie. When the seller has none, show the highest reading. For the 2024 Rubicon, seven CarMax excerpts said 2,322 and one leaked card said 21,252; vininspect dated 2,072 in 2026-07. Report a disagreement only when another source is higher; lower readings are older observations |
| NHTSA vPIC | engine, drive type, fuel, transmission style/speeds, trim, body | engine, drivetrain and fuel prefer the VIN decode; transmission, trim and body prefer the listing (VINs often don't encode a manual gearbox; vPIC's body names are coarse) |

Colors (`Exterior Color: Alpine White`, `White 2017 BMW M2`) and the dealer name are available but not
yet modeled as candidate fields.

## Adding a site

1. Save real excerpts for a few vehicles (exact-VIN queries) and look for the record boundary: where
   one car's fields end and the next car's begin.
2. Add rules to `SITE_RULES` only for values that are inside that boundary.
3. Add each shape to `backend/tests/test_snippets.py`, then run `scripts/eval_imports.py` on real URLs.
