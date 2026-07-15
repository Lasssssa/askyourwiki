"""Resolve which indexed wiki scopes a signed-in GitLab user may read.

Access is decided with the application's own token (the one used for syncing):
for each configured project/group, a public/internal scope is readable by any
signed-in GitLab user, while a private scope requires the user to be a (direct or
inherited) member. Results are cached briefly per user so this doesn't hit GitLab
on every chat message.

This is a security boundary: on GitLab errors the resolver fails *closed* (denies
the scope) rather than leaking wikis the user may not be allowed to see.
"""

from __future__ import annotations

import asyncio
import logging
import time

from config import Config
from gitlab.client import GitLabAPIError, GitLabClient

logger = logging.getLogger(__name__)

# Sentinel distinguishing "no cache entry" from a cached falsy/empty value.
_MISS = object()


def scope_key(scope_type: str, scope_id: int) -> str:
    """The stable key for a scope, matching WikiStore's directory names."""
    return f"{scope_type}_{scope_id}"


class _TTLCache:
    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._entries: dict[str, tuple[object, float]] = {}

    def get(self, key: str) -> object:
        entry = self._entries.get(key)
        if entry is None:
            return _MISS
        value, expires_at = entry
        if expires_at < time.monotonic():
            self._entries.pop(key, None)
            return _MISS
        return value

    def set(self, key: str, value: object) -> None:
        self._entries[key] = (value, time.monotonic() + self._ttl)


class AccessResolver:
    """Computes the set of scope keys a user is allowed to read."""

    def __init__(self, config: Config, cache_ttl: float = 300.0) -> None:
        self._config = config
        self._cache = _TTLCache(cache_ttl)
        # Scope visibility is user-independent, so it's cached across users.
        self._visibility_cache = _TTLCache(cache_ttl)

    async def accessible_scope_keys(self, username: str, scopes: list[tuple[str, int]]) -> set[str]:
        """The scope keys, among `scopes`, that `username` is allowed to read.

        `scopes` are the (scope_type, scope_id) pairs actually indexed locally
        (from ``WikiStore.list_scopes()``), so auto-discovered projects are
        access-controlled just like configured ones.
        """
        if not scopes:
            return set()

        cached = self._cache.get(username)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]

        try:
            allowed = await self._compute(username, scopes)
        except GitLabAPIError as exc:
            # A total failure (e.g. GitLab unreachable): deny, but don't cache it
            # so the next request retries once GitLab is back.
            logger.warning("Access resolution failed for %r: %s; denying (not cached).", username, exc)
            return set()

        self._cache.set(username, allowed)
        return allowed

    async def _compute(self, username: str, scopes: list[tuple[str, int]]) -> set[str]:
        async with GitLabClient(self._config.GITLAB_URL, self._config.GITLAB_TOKEN) as client:
            user_id = await client.get_user_id(username)
            if user_id is None:
                logger.warning("Access: no GitLab user found for %r; denying all scopes.", username)
                return set()

            # Check every scope concurrently; a per-scope error fails closed.
            results = await asyncio.gather(
                *(self._can_read(client, st, sid, user_id) for st, sid in scopes),
                return_exceptions=True,
            )

        allowed: set[str] = set()
        for (scope_type, scope_id), result in zip(scopes, results):
            if result is True:
                allowed.add(scope_key(scope_type, scope_id))
            elif isinstance(result, Exception):
                logger.warning(
                    "Access check failed for %s %s (user %r): %s; denying this scope.",
                    scope_type,
                    scope_id,
                    username,
                    result,
                )
        return allowed

    async def _can_read(
        self, client: GitLabClient, scope_type: str, scope_id: int, user_id: int
    ) -> bool:
        api_scope = "projects" if scope_type == "project" else "groups"

        key = scope_key(scope_type, scope_id)
        visibility = self._visibility_cache.get(key)
        if visibility is _MISS:
            visibility = await client.get_visibility(api_scope, scope_id)
            self._visibility_cache.set(key, visibility)

        # public/internal scopes are readable by any signed-in GitLab user; a
        # private (or unknown) scope requires membership.
        if visibility in ("public", "internal"):
            return True
        return await client.is_member(api_scope, scope_id, user_id)
