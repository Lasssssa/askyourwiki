"""Building the system context from locally stored wiki pages."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from storage.wiki_store import WikiPage, WikiStore

logger = logging.getLogger(__name__)

# Simple estimate: ~4 characters per token (common heuristic for FR/EN).
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
    """Builds the system context from all available wiki pages.

    Pages are already sorted by sync date (most recent first). If the
    context exceeds `max_tokens`, it is truncated, prioritizing the most
    recent pages and stopping as soon as the budget is reached.
    """
    pages = store.load_all_pages()
    max_chars = max_tokens * CHARS_PER_TOKEN

    if not pages:
        return WikiContext(
            text="No wiki pages are currently indexed.",
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
        # The most recent page alone already exceeds the budget: truncate it.
        first = _format_page(pages[0])
        sections = [first[:max_chars]]
        truncated = True

    text = (
        "Here is the content of the indexed GitLab wikis. Each section corresponds to a wiki page.\n\n"
        + "\n---\n\n".join(sections)
    )

    if truncated:
        logger.info(
            "Context truncated: %d/%d page(s) included (~%d tokens).",
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
