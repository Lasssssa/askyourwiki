"""Construction du contexte système à partir des pages de wiki stockées localement."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from storage.wiki_store import WikiPage, WikiStore

logger = logging.getLogger(__name__)

# Estimation simple: ~4 caractères par token (heuristique courante pour FR/EN).
CHARS_PER_TOKEN = 4


@dataclass
class WikiContext:
    text: str
    pages_included: int
    pages_total: int
    truncated: bool


def _format_page(page: WikiPage) -> str:
    scope_label = f"{page.scope_type} {page.scope_id}"
    return (
        f"### {page.title} (scope: {scope_label}, slug: {page.slug})\n\n"
        f"{page.content.strip()}\n"
    )


def build_context(store: WikiStore, max_tokens: int) -> WikiContext:
    """Construit le contexte système à partir de toutes les pages de wiki disponibles.

    Les pages sont déjà triées par date de synchronisation (plus récentes en premier).
    Si le contexte dépasse `max_tokens`, on tronque en conservant en priorité les
    pages les plus récentes et en arrêtant dès que le budget est atteint.
    """
    pages = store.load_all_pages()
    max_chars = max_tokens * CHARS_PER_TOKEN

    if not pages:
        return WikiContext(
            text="Aucune page de wiki n'est actuellement indexée.",
            pages_included=0,
            pages_total=0,
            truncated=False,
        )

    sections: list[str] = []
    total_chars = 0
    truncated = False

    for page in pages:
        section = _format_page(page)
        if total_chars + len(section) > max_chars:
            truncated = True
            break
        sections.append(section)
        total_chars += len(section)

    if not sections:
        # La page la plus récente seule dépasse déjà le budget: on la tronque.
        first = _format_page(pages[0])
        sections = [first[:max_chars]]
        truncated = True

    text = (
        "Voici le contenu des wikis GitLab indexés. Chaque section correspond à une page de wiki.\n\n"
        + "\n---\n\n".join(sections)
    )

    if truncated:
        logger.info(
            "Contexte tronqué: %d/%d page(s) incluse(s) (~%d tokens).",
            len(sections),
            len(pages),
            total_chars // CHARS_PER_TOKEN,
        )

    return WikiContext(
        text=text,
        pages_included=len(sections),
        pages_total=len(pages),
        truncated=truncated,
    )
