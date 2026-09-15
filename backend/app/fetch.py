"""Bounded, public-address-pinned fetching. No proxies, cookies, retries or block bypass."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import certifi
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .config import Settings
from .sources import source_for

USER_AGENT = "RevRank/0.1"
MAX_BYTES = 2_000_000
ROBOTS_BYTES = 256_000
ACCESS_CHALLENGE = re.compile(
    r"(verify you are human|checking your browser|access denied|captcha|cf-chl-)", re.I
)
TOTAL_SECONDS = 15
MAX_REDIRECTS = 3
_DNS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="revrank-dns")
_DNS_SLOTS = threading.BoundedSemaphore(4)


class FetchError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Page:
    text: str
    url: str


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise FetchError("failed", "Source request exceeded the total time limit.")
    return seconds


def validated_url(url: str) -> tuple[str, str, int]:
    try:
        if len(url) > 2048 or re.search(r"[\x00-\x20\x7f\\]", url):
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None:
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if "%" in host or not host:
            raise ValueError()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            raise FetchError("blocked", "Local and private hostnames are blocked.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
            if not is_public(address):
                raise FetchError("blocked", "Private, loopback, reserved and non-public addresses are blocked.")
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
                raise ValueError()
        netloc = "[" + host + "]" if ":" in host else host
        path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="/?%:@!$&'()*+,;=-._~")
        return urlunsplit((parsed.scheme, netloc, path, query, "")), host, port
    except (ValueError, UnicodeError):
        raise FetchError("blocked", "Use an HTTP(S) URL with its standard port and no credentials or invalid characters.")


def is_public(address) -> bool:
    # Reject transition mechanisms as well as ordinary non-public addresses.
    if not address.is_global or address.is_multicast or address.is_unspecified:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
    return True


def resolve_public(host: str, port: int, deadline: float) -> list[str]:
    if not _DNS_SLOTS.acquire(timeout=min(1, remaining(deadline))):
        raise FetchError("failed", "DNS resolver busy; try again later.")
    try:
        job = _DNS.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    except Exception:
        _DNS_SLOTS.release()
        raise
    job.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        records = job.result(timeout=min(4, remaining(deadline)))
    except (OSError, FutureTimeout):
        raise FetchError("failed", "Source DNS resolution failed or timed out.")
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not is_public(ipaddress.ip_address(a)) for a in addresses):
        raise FetchError("blocked", "DNS resolved to a non-public address; request blocked.")
    return addresses


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, secure: bool, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self.address, self.secure = address, secure

    def connect(self):
        # Use the validated numerical address directly; never resolve hostname a second time.
        family = socket.AF_INET6 if ":" in self.address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.address, self.port))
            if self.secure:
                context = ssl.create_default_context()
                # Some Python installations have no system CA bundle. Add the
                # maintained public roots while retaining any system trust roots.
                context.load_verify_locations(cafile=certifi.where())
                self.sock = context.wrap_socket(sock, server_hostname=self.host)
            else:
                self.sock = sock
        except BaseException:
            sock.close()
            raise


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def request_once(url: str, settings: Settings, deadline: float, limit: int) -> Response:
    url, host, port = validated_url(url)
    entry = source_for(host, settings)
    if entry["status"] != "allowed":
        raise FetchError("restricted" if entry["status"] == "restricted" else "unsupported", entry["reason"])
    addresses = resolve_public(host, port, deadline)
    parsed = urlsplit(url)
    conn = PinnedConnection(host, port, addresses[0], parsed.scheme == "https", min(4, remaining(deadline)))
    try:
        conn.request("GET", (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
                     headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/ld+json",
                              "Accept-Encoding": "identity", "Connection": "close"})
        conn.sock.settimeout(min(4, remaining(deadline)))
        response = conn.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        # Redirect and failure bodies are never consumed.
        if response.status >= 300:
            return Response(response.status, headers, b"")
        if headers.get("content-encoding", "identity").lower() not in ("", "identity"):
            raise FetchError("blocked", "Compressed source responses are unsupported; no bypass attempted.")
        length = headers.get("content-length")
        if length and (not length.isdigit() or int(length) > limit):
            raise FetchError("failed", "Source response exceeds the size limit or has an invalid length.")
        chunks, size = [], 0
        while True:
            # Connection: close can move ownership to HTTPResponse.fp, so retain its socket.
            sock = conn.sock or getattr(getattr(response.fp, "raw", None), "_sock", None)
            if sock:
                sock.settimeout(min(4, remaining(deadline)))
            remaining(deadline)
            chunk = response.read1(min(32768, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise FetchError("failed", "Source response exceeds the size limit.")
            chunks.append(chunk)
        return Response(response.status, headers, b"".join(chunks))
    except FetchError:
        raise
    except ssl.SSLCertVerificationError:
        raise FetchError("failed", "TLS certificate verification failed; check the local CA bundle or source certificate. Verification was not bypassed.")
    except (OSError, http.client.HTTPException, ValueError):
        raise FetchError("failed", "Source connection failed, timed out, or returned an invalid response.")
    finally:
        conn.close()


def redirect_target(url: str, response: Response) -> str:
    location = response.headers.get("location", "")
    if not location:
        raise FetchError("failed", "Source redirect has no destination.")
    result, _, _ = validated_url(urljoin(url, location))
    if result == validated_url(url)[0]:
        raise FetchError("blocked", "Redirect points back to the same URL.")
    if urlsplit(result).hostname != urlsplit(url).hostname:
        raise FetchError("blocked", "Cross-host redirects are blocked; submit the destination separately after review.")
    if urlsplit(url).scheme == "https" and urlsplit(result).scheme != "https":
        raise FetchError("blocked", "HTTPS downgrade redirect blocked.")
    return result


def check_robots(url: str, settings: Settings, deadline: float):
    parsed = urlsplit(url)
    robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    current = robots_url
    for _ in range(MAX_REDIRECTS + 1):
        result = request_once(current, settings, deadline, ROBOTS_BYTES)
        if result.status in (301, 302, 303, 307, 308):
            current = redirect_target(current, result)
            continue
        if result.status in (404, 410):
            return
        if result.status != 200:
            raise FetchError("blocked", f"robots.txt returned HTTP {result.status}; RevRank stopped because site rules could not be checked.")
        content_type = result.headers.get("content-type", "").lower()
        text = result.body.decode("utf-8", errors="replace")
        if "html" in content_type or re.search(r"<(?:html|!doctype)", text, re.I):
            raise FetchError("blocked", "robots.txt returned an HTML page; collection is blocked conservatively.")
        parser = RobotFileParser(robots_url)
        parser.parse(text.splitlines())
        if not parser.can_fetch(USER_AGENT, url):
            raise FetchError("blocked", "robots.txt disallows this listing path; paste listing text instead.")
        delay = parser.crawl_delay(USER_AGENT)
        rate = parser.request_rate(USER_AGENT)
        # Never silently ignore a crawl schedule this on-demand fetcher cannot enforce.
        if (delay and delay > 0) or rate:
            raise FetchError("blocked", "robots.txt specifies a crawl schedule; this importer has no scheduled crawler.")
        return
    raise FetchError("blocked", "robots.txt exceeded the redirect limit.")


def fetch_listing(url: str, settings: Settings) -> Page:
    from .listing_url import is_listing_url, same_listing
    url, host, _ = validated_url(url)
    requested = url
    source = source_for(host, settings)
    if source["status"] != "allowed":
        raise FetchError("restricted" if source["status"] == "restricted" else "unsupported", source["reason"])
    if not settings.live_fetch_enabled:
        raise FetchError("unsupported", "Live fetching is disabled by local configuration. Paste listing text or use manual entry.")
    deadline = time.monotonic() + TOTAL_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        check_robots(url, settings, deadline)
        result = request_once(url, settings, deadline, MAX_BYTES)
        if result.status in (301, 302, 303, 307, 308):
            url = redirect_target(url, result)
            # Expired listings redirect to search results; that page's cars are not this vehicle.
            if is_listing_url(requested) and not same_listing(url, requested):
                raise FetchError("failed", "The listing redirected to a different page (usually a search page), so it appears to be "
                                           "sold or removed. This does not confirm a sale.")
            continue
        if result.status in (401, 403, 429):
            raise FetchError("blocked", f"The website returned HTTP {result.status} (access denied or rate limited). RevRank did attempt this URL; paste listing text to continue.")
        if result.status in (404, 410):
            raise FetchError("failed", "Listing is unavailable or removed. This does not indicate a confirmed sale.")
        if result.status != 200:
            raise FetchError("failed", "Source returned an unsuccessful response.")
        content_type = result.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in ("text/html", "application/xhtml+xml", "text/plain", "application/ld+json"):
            raise FetchError("unsupported", "Only HTML, plain text and JSON-LD listings are supported.")
        text = result.body.decode("utf-8", errors="replace")
        if ACCESS_CHALLENGE.search(text[:20000]):
            raise FetchError("blocked", "Source returned an access challenge; no bypass attempted. Paste listing text.")
        return Page(text=text, url=url)
    raise FetchError("blocked", "Listing exceeded the redirect limit.")
