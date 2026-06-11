"""Synchronization of GitLab wikis (projects and groups) to local storage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import Config
from gitlab.client import GitLabAPIError, GitLabClient
from storage.wiki_store import WikiStore

logger = logging.getLogger(__name__)


class SyncManager:
    """Orchestrates synchronization of GitLab wikis to the `WikiStore`."""

    def __init__(self, config: Config, store: WikiStore) -> None:
        self.config = config
        self.store = store
        self.last_sync_at: str | None = None
        self.last_sync_errors: list[str] = []
        self.is_syncing: bool = False

    async def sync_all(self) -> dict[str, Any]:
        """Fully resynchronizes the wikis of all configured projects/groups.

        Note: the GitLab "wikis" API does not provide a last-modified date per
        page, so a truly incremental per-page sync isn't possible. Each scope
        (project/group) is fully re-downloaded and then replaced locally.
        """
        if self.is_syncing:
            logger.info("Synchronization already in progress, request ignored.")
            return self.status()

        self.is_syncing = True
        self.last_sync_errors = []
        pages_synced = 0

        try:
            async with GitLabClient(self.config.GITLAB_URL, self.config.GITLAB_TOKEN) as client:
                for project_id in self.config.GITLAB_PROJECT_IDS:
                    pages_synced += await self._sync_scope(client, "project", project_id)

                for group_id in self.config.GITLAB_GROUP_IDS:
                    pages_synced += await self._sync_scope(client, "group", group_id)
        except GitLabAPIError as exc:
            logger.error("Fatal error during synchronization: %s", exc)
            self.last_sync_errors.append(str(exc))
        finally:
            self.is_syncing = False

        self.last_sync_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Synchronization finished: %d page(s) synced, %d error(s).",
            pages_synced,
            len(self.last_sync_errors),
        )
        return self.status()

    async def _sync_scope(self, client: GitLabClient, scope_type: str, scope_id: int) -> int:
        try:
            if scope_type == "project":
                pages = await client.get_project_wiki_pages(scope_id)
            else:
                pages = await client.get_group_wiki_pages(scope_id)
        except GitLabAPIError as exc:
            message = f"{scope_type} {scope_id}: {exc}"
            logger.error("Synchronization failed for %s", message)
            self.last_sync_errors.append(message)
            return 0

        if not pages:
            logger.info("No wiki pages found for %s %s.", scope_type, scope_id)
            return 0

        self.store.reset_scope(scope_type, scope_id)
        for page in pages:
            self.store.save_page(
                scope_type=scope_type,
                scope_id=scope_id,
                slug=page.get("slug", "untitled"),
                title=page.get("title", page.get("slug", "untitled")),
                content=page.get("content", ""),
                page_format=page.get("format", "markdown"),
            )

        logger.info("%d page(s) synced for %s %s.", len(pages), scope_type, scope_id)
        return len(pages)

    def status(self) -> dict[str, Any]:
        return {
            "pages_indexed": self.store.count_pages(),
            "last_sync_at": self.last_sync_at,
            "is_syncing": self.is_syncing,
            "last_sync_errors": self.last_sync_errors,
            "configured_projects": self.config.GITLAB_PROJECT_IDS,
            "configured_groups": self.config.GITLAB_GROUP_IDS,
        }
