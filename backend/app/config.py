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
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    data_dir: Path = ROOT / ".local"
    marketcheck_api_key: str = ""
    search_provider: str = "brave"
    search_api_key: str = ""
    vin_decode_enabled: bool = False

    @property
    def marketcheck_enabled(self) -> bool:
        return bool(self.marketcheck_api_key)

    @property
    def search_enabled(self) -> bool:
        return bool(self.search_api_key) and self.search_provider in ('brave', 'tavily')

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

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
            llm_base_url=os.getenv("REVRANK_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_model=os.getenv("REVRANK_LLM_MODEL", "").strip(),
            data_dir=directory if directory.is_absolute() else ROOT / directory,
            marketcheck_api_key=os.getenv("REVRANK_MARKETCHECK_API_KEY", "").strip(),
            search_provider=os.getenv("REVRANK_SEARCH_PROVIDER", "brave").strip().lower(),
            search_api_key=os.getenv("REVRANK_SEARCH_API_KEY", "").strip(),
            vin_decode_enabled=os.getenv("REVRANK_VIN_DECODE_ENABLED", "false").lower() == "true",
        )
