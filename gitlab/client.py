"""Client asynchrone pour l'API REST GitLab (v4)."""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


class GitLabAPIError(Exception):
    """Erreur générique lors d'un appel à l'API GitLab."""


class GitLabAuthError(GitLabAPIError):
    """Token GitLab invalide ou expiré (401)."""


class GitLabNotFoundError(GitLabAPIError):
    """Ressource introuvable ou inaccessible (404), ou wiki désactivé."""


class GitLabClient:
    """Client minimal pour récupérer les pages de wiki des projets et groupes GitLab."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        if not base_url:
            raise ValueError("GITLAB_URL doit être configuré.")
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
            raise GitLabAPIError(f"Erreur réseau lors de l'appel à {path}: {exc}") from exc

        if response.status_code == 401:
            raise GitLabAuthError(f"Authentification GitLab refusée (token invalide ou expiré) pour {path}.")
        if response.status_code == 404:
            raise GitLabNotFoundError(f"Ressource introuvable ou wiki désactivé: {path}")
        if response.is_error:
            raise GitLabAPIError(f"Erreur GitLab {response.status_code} sur {path}: {response.text[:200]}")

        return response

    async def _get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Récupère toutes les pages d'une ressource paginée GitLab (pagination par offset)."""
        results: list[dict[str, Any]] = []
        page = 1
        params = dict(params or {})
        params["per_page"] = 100

        while True:
            params["page"] = page
            response = await self._get(path, params=params)
            data = response.json()
            if not isinstance(data, list):
                raise GitLabAPIError(f"Réponse inattendue (non paginée) pour {path}.")
            results.extend(data)

            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            page = int(next_page)

        return results

    async def get_project_wiki_pages(self, project_id: int) -> list[dict[str, Any]]:
        """Récupère toutes les pages de wiki d'un projet, contenu inclus."""
        return await self._get_wiki_pages("projects", project_id)

    async def get_group_wiki_pages(self, group_id: int) -> list[dict[str, Any]]:
        """Récupère toutes les pages de wiki d'un groupe, contenu inclus."""
        return await self._get_wiki_pages("groups", group_id)

    async def _get_wiki_pages(
        self, scope: Literal["projects", "groups"], scope_id: int
    ) -> list[dict[str, Any]]:
        path = f"/{scope}/{scope_id}/wikis"
        try:
            return await self._get_paginated(path, params={"with_content": 1})
        except GitLabNotFoundError:
            logger.warning("Wiki introuvable ou désactivé pour %s %s.", scope, scope_id)
            return []
