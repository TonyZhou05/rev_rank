"""Server-only configuration. Relative data paths resolve against the project root."""
from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    live_fetch_enabled: bool = False
    allowed_domains: tuple[str, ...] = ()
    llm_api_key: str = ""
    # DeepSeek is the configured OpenAI-compatible provider; any compatible endpoint works.
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = ""
    data_dir: Path = ROOT / ".local"
    marketcheck_api_key: str = ""
    search_provider: str = "brave"
    search_api_key: str = ""
    vin_decode_enabled: bool = False
    # One extra MarketCheck call per known VIN, for the factory MSRP a listing cannot supply.
    neovin_enabled: bool = True
    # One extra MarketCheck call, spent only when active inventory held nothing, against the
    # past-inventory endpoint. It runs on an import that would otherwise recover nothing at all.
    marketcheck_past_enabled: bool = True
    # Search-derived dealer flags. Off by default: each report spends search credits on the seller
    # rather than the car, so an operator opts in deliberately.
    dealer_signals_enabled: bool = False
    # Searches per distinct dealer, per report. Tavily advanced search costs 2 credits each.
    dealer_signal_searches: int = 2
    # Paid-provider budgets per UTC month, enforced by usage.py before each call.
    marketcheck_monthly_calls: int = 500
    search_monthly_credits: int = 1000
    # Hard wall for one POST /api/compare, just under the page's own 90s limit so the server
    # answers with an honest deterministic report before the browser gives up.
    compare_timeout_seconds: float = 85.0
    # After Direct is blocked or thin: a private headless session of the buyer-supplied VDP.
    # Off by default until Tongli opts in (primary browse raises ToS hit rate).
    # This is not counsel clearance. Docker/Render must not set the flag on.
    browser_recovery_enabled: bool = False
    # Cap for one Playwright session. The import token is the outer wall.
    browser_timeout_seconds: float = 20.0
    # Hard wall for one POST /api/import, including Direct plus recovery (licensed/browse/search).
    import_timeout_seconds: float = 55.0

    @property
    def marketcheck_enabled(self) -> bool:
        return bool(self.marketcheck_api_key)

    @property
    def neovin_msrp_enabled(self) -> bool:
        return self.marketcheck_enabled and self.neovin_enabled

    @property
    def past_inventory_enabled(self) -> bool:
        return self.marketcheck_enabled and self.marketcheck_past_enabled

    @property
    def search_enabled(self) -> bool:
        return bool(self.search_api_key) and self.search_provider in ('brave', 'tavily')

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @property
    def dealer_signals_available(self) -> bool:
        """Dealer signals need a search provider; the model only interprets what search returned."""
        return self.dealer_signals_enabled and self.search_enabled

    @property
    def llm_endpoint_host(self) -> str:
        """Hostname of the configured model endpoint. Never the key, which travels in a header."""
        from urllib.parse import urlsplit
        return urlsplit(self.llm_base_url).hostname or ""

    @classmethod
    def from_env(cls) -> "Settings":
        directory = Path(os.getenv("REVRANK_DATA_DIR", ".local")).expanduser()
        domains = tuple(dict.fromkeys(
            d.strip().lower().rstrip(".").encode("idna").decode("ascii")
            for d in os.getenv("REVRANK_ALLOWED_DOMAINS", "").split(",") if d.strip()
        ))
        # Exact hosts, never wildcard/subdomain permissions or URL strings.
        if any(not d or any(c in d for c in "/:@*?#") for d in domains):
            raise ValueError("REVRANK_ALLOWED_DOMAINS must contain exact DNS hostnames")
        return cls(
            live_fetch_enabled=os.getenv("REVRANK_LIVE_FETCH_ENABLED", "false").lower() == "true",
            allowed_domains=domains,
            llm_api_key=os.getenv("REVRANK_LLM_API_KEY", "").strip(),
            llm_base_url=(os.getenv("REVRANK_LLM_BASE_URL", "").strip() or "https://api.deepseek.com/v1").rstrip("/"),
            llm_model=os.getenv("REVRANK_LLM_MODEL", "").strip(),
            data_dir=directory if directory.is_absolute() else ROOT / directory,
            marketcheck_api_key=os.getenv("REVRANK_MARKETCHECK_API_KEY", "").strip(),
            search_provider=os.getenv("REVRANK_SEARCH_PROVIDER", "brave").strip().lower(),
            search_api_key=os.getenv("REVRANK_SEARCH_API_KEY", "").strip(),
            vin_decode_enabled=os.getenv("REVRANK_VIN_DECODE_ENABLED", "false").lower() == "true",
            neovin_enabled=os.getenv("REVRANK_NEOVIN_ENABLED", "true").lower() != "false",
            marketcheck_past_enabled=os.getenv("REVRANK_MARKETCHECK_PAST_INVENTORY_ENABLED", "true").lower() != "false",
            dealer_signals_enabled=os.getenv("REVRANK_DEALER_SIGNALS_ENABLED", "false").lower() == "true",
            dealer_signal_searches=max(1, min(3, int(os.getenv("REVRANK_DEALER_SIGNAL_SEARCHES", "2")))),
            marketcheck_monthly_calls=int(os.getenv("REVRANK_MARKETCHECK_MONTHLY_CALLS", "500")),
            search_monthly_credits=int(os.getenv("REVRANK_SEARCH_MONTHLY_CREDITS", "1000")),
            compare_timeout_seconds=max(1.0, float(os.getenv("REVRANK_COMPARE_TIMEOUT_SECONDS", "85"))),
            browser_recovery_enabled=os.getenv("REVRANK_BROWSER_RECOVERY_ENABLED", "false").lower() == "true",
            browser_timeout_seconds=max(5.0, min(45.0, float(os.getenv("REVRANK_BROWSER_TIMEOUT_SECONDS", "20")))),
            import_timeout_seconds=max(15.0, float(os.getenv("REVRANK_IMPORT_TIMEOUT_SECONDS", "55"))),
        )
