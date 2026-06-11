"""Chargement et validation de la configuration depuis les variables d'environnement."""

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
            logging.getLogger(__name__).warning("ID invalide ignoré dans la configuration: %r", part)
    return ids


class Config:
    GITLAB_URL: str = os.getenv("GITLAB_URL", "").rstrip("/")
    GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "")
    GITLAB_PROJECT_IDS: list[int] = _parse_id_list(os.getenv("GITLAB_PROJECT_IDS"))
    GITLAB_GROUP_IDS: list[int] = _parse_id_list(os.getenv("GITLAB_GROUP_IDS"))

    # "vllm" (par défaut, modèle auto-hébergé compatible OpenAI) ou "anthropic" (API hébergée)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "vllm").strip().lower()

    # Configuration pour un serveur vLLM (ou tout autre serveur exposant une API compatible OpenAI)
    VLLM_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    VLLM_MODEL: str = os.getenv("VLLM_MODEL", "")
    VLLM_API_KEY: str = os.getenv("VLLM_API_KEY", "EMPTY")

    # Configuration pour l'API hébergée Anthropic (optionnel)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "")

    SYNC_INTERVAL_MINUTES: int = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))

    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data" / "wikis"

    MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "150000"))
    MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "5"))

    @classmethod
    def validate(cls) -> list[str]:
        """Retourne une liste de messages d'avertissement pour la configuration manquante."""
        warnings = []
        if not cls.GITLAB_URL:
            warnings.append("GITLAB_URL n'est pas configuré.")
        if not cls.GITLAB_TOKEN:
            warnings.append("GITLAB_TOKEN n'est pas configuré.")
        if not cls.GITLAB_PROJECT_IDS and not cls.GITLAB_GROUP_IDS:
            warnings.append("Aucun GITLAB_PROJECT_IDS ni GITLAB_GROUP_IDS configuré.")
        if cls.LLM_PROVIDER == "vllm":
            if not cls.VLLM_BASE_URL:
                warnings.append("VLLM_BASE_URL n'est pas configuré.")
            if not cls.VLLM_MODEL:
                warnings.append("VLLM_MODEL n'est pas configuré.")
        elif cls.LLM_PROVIDER == "anthropic":
            if not cls.ANTHROPIC_API_KEY:
                warnings.append("ANTHROPIC_API_KEY n'est pas configuré.")
            if not cls.ANTHROPIC_MODEL:
                warnings.append("ANTHROPIC_MODEL n'est pas configuré.")
        else:
            warnings.append(f"LLM_PROVIDER={cls.LLM_PROVIDER!r} inconnu (valeurs valides: 'vllm', 'anthropic').")
        return warnings


config = Config()
