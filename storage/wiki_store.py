"""Lecture/écriture des pages de wiki en local au format markdown avec métadonnées."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FRONTMATTER_DELIM = "---"


@dataclass
class WikiPage:
    title: str
    slug: str
    scope_type: str  # "project" ou "group"
    scope_id: int
    content: str
    format: str
    synced_at: str
    path: Path | None = None


def _scope_dir(data_dir: Path, scope_type: str, scope_id: int) -> Path:
    return data_dir / f"{scope_type}_{scope_id}"


def _slug_to_filename(slug: str) -> str:
    """Les slugs GitLab peuvent contenir des '/' (pages imbriquées) -> on les remplace."""
    return slug.replace("/", "__") + ".md"


def _serialize_frontmatter(meta: dict[str, Any]) -> str:
    lines = [_FRONTMATTER_DELIM]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.append(_FRONTMATTER_DELIM)
    return "\n".join(lines) + "\n"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith(_FRONTMATTER_DELIM):
        return {}, text

    parts = text.split(_FRONTMATTER_DELIM, 2)
    if len(parts) < 3:
        return {}, text

    _, raw_meta, body = parts
    meta: dict[str, str] = {}
    for line in raw_meta.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    return meta, body.lstrip("\n")


class WikiStore:
    """Gère la persistance des pages de wiki sur disque."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def reset_scope(self, scope_type: str, scope_id: int) -> None:
        """Supprime toutes les pages déjà synchronisées pour ce scope (avant une re-sync complète)."""
        scope_dir = _scope_dir(self.data_dir, scope_type, scope_id)
        if scope_dir.exists():
            shutil.rmtree(scope_dir)

    def save_page(
        self,
        scope_type: str,
        scope_id: int,
        slug: str,
        title: str,
        content: str,
        page_format: str = "markdown",
    ) -> Path:
        scope_dir = _scope_dir(self.data_dir, scope_type, scope_id)
        scope_dir.mkdir(parents=True, exist_ok=True)

        synced_at = datetime.now(timezone.utc).isoformat()
        meta = {
            "title": title,
            "slug": slug,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "format": page_format,
            "synced_at": synced_at,
        }

        file_path = scope_dir / _slug_to_filename(slug)
        file_path.write_text(_serialize_frontmatter(meta) + "\n" + content, encoding="utf-8")
        return file_path

    def load_all_pages(self) -> list[WikiPage]:
        """Charge toutes les pages stockées localement, triées par date de synchro (plus récentes d'abord)."""
        pages: list[WikiPage] = []

        if not self.data_dir.exists():
            return pages

        for scope_dir in sorted(self.data_dir.iterdir()):
            if not scope_dir.is_dir():
                continue
            for md_file in sorted(scope_dir.glob("*.md")):
                try:
                    text = md_file.read_text(encoding="utf-8")
                except OSError as exc:
                    logger.warning("Impossible de lire %s: %s", md_file, exc)
                    continue

                meta, body = _parse_frontmatter(text)
                pages.append(
                    WikiPage(
                        title=meta.get("title", md_file.stem),
                        slug=meta.get("slug", md_file.stem),
                        scope_type=meta.get("scope_type", "project"),
                        scope_id=int(meta.get("scope_id", 0) or 0),
                        content=body,
                        format=meta.get("format", "markdown"),
                        synced_at=meta.get("synced_at", ""),
                        path=md_file,
                    )
                )

        pages.sort(key=lambda p: p.synced_at, reverse=True)
        return pages

    def count_pages(self) -> int:
        if not self.data_dir.exists():
            return 0
        return sum(1 for scope_dir in self.data_dir.iterdir() if scope_dir.is_dir() for _ in scope_dir.glob("*.md"))
