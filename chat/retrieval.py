"""Lexical retrieval (RAG) over the indexed wiki pages.

Instead of stuffing every page into the prompt, the wikis are split into chunks
and ranked against the user's question with BM25; only the top chunks (within the
token budget, and within the scopes the user may access) are sent to the model.

Pure-Python and in-memory: the index is rebuilt from the `WikiStore` after each
sync. The `Retriever` is intentionally the only retrieval seam, so a semantic
backend could replace/augment it later without touching the endpoints.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional

from chat.context import CHARS_PER_TOKEN
from storage.wiki_store import WikiPage

logger = logging.getLogger(__name__)

# Chunking: ~1600 chars ≈ 400 tokens per chunk, with a one-paragraph overlap so a
# fact split across a boundary still appears whole in at least one chunk.
CHUNK_TARGET_CHARS = 1600
CHUNK_OVERLAP_PARAGRAPHS = 1
# Cap on chunks considered/returned, as a safety bound on very large corpora.
DEFAULT_MAX_CHUNKS = 40

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_PARAGRAPH_RE = re.compile(r"\n\s*\n")

_CONTEXT_HEADER = (
    "Here is the content of the indexed GitLab wikis relevant to the question. "
    "Each section is an excerpt from a wiki page.\n\n"
)
_EMPTY_CONTEXT = "No wiki content is currently indexed."


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens (Unicode-aware, so accented text works too)."""
    return _TOKEN_RE.findall(text.lower())


