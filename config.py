"""Load and validate configuration from environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _parse_id_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid ID ignored in configuration: %r", part)
    return ids


class Config:
    GITLAB_URL: str = os.getenv("GITLAB_URL", "").rstrip("/")
    GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "")
    GITLAB_PROJECT_IDS: list[int] = _parse_id_list(os.getenv("GITLAB_PROJECT_IDS"))
    GITLAB_GROUP_IDS: list[int] = _parse_id_list(os.getenv("GITLAB_GROUP_IDS"))

    # "vllm" (default, OpenAI-compatible self-hosted model) or "anthropic" (hosted API)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "vllm").strip().lower()

    # Configuration for a vLLM server (or any other server exposing an OpenAI-compatible API)
    VLLM_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    VLLM_MODEL: str = os.getenv("VLLM_MODEL", "")
    VLLM_API_KEY: str = os.getenv("VLLM_API_KEY", "EMPTY")

    # Configuration for the hosted Anthropic API (optional)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "")

    SYNC_INTERVAL_MINUTES: int = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))

    # Title displayed in the web UI header
    APP_TITLE: str = os.getenv("APP_TITLE", "GitLab Wiki Assistant")

    # Optional shared username/password login (disabled unless both are set)
    AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "")
    AUTH_PASSWORD: str = os.getenv("AUTH_PASSWORD", "")

    # Optional "Sign in with GitLab" (OAuth2) against the GITLAB_URL instance.
    # Requires an OAuth application registered in GitLab with the "read_user" scope.
    GITLAB_OAUTH_CLIENT_ID: str = os.getenv("GITLAB_OAUTH_CLIENT_ID", "")
    GITLAB_OAUTH_CLIENT_SECRET: str = os.getenv("GITLAB_OAUTH_CLIENT_SECRET", "")
    # Callback URL registered with the OAuth application. If empty, it is derived
    # from the incoming request (<base-url>/auth/gitlab/callback).
    GITLAB_OAUTH_REDIRECT_URI: str = os.getenv("GITLAB_OAUTH_REDIRECT_URI", "")

    # Secret used to sign session cookies. If empty, a secret is derived from the
    # auth credentials (stable across restarts) or generated at startup.
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")

    @property
    def password_auth_enabled(self) -> bool:
        return bool(self.AUTH_USERNAME and self.AUTH_PASSWORD)

    @property
    def gitlab_auth_enabled(self) -> bool:
        return bool(self.GITLAB_URL and self.GITLAB_OAUTH_CLIENT_ID and self.GITLAB_OAUTH_CLIENT_SECRET)

    @property
    def auth_enabled(self) -> bool:
        return self.password_auth_enabled or self.gitlab_auth_enabled

    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data" / "wikis"
    FRONTEND_DIST: Path = BASE_DIR / "frontend" / "dist"

    MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "150000"))
    MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "5"))

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of warning messages for missing configuration."""
        warnings = []
        if not cls.GITLAB_URL:
            warnings.append("GITLAB_URL is not configured.")
        if not cls.GITLAB_TOKEN:
            warnings.append("GITLAB_TOKEN is not configured.")
        if not cls.GITLAB_PROJECT_IDS and not cls.GITLAB_GROUP_IDS:
            warnings.append("No GITLAB_PROJECT_IDS or GITLAB_GROUP_IDS configured.")
        if cls.LLM_PROVIDER == "vllm":
            if not cls.VLLM_BASE_URL:
                warnings.append("VLLM_BASE_URL is not configured.")
            if not cls.VLLM_MODEL:
                warnings.append("VLLM_MODEL is not configured.")
        elif cls.LLM_PROVIDER == "anthropic":
            if not cls.ANTHROPIC_API_KEY:
                warnings.append("ANTHROPIC_API_KEY is not configured.")
            if not cls.ANTHROPIC_MODEL:
                warnings.append("ANTHROPIC_MODEL is not configured.")
        else:
            warnings.append(f"Unknown LLM_PROVIDER={cls.LLM_PROVIDER!r} (valid values: 'vllm', 'anthropic').")
        if bool(cls.AUTH_USERNAME) != bool(cls.AUTH_PASSWORD):
            warnings.append("AUTH_USERNAME and AUTH_PASSWORD must be set together: password sign-in is disabled.")
        if bool(cls.GITLAB_OAUTH_CLIENT_ID) != bool(cls.GITLAB_OAUTH_CLIENT_SECRET):
            warnings.append(
                "GITLAB_OAUTH_CLIENT_ID and GITLAB_OAUTH_CLIENT_SECRET must be set together: "
                "GitLab sign-in is disabled."
            )
        elif cls.GITLAB_OAUTH_CLIENT_ID and not cls.GITLAB_URL:
            warnings.append("GITLAB_OAUTH_* is configured but GITLAB_URL is not: GitLab sign-in is disabled.")
        return warnings


config = Config()
