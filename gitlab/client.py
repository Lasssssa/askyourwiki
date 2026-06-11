"""Asynchronous client for the GitLab REST API (v4)."""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


class GitLabAPIError(Exception):
    """Generic error during a call to the GitLab API."""


class GitLabAuthError(GitLabAPIError):
    """Invalid or expired GitLab token (401)."""


class GitLabNotFoundError(GitLabAPIError):
    """Resource not found or inaccessible (404), or wiki disabled."""


class GitLabClient:
    """Minimal client for fetching wiki pages of GitLab projects and groups."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        if not base_url:
            raise ValueError("GITLAB_URL must be configured.")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v4",
            headers={"PRIVATE-TOKEN": token} if token else {},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GitLabClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            response = await self._client.get(path, params=params)
        except httpx.RequestError as exc:
            raise GitLabAPIError(f"Network error while calling {path}: {exc}") from exc

        if response.status_code == 401:
            raise GitLabAuthError(f"GitLab authentication refused (invalid or expired token) for {path}.")
        if response.status_code == 404:
            raise GitLabNotFoundError(f"Resource not found or wiki disabled: {path}")
        if response.is_error:
            raise GitLabAPIError(f"GitLab error {response.status_code} on {path}: {response.text[:200]}")

        return response

    async def _get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Fetches all pages of a paginated GitLab resource (offset-based pagination)."""
        results: list[dict[str, Any]] = []
        page = 1
        params = dict(params or {})
        params["per_page"] = 100

        while True:
            params["page"] = page
            response = await self._get(path, params=params)
            data = response.json()
            if not isinstance(data, list):
                raise GitLabAPIError(f"Unexpected (non-paginated) response for {path}.")
            results.extend(data)

            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            page = int(next_page)

        return results

    async def get_project_wiki_pages(self, project_id: int) -> list[dict[str, Any]]:
        """Fetches all wiki pages of a project, including content."""
        return await self._get_wiki_pages("projects", project_id)

    async def get_group_wiki_pages(self, group_id: int) -> list[dict[str, Any]]:
        """Fetches all wiki pages of a group, including content."""
        return await self._get_wiki_pages("groups", group_id)

    async def _get_wiki_pages(
        self, scope: Literal["projects", "groups"], scope_id: int
    ) -> list[dict[str, Any]]:
        path = f"/{scope}/{scope_id}/wikis"
        try:
            return await self._get_paginated(path, params={"with_content": 1})
        except GitLabNotFoundError:
            logger.warning("Wiki not found or disabled for %s %s.", scope, scope_id)
            return []