def _hard_wrap(text: str, target_chars: int) -> list[str]:
    """Splits an oversized paragraph into <=target_chars pieces on word bounds."""
    words = text.split()
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if current and length + len(word) + 1 > target_chars:
            pieces.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += len(word) + 1
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_text(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Splits page text into overlapping chunks, respecting paragraph bounds."""
    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= target_chars:
            units.append(paragraph)
        else:
            units.extend(_hard_wrap(paragraph, target_chars))

    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for unit in units:
        if current and length + len(unit) > target_chars:
            chunks.append("\n\n".join(current))
            current = current[-CHUNK_OVERLAP_PARAGRAPHS:] if CHUNK_OVERLAP_PARAGRAPHS else []
            length = sum(len(u) for u in current)
        current.append(unit)
        length += len(unit)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


@dataclass
class Chunk:
    scope_type: str
    scope_id: int
    title: str
    slug: str
    text: str

    @property
    def scope_key(self) -> str:
        return f"{self.scope_type}_{self.scope_id}"

    def as_section(self) -> str:
        return (
            f"### {self.title} (scope: {self.scope_type} {self.scope_id}, slug: {self.slug})\n\n"
            f"{self.text.strip()}\n"
        )


@dataclass
class RetrievalResult:
    text: str
    chunks_used: int
    sources: list[dict] = field(default_factory=list)


class _BM25Index:
    """Minimal in-memory BM25 index over a fixed list of chunks."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self._doc_len: list[int] = []
        self._freqs: list[dict[str, int]] = []
        self._postings: dict[str, list[int]] = {}
        self._idf: dict[str, float] = {}

        doc_freq: dict[str, int] = {}
        for doc_index, chunk in enumerate(chunks):
            counts: dict[str, int] = {}
            for token in tokenize(chunk.text):
                counts[token] = counts.get(token, 0) + 1
            self._freqs.append(counts)
            self._doc_len.append(sum(counts.values()))
            for token in counts:
                doc_freq[token] = doc_freq.get(token, 0) + 1
                self._postings.setdefault(token, []).append(doc_index)

        total = len(chunks)
        self._avgdl = (sum(self._doc_len) / total) if total else 0.0
        for token, n in doc_freq.items():
            # BM25+ idf: always positive, avoids negative scores for common terms.
            self._idf[token] = math.log(1 + (total - n + 0.5) / (n + 0.5))

    def _score(self, doc_index: int, query_tokens: list[str]) -> float:
        freqs = self._freqs[doc_index]
        dl = self._doc_len[doc_index]
        denom_norm = self.k1 * (1 - self.b + self.b * dl / self._avgdl) if self._avgdl else self.k1
        score = 0.0
        for token in query_tokens:
            tf = freqs.get(token, 0)
            if tf == 0:
                continue
            score += self._idf.get(token, 0.0) * (tf * (self.k1 + 1)) / (tf + denom_norm)
        return score

    def search(
        self, query_tokens: list[str], allowed_scope_keys: Optional[set], limit: int
    ) -> list[Chunk]:
        """Top chunks for the query, filtered to allowed scopes (None = all)."""

        def allowed(chunk: Chunk) -> bool:
            return allowed_scope_keys is None or chunk.scope_key in allowed_scope_keys

        total = len(self.chunks)
        unique = set(query_tokens)
        # Gather candidates from "selective" terms only (present, and not in more
        # than half the corpus) so near-ubiquitous words don't pull in unrelated
        # chunks. Fall back to all terms if the query is entirely non-selective.
        selective = [t for t in unique if 0 < len(self._postings.get(t, ())) < 0.5 * total]
        candidate_terms = selective or unique

        candidates: set[int] = set()
        for token in candidate_terms:
            candidates.update(self._postings.get(token, ()))

        # Scoring still uses the full query (a matched common term adds a little).
        scored = [
            (self._score(i, query_tokens), i) for i in candidates if allowed(self.chunks[i])
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.chunks[i] for _, i in scored[:limit]]

    def recency_fallback(self, allowed_scope_keys: Optional[set], limit: int) -> list[Chunk]:
        """When nothing matches lexically, return the most recent allowed chunks.

        `chunks` are built in the store's recency order (newest page first).
        """
        result: list[Chunk] = []
        for chunk in self.chunks:
            if allowed_scope_keys is None or chunk.scope_key in allowed_scope_keys:
                result.append(chunk)
                if len(result) >= limit:
                    break
        return result


class Retriever:
    """Builds a BM25 index from wiki pages and retrieves context per question."""

    def __init__(self) -> None:
        self._index = _BM25Index([])

    def rebuild(self, pages: list[WikiPage]) -> None:
        chunks: list[Chunk] = []
        for page in pages:
            for text in chunk_text(page.content):
                chunks.append(Chunk(page.scope_type, page.scope_id, page.title, page.slug, text))
        self._index = _BM25Index(chunks)
        logger.info("Retrieval index rebuilt: %d chunk(s) from %d page(s).", len(chunks), len(pages))

    @property
    def chunk_count(self) -> int:
        return len(self._index.chunks)

    def retrieve(
        self,
        query: str,
        allowed_scope_keys: Optional[set],
        max_tokens: int,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
    ) -> RetrievalResult:
        index = self._index
        if not index.chunks:
            return RetrievalResult(text=_EMPTY_CONTEXT, chunks_used=0)

        ranked = index.search(tokenize(query), allowed_scope_keys, max_chunks)
        if not ranked:
            # No lexical match: fall back to recent content so the model still has
            # grounding material rather than nothing.
            ranked = index.recency_fallback(allowed_scope_keys, max_chunks)

        max_chars = max_tokens * CHARS_PER_TOKEN
        sections: list[str] = []
        used: list[Chunk] = []
        total = 0
        for chunk in ranked:
            section = chunk.as_section()
            if sections and total + len(section) > max_chars:
                break
            sections.append(section)
            used.append(chunk)
            total += len(section)

        if not sections:
            return RetrievalResult(text=_EMPTY_CONTEXT, chunks_used=0)

        # De-duplicated list of source pages, in first-appearance order.
        sources: list[dict] = []
        seen: set[tuple] = set()
        for chunk in used:
            key = (chunk.scope_key, chunk.slug)
            if key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "title": chunk.title,
                        "slug": chunk.slug,
                        "scope_type": chunk.scope_type,
                        "scope_id": chunk.scope_id,
                    }
                )

        text = _CONTEXT_HEADER + "\n---\n\n".join(sections)
        return RetrievalResult(text=text, chunks_used=len(used), sources=sources)
