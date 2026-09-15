"""Private in-app browse of one buyer-supplied listing URL.

This is a recovery fallback after Direct is blocked: a headless Chromium session on the
server opens only the URL the buyer pasted, like a private browse, then returns the rendered
HTML to the existing extractor. It is not a crawler, not a cloud-agent spawn, and not a
bot-manager bypass.

Limits (enforced here, not by prompt):
- Navigate only to the validated user-supplied URL. Same-host subresources may load so the
  page can render; review/complaint/social hosts are aborted; document navigations off the
  listing's registrable domain are aborted.
- Review sites and dealer boards are refused even if the operator allowlisted the host.
- An explicit robots.txt Disallow or crawl-delay refuses the browse. If robots.txt cannot be
  read (HTTP 403, HTML interstitial — the CarMax/Render case), we still open that one URL:
  that is not a site crawl. A challenge or 403 on the listing itself is reported as blocked;
  no stealth, proxies, cookies, or CAPTCHA solving.
- Dealer-signals search is untouched. This module never searches and never opens a review page.
"""
from urllib.parse import urlsplit
import logging
import time

from .cancel import Cancelled, budget as cancel_budget, closing
from .config import Settings
from .fetch import ACCESS_CHALLENGE, FetchError, Page, check_robots, remaining, validated_url
from .listing_url import MARKETPLACES, bare_host, is_listing_url, same_listing
from .sources import source_for

log = logging.getLogger("revrank.browse")

# v1 host allowlist: CarMax, Carvana, and hosts whose single-listing URL we already recognize.
# Unknown hosts are blocked. This is not counsel clearance; the feature flag stays off until Tongli opts in.
BROWSE_VDP_HOSTS = MARKETPLACES
PASTE_HINT = "Paste the price, mileage, and VIN from the listing to continue."
# Review, complaint, social and directory hosts. Marketplace VDPs (CarMax, Carvana, Cars.com, …)
# are not in this list: those are the listing pages a buyer pastes. Dealer-signals uses a wider
# deny list because it must not quote review platforms; this path must still open a CarMax VDP.
REVIEW_HOSTS = (
    "yelp.com", "dealerrater.com", "bbb.org", "consumeraffairs.com",
    "complaintsboard.com", "pissedconsumer.com", "ripoffreport.com", "reddit.com", "quora.com",
    "trustpilot.com", "birdeye.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "tiktok.com", "youtube.com", "linkedin.com", "yellowpages.com", "mapquest.com", "indeed.com",
    "glassdoor.com", "pinterest.com", "nextdoor.com", "wikipedia.org", "medium.com", "substack.com",
)
CHALLENGE = ACCESS_CHALLENGE
# Images and media are not listing fields. Aborting them keeps the session short.
SKIP_RESOURCES = frozenset({"image", "media", "font", "websocket"})


