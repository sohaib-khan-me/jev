"""Application configuration, loaded from environment variables and backend/.env.

Secrets are stored as SecretStr so they never appear in repr() output or logs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MySQL (read-only source database) ---
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "jev_reader"
    mysql_password: SecretStr = SecretStr("")
    mysql_database: str = "fast_jev_test"
    mysql_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    mysql_read_timeout_seconds: int = Field(default=15, ge=1, le=300)

    # --- JEV provider: where the {model, state, questions} request is sent ---
    jev_provider: Literal["cloudflare", "openrouter"] = "cloudflare"

    # Cloudflare Workers AI
    cloudflare_account_id: str = ""
    cloudflare_api_token: SecretStr = SecretStr("")
    cloudflare_api_base_url: str = "https://api.cloudflare.com/client/v4"
    jev_model: str = "typesafe/jev"

    # OpenRouter Decisions API (alpha)
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api"
    openrouter_jev_model: str = "~typesafe/jev-latest"

    jev_mock_mode: bool = False
    jev_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    jev_max_retries: int = Field(default=2, ge=0, le=2)
    jev_low_confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    # Experiment knob: include distinct example values of categorical columns in
    # the context sent to JEV. Off by default so the experiment is schema-only.
    jev_include_sample_values: bool = False

    # --- Candidate generation ---
    candidate_max_fields: int = Field(default=25, ge=2, le=200)
    value_scan_max_distinct: int = Field(default=100, ge=1, le=10_000)
    value_scan_max_rows: int = Field(default=100_000, ge=1)

    # --- App ---
    frontend_url: str = "http://localhost:5173"
    history_db_path: Path = BACKEND_DIR / "data" / "history.sqlite3"
    test_cases_path: Path = PROJECT_ROOT / "evaluation" / "test_cases.json"
    log_level: str = "INFO"
    # Campaign text is synthetic here; set to false to keep it out of logs later.
    log_campaign_text: bool = True
    # Only for local debugging: include exception details in 500 responses.
    debug_errors: bool = False

    @property
    def jev_configured(self) -> bool:
        if self.jev_provider == "openrouter":
            return bool(self.openrouter_api_key.get_secret_value())
        return bool(self.cloudflare_account_id and self.cloudflare_api_token.get_secret_value())

    @property
    def jev_endpoint(self) -> str:
        if self.jev_provider == "openrouter":
            return f"{self.openrouter_base_url}/alpha/decisions"
        return f"{self.cloudflare_api_base_url}/accounts/{self.cloudflare_account_id}/ai/run"

    @property
    def jev_request_model(self) -> str:
        return self.openrouter_jev_model if self.jev_provider == "openrouter" else self.jev_model

    @property
    def jev_api_token(self) -> SecretStr:
        return self.openrouter_api_key if self.jev_provider == "openrouter" else self.cloudflare_api_token

    @property
    def jev_credential_hint(self) -> str:
        if self.jev_provider == "openrouter":
            return "Set OPENROUTER_API_KEY in backend/.env."
        return "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in backend/.env."

    @property
    def mysql_url(self) -> URL:
        # URL.create escapes special characters in the password correctly.
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
