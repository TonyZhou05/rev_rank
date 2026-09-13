"""Entirely invented fixtures: no real inventory, VINs or market observations."""
from .models import Candidate, Evidence, now, value_text


def demo_candidates() -> list[Candidate]:
    examples = [
        dict(id="demo-m2", title="2021 BMW M2 Competition · SYNTHETIC", make="BMW", model="M2",
             trim="Competition", generation="F87", year=2021, price=54800, mileage=24500,
             transmission="6-speed manual", features=["Heated seats", "Apple CarPlay", "Rear seats"],
             history="Synthetic seller claim: service records available; accident history unverified."),
        dict(id="demo-supra", title="2022 Toyota GR Supra 3.0 Premium · SYNTHETIC", make="Toyota",
             model="GR Supra", trim="3.0 Premium", generation="A90", year=2022, price=51900, mileage=18300,
             transmission="8-speed automatic", features=["Heated seats", "Apple CarPlay", "Two seats"],
             history="Synthetic seller claim: one owner; service and accident history unverified."),
        dict(id="demo-cayman", title="2020 Porsche 718 Cayman · SYNTHETIC", make="Porsche",
             model="718 Cayman", trim="Base", generation="982", year=2020, price=56900, mileage=31200,
             transmission="6-speed manual", features=["Sport Chrono", "Two seats"],
             history=None),
    ]
    result = []
    for example in examples:
        example.update(currency="USD", mileage_unit="mi", location="Synthetic example · Austin, TX",
                       source_kind="synthetic", source_url=None)
        evidence = {k: Evidence(value=value_text(v), source="Invented RevRank demonstration fixture",
                               status="synthetic")
                    for k, v in example.items() if v is not None and k not in ("id", "source_kind", "source_url")}
        evidence["price_type"] = Evidence(value="asking", source="Synthetic example", status="synthetic")
        evidence["observed_at"] = Evidence(value=now(), source="Fixture generated at", status="synthetic")
        result.append(Candidate(**example, evidence=evidence,
            warnings=["SYNTHETIC DEMO: all listing details and prices are invented, not live listings or market evidence.",
                      "Synthetic equipment and history must not be treated as verified specifications."]))
    return result