class BrowseError(Exception):
    """Structured browse failure. `status` is the retrieval-attempt status string."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def registrable(host: str) -> str:
    host = host.lower().removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 1 else host


def is_review_host(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return registrable(host) in REVIEW_HOSTS or any(host.endswith("." + d) for d in REVIEW_HOSTS)


def browse_vdp_allowed(url: str) -> tuple[bool, str]:
    """Single buyer-supplied VDP on the v1 host allowlist, or a refused reason."""
    host = bare_host(url)
    if is_review_host(host):
        return False, f"Review sites and dealer boards are not opened. {PASTE_HINT}"
    if host not in BROWSE_VDP_HOSTS:
        return False, ("This website is not on the private-browse allowlist "
                       "(CarMax, Carvana, and recognized listing hosts). " + PASTE_HINT)
    if is_listing_url(url) is not True:
        return False, ("Private browse opens one vehicle listing page, not a search or category page. "
                       + PASTE_HINT)
    return True, ""


def robots_decision(url: str, settings: Settings, deadline: float) -> tuple[bool, str]:
    """Whether this single URL may be opened, plus a note for the attempt log.

    Explicit Disallow / crawl-delay / restricted source → refuse.
    Unreadable robots.txt (403, HTML interstitial) → allow this one URL only.
    """
    try:
        check_robots(url, settings, deadline)
        return True, ""
    except FetchError as error:
        message = error.message
        if error.status in ("restricted", "unsupported"):
            return False, message
        if "disallows this listing path" in message or "crawl schedule" in message:
            return False, message
        return True, message


def browse_listing(url: str, settings: Settings, token=None, timeout: float = 20.0) -> Page:
    """Open `url` in a private headless session and return the rendered HTML.

    Raises BrowseError or Cancelled. Never launches a browser for a refused URL.
    """
    if token is not None:
        token.check()
    url, host, _ = validated_url(url)
    allowed_vdp, refused = browse_vdp_allowed(url)
    if not allowed_vdp:
        raise BrowseError("refused", refused)
    source = source_for(host, settings)
    if source["status"] != "allowed":
        raise BrowseError("refused", source["reason"])
    seconds = cancel_budget(token, timeout, minimum=2.0) if token is not None else max(2.0, timeout)
    deadline = time.monotonic() + seconds
    allowed, robots_note = robots_decision(url, settings, deadline)
    if not allowed:
        raise BrowseError("refused", robots_note or "robots.txt does not allow this listing path.")
    if token is not None:
        token.check()
    try:
        left = remaining(deadline)
    except FetchError:
        raise BrowseError("timeout", f"Private browse exceeded its time limit. {PASTE_HINT}") from None
    page = _playwright_open(url, host, token, cancel_budget(token, left, minimum=1.0) if token is not None else left)
    if robots_note:
        # Could not read robots.txt; the page was still opened. Callers log the browse attempt.
        log.info("browse proceeded without a readable robots.txt host=%s", host)
    return page


def _playwright_open(url: str, host: str, token, timeout: float) -> Page:
    """Launch Chromium for one URL. Tests replace this; CI never calls the real launcher."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowseError("failed", "Private-browser recovery is not installed on this server.") from None

    timeout_ms = max(1000, int(timeout * 1000))
    target_reg = registrable(host)
    browser = None

    def abort():
        if browser is not None:
            try:
                browser.close()
            except Exception:
                log.debug("browse closer could not close Chromium")

    try:
        playwright = sync_playwright().start()
    except Exception:
        raise BrowseError("failed", "Private-browser recovery could not start on this server.") from None
    try:
        try:
            browser = playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        except Exception:
            raise BrowseError(
                "failed",
                "Private-browser recovery is not available on this server (Chromium is not installed).",
            ) from None
        with closing(token, abort):
            if token is not None:
                token.check()
            context = browser.new_context(accept_downloads=False, java_script_enabled=True)
            page = context.new_page()

            def handle_route(route):
                request = route.request
                req_host = (urlsplit(request.url).hostname or "").lower()
                if is_review_host(req_host) or request.resource_type in SKIP_RESOURCES:
                    return route.abort()
                if request.resource_type == "document" and registrable(req_host) != target_reg:
                    return route.abort()
                return route.continue_()

            page.route("**/*", handle_route)
            page.set_default_timeout(timeout_ms)
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if token is not None:
                token.check()
            if response is not None:
                status = response.status
                if status in (401, 403, 429):
                    raise BrowseError(
                        "blocked",
                        f"The private browse received HTTP {status} (access denied or rate limited). "
                        f"No bypass was attempted. {PASTE_HINT}",
                    )
                if status in (404, 410):
                    raise BrowseError("failed", "Listing is unavailable or removed. This does not indicate a confirmed sale.")
                if status >= 400:
                    raise BrowseError("failed", f"The private browse received HTTP {status}.")
            settle_ms = min(1500, max(0, timeout_ms // 4))
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            if token is not None:
                token.check()
            final_url = page.url or url
            if urlsplit(final_url).hostname and not same_listing(final_url, url):
                raise BrowseError(
                    "failed",
                    "The listing redirected to a different page (usually a search page), so it appears to be "
                    "sold or removed. This does not confirm a sale.",
                )
            text = page.content()
            if CHALLENGE.search(text[:20000]):
                raise BrowseError("blocked", f"Source returned an access challenge; no bypass was attempted. {PASTE_HINT}")
            return Page(text=text, url=final_url)
    except BrowseError:
        raise
    except Cancelled:
        raise
    except PlaywrightTimeout:
        raise BrowseError("timeout", f"Private browse exceeded its time limit. {PASTE_HINT}") from None
    except PlaywrightError:
        raise BrowseError("failed", "Private browse could not open this listing.") from None
    finally:
        abort()
        try:
            playwright.stop()
        except Exception:
            pass
