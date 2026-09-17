from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./crawler.db"

    # Redis (optional, in-memory queue fallback if not reachable)
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"

    # Crawler Identity
    CRAWLER_USER_AGENT: str = "ContactDiscoveryBot/1.0 (+https://example.com/bot)"

    # Default Crawl Limits
    DEFAULT_REQUESTS_PER_SECOND: float = 2.0
    DEFAULT_CONCURRENCY: int = 5
    DEFAULT_MAX_PAGES: int = 500
    DEFAULT_MAX_DEPTH: int = 5
    DEFAULT_TIMEOUT: float = 20.0

    # Hard Safety Limits
    MAX_RESPONSE_SIZE_MB: int = 10
    MAX_REDIRECTS: int = 5
    MAX_QUEUE_SIZE: int = 5000
    MAX_RUNTIME_SECONDS: int = 3600
    MAX_LINKS_PER_PAGE: int = 200

    # Security
    ALLOW_PRIVATE_IPS: bool = False

    # Browser Rendering (Playwright)
    ENABLE_BROWSER_RENDERING: bool = False

    # Observability
    LOG_LEVEL: str = "INFO"

    @property
    def max_response_size_bytes(self) -> int:
        return self.MAX_RESPONSE_SIZE_MB * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    return Settings()
