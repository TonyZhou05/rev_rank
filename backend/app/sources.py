"""Permission registry. Operator configuration is not a legal clearance."""
from urllib.parse import urlsplit

from .config import Settings

REGISTRY = (
    ("carmax.com", "CarMax", "unsupported", "Operator opt-in required; live extraction coverage must be tested."),
    ("carvana.com", "Carvana", "unsupported", "Operator opt-in required; live extraction coverage must be tested."),
    ("edmunds.com", "Edmunds", "unsupported", "Operator opt-in required; live extraction coverage must be tested."),
    ("kbb.com", "Kelley Blue Book", "unsupported", "Operator opt-in required; live extraction coverage must be tested."),
    ("autolist.com", "Autolist", "unsupported", "Operator opt-in required; live extraction coverage must be tested."),
    ("caredge.com", "CarEdge", "restricted", "Published terms restrict unauthorized scraping/reuse; obtain permission and review current terms before integration."),
    ("cargurus.com", "CarGurus", "restricted", "Known restrictions on unauthorized automated collection/reuse; no built-in permission or bypass."),
    ("autotrader.com", "Autotrader", "unsupported", "Collection, retention and display rights have not been reviewed."),
    ("cars.com", "Cars.com", "unsupported", "Collection, retention and display rights have not been reviewed."),
    ("carfax.com", "CARFAX", "unsupported", "No approved collection or vehicle-history data integration."),
    ("truecar.com", "TrueCar", "unsupported", "No approved source adapter or data-use review."),
    ("classic.com", "CLASSIC.COM", "unsupported", "A licensed integration and its permitted uses need separate review."),
)


def source_for(domain: str, settings: Settings) -> dict:
    domain = domain.lower().rstrip(".")
    prior = next((r for r in REGISTRY if domain == r[0] or domain.endswith("." + r[0])), None)
    if domain in settings.allowed_domains:
        reason = "Exact host enabled by local operator configuration. This does not establish successful extraction or a reuse license; robots and network checks still apply."
        if prior:
            reason += " Registry note: " + prior[3]
        return dict(domain=domain, name=prior[1] if prior else domain, status="allowed", reason=reason)
    if prior:
        return dict(domain=domain, name=prior[1], status=prior[2], reason=prior[3])
    return dict(domain=domain, name=domain, status="unsupported",
                reason="RevRank has not enabled URL import for this website. No page was fetched. Paste the vehicle's listing text to continue; the URL can remain as a reference.")


def sources_response(settings: Settings) -> dict:
    domains = list(dict.fromkeys([r[0] for r in REGISTRY] + list(settings.allowed_domains)))
    return {"sources": [source_for(d, settings) for d in domains],
            "live_fetch_enabled": settings.live_fetch_enabled}
