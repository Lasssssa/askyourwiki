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

import logging
import time
from typing import Optional

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

    def _configured_scopes(self) -> list[tuple[str, int]]:
        return [("project", pid) for pid in self._config.GITLAB_PROJECT_IDS] + [
            ("group", gid) for gid in self._config.GITLAB_GROUP_IDS
        ]

    async def accessible_scope_keys(self, username: str) -> set[str]:
        cached = self._cache.get(username)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]

        try:
            allowed = await self._compute(username)
        except GitLabAPIError as exc:
            # A total failure (e.g. GitLab unreachable): deny, but don't cache it
            # so the next request retries once GitLab is back.
            logger.warning("Access resolution failed for %r: %s; denying (not cached).", username, exc)
            return set()

        self._cache.set(username, allowed)
        return allowed

    async def _compute(self, username: str) -> set[str]:
        scopes = self._configured_scopes()
        if not scopes:
            return set()

        allowed: set[str] = set()
        async with GitLabClient(self._config.GITLAB_URL, self._config.GITLAB_TOKEN) as client:
            user_id = await client.get_user_id(username)
            if user_id is None:
                logger.warning("Access: no GitLab user found for %r; denying all scopes.", username)
                return set()

            for scope_type, scope_id in scopes:
                try:
                    if await self._can_read(client, scope_type, scope_id, user_id):
                        allowed.add(scope_key(scope_type, scope_id))
                except GitLabAPIError as exc:
                    # Fail closed for this scope only.
                    logger.warning(
                        "Access check failed for %s %s (user %r): %s; denying this scope.",
                        scope_type,
                        scope_id,
                        username,
                        exc,
                    )

        return allowed

    async def _can_read(
        self, client: GitLabClient, scope_type: str, scope_id: int, user_id: int
    ) -> bool:
        api_scope = "projects" if scope_type == "project" else "groups"
        visibility = await client.get_visibility(api_scope, scope_id)
        # public/internal scopes are readable by any signed-in GitLab user; a
        # private (or unknown) scope requires membership.
        if visibility in ("public", "internal"):
            return True
        return await client.is_member(api_scope, scope_id, user_id)
