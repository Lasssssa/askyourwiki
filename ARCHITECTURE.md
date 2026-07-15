# Architecture - AskYourWiki

This document describes the internal workings of the application: how the components fit
together, how data flows, and the important design decisions.

## Overview

```
┌─────────────┐      ┌──────────────────────────────────────────────┐      ┌─────────────┐
│   GitLab     │◄────►│              FastAPI (main.py)                │◄────►│  LLM backend │
│ (projects &  │ REST │                                                │ API  │ (vLLM /      │
│  groups,     │      │  ┌────────────┐  ┌────────────┐  ┌──────────┐ │      │  Anthropic)  │
│  wikis)      │      │  │ SyncManager│  │ WikiStore  │  │ context/ │ │      └─────────────┘
└─────────────┘      │  │(gitlab/sync│  │(storage/   │  │  chat    │ │
                      │  │   .py)     │  │wiki_store) │  │ (chat/)  │ │
                      │  └────────────┘  └────────────┘  └──────────┘ │
                      │         │               │                      │
                      │         └──────►  data/wikis/*.md ◄────────────┘
                      └────────────────────┬───────────────────────────┘
                                            │ HTTP (SSE)
                                            ▼
                                  ┌────────────────────┐
                                  │ frontend/ (web UI)  │
                                  │  React + Vite (TS)  │
                                  └────────────────────┘
```

The application has two main flows:

1. **Synchronization flow**: GitLab → `gitlab/client.py` → `gitlab/sync.py` →
   `storage/wiki_store.py` → markdown files in `data/wikis/`.
2. **Chat flow**: browser → `POST /api/chat` → `chat/context.py` (reads
   `data/wikis/`) → LLM backend (`chat/vllm.py` or `chat/anthropic_chat.py`, called with
   streaming) → SSE → browser.

## Configuration (`config.py`)

Single entry point for all environment variables (loaded via `python-dotenv` from `.env`).
Exposes a singleton `config` object used by every module:

- `GITLAB_URL`, `GITLAB_TOKEN`: access to the GitLab instance
- `GITLAB_PROJECT_IDS`, `GITLAB_GROUP_IDS`: lists of IDs (parsed from `"123,456"` strings),
  scopes to synchronize
- `LLM_PROVIDER`: LLM backend used (`vllm` by default, or `anthropic`)
- `VLLM_BASE_URL`, `VLLM_MODEL`, `VLLM_API_KEY`: access to the OpenAI-compatible self-hosted model
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`: access to the hosted Anthropic API (if `LLM_PROVIDER=anthropic`)
- `SYNC_INTERVAL_MINUTES`: frequency of the scheduled sync job
- `APP_TITLE`: title displayed in the web UI header (exposed via `GET /api/config`)
- `GITLAB_OAUTH_CLIENT_ID`, `GITLAB_OAUTH_CLIENT_SECRET`, `GITLAB_OAUTH_REDIRECT_URI`,
  `SESSION_SECRET`: optional "Sign in with GitLab" (see [Authentication](#authentication))
- `MAX_CONTEXT_TOKENS` (150,000 by default): token budget for the context sent to the model
- `MAX_HISTORY_MESSAGES` (5 by default): number of history exchanges kept
- `DATA_DIR`: `data/wikis/`, root of local storage
- `FRONTEND_DIST`: `frontend/dist/`, compiled web UI served by the backend

`Config.validate()` returns a list of warnings (missing config) logged at startup, without
blocking the application from starting (allows starting even without GitLab config, e.g. to
test the UI).

## Wiki synchronization

### `gitlab/client.py` — `GitLabClient`

Asynchronous HTTP client (httpx) wrapping the GitLab REST API v4.

- All requests go through `_get()`, which translates HTTP status codes into domain
  exceptions: `GitLabAuthError` (401), `GitLabNotFoundError` (404 — project/group/wiki
  inaccessible or disabled), `GitLabAPIError` (other errors / network errors).
- `_get_paginated()` follows the `X-Next-Page` header to fetch all pages of a paginated
  resource (100 items per page).
- `get_project_wiki_pages(project_id)` / `get_group_wiki_pages(group_id)` call
  `GET /projects/:id/wikis` and `GET /groups/:id/wikis` respectively, with
  `with_content=1` (so the markdown content is fetched in a single pass). If the wiki is
  disabled or missing (404), the method returns an empty list instead of raising.
- `get_project_root_markdown_pages(project_id)` lists the root of the project's default
  branch via `GET /projects/:id/repository/tree`, keeps the `*.md` blobs, and fetches each
  one's raw content via `GET /projects/:id/repository/files/:path/raw`. Each file is
  returned in the same shape as a wiki page, with `slug` prefixed by `repo-root/` (e.g.
  `repo-root/README.md`) so it doesn't collide with actual wiki pages. If the repository is
  missing or empty (404), it returns an empty list; a file that fails to fetch is skipped
  with a warning rather than failing the whole sync.

### `gitlab/sync.py` — `SyncManager`

Orchestrates synchronization and keeps state (`last_sync_at`, `last_sync_errors`,
`is_syncing`) consumed by `/api/status`.

- `sync_all()`: for each project (`GITLAB_PROJECT_IDS`) then each group
  (`GITLAB_GROUP_IDS`), calls `_sync_scope()`. A lock (`is_syncing`) prevents concurrent
  runs (if a scheduled sync and a manual sync overlap, the second one is ignored and
  returns the current status).
- `_sync_scope(client, scope_type, scope_id)`: fetches the pages via the client — for
  projects, this combines the wiki pages with the root-level `*.md` files of the
  repository — then **fully replaces** the scope's local content (`store.reset_scope()`
  removes the directory, then each page is rewritten via `store.save_page()`). Per-scope
  errors are caught and accumulated in `last_sync_errors` without interrupting
  synchronization of the other scopes.

> **Why a full resync instead of incremental?** The GitLab `/wikis` API returns no
> last-modified date per page. There is therefore no reliable way to know which pages
> changed without re-downloading everything. A full resync per scope remains cheap (wikis
> are rarely large) and guarantees that pages deleted on the GitLab side also disappear
> from local storage.

### `storage/wiki_store.py` — `WikiStore`

File-based persistence layer, no database.

- Layout: `data/wikis/{scope_type}_{scope_id}/{slug}.md` (`/` in nested slugs are replaced
  with `__`).
- Each file contains a simple frontmatter block (`---` ... `---`) with `title`, `slug`,
  `scope_type`, `scope_id`, `format`, `synced_at`, followed by the page's raw markdown
  content.
- `load_all_pages()` reads back the whole directory, parses the frontmatter, and returns a
  list of `WikiPage` **sorted by `synced_at` descending** (most recently synced pages
  first) — this order is later used for context truncation.
- `count_pages()` / `reset_scope()` are utilities for status and resync.

## Chat with the LLM

### `chat/context.py` — `build_context()`

Builds the text that will be injected into the model's system prompt.

- Loads all pages via `WikiStore.load_all_pages()` (already sorted, most recent first).
- Formats each page as a markdown section: `### {title} (scope: ..., slug: ...)` followed by
  the content.
- Accumulates sections as long as the cumulative size (in characters) stays under
  `MAX_CONTEXT_TOKENS * 4` (heuristic of ~4 characters/token). As soon as adding a page
  would exceed the budget, it stops: the oldest pages are therefore the first to be
  excluded (priority to recent pages, as required by the spec).
- Edge case: if even the first page alone exceeds the budget, it is hard-truncated to
  `max_chars` characters.
- Returns a `WikiContext` object (`text`, `pages_included`, `pages_total`, `truncated`) for
  logging/diagnostics.

### `chat/base.py` — `BaseChat` and interchangeable backends

The generation engine is **pluggable** via `LLM_PROVIDER` (`vllm` or `anthropic`).
`BaseChat` factors out what is common to both backends:

- `SYSTEM_PROMPT_TEMPLATE`: instructs the model to answer **only** from the provided wiki
  context, to explicitly say when information is missing, and to answer in the language of
  the question. The context produced by `build_context()` is injected directly into this
  template.
- `_build_messages()`: trims the history received from the frontend to the last
  `MAX_HISTORY_MESSAGES` exchanges (× 2 messages per exchange = user + assistant), then
  appends the new user message.
- `stream_response(message, history, context_text)`: an async generator that `yield`s each
  text fragment of the response — this is the interface implemented by each backend and
  consumed directly by the FastAPI endpoint.

#### `chat/vllm.py` — `VLLMChat` (default backend, self-hosted model)

Uses the `openai` SDK (`AsyncOpenAI`) pointed at `VLLM_BASE_URL` (the OpenAI-compatible
`/v1/chat/completions` endpoint exposed by vLLM or any equivalent server). The system
prompt is passed as the first `role: "system"` message in the `messages` list.
`stream_response()` consumes the `chat.completions.create(..., stream=True)` stream and
yields `chunk.choices[0].delta.content` on each iteration. On API error, an error message
is yielded as text rather than raising, so the SSE stream ends cleanly on the client side.

#### `chat/anthropic_chat.py` — `AnthropicChat` (hosted API, optional)

Uses the official `anthropic` SDK (`AsyncAnthropic`). `stream_response()` calls
`client.messages.stream(...)` with the configured model (`ANTHROPIC_MODEL`, system prompt +
messages), and relays `stream.text_stream`. Same error guarantees as `VLLMChat` (error
message yielded rather than raised as an exception).

#### Backend selection (`main.py`)

`_build_chat_client()` reads `config.LLM_PROVIDER` and instantiates `VLLMChat` or
`AnthropicChat` accordingly (or returns `None` if the required configuration is missing, in
which case `/api/chat` responds with 503). The rest of the application (sync, context, UI,
SSE streaming) is strictly identical regardless of the chosen backend.

## FastAPI API (`main.py`)

At module load time:
- Instantiates `WikiStore`, `SyncManager`, `AsyncIOScheduler`, and the `chat_client`
  corresponding to `LLM_PROVIDER` via `_build_chat_client()` (if the required configuration
  is missing, `chat_client` is `None` and `/api/chat` will respond with 503).

`lifespan` (app lifecycle):
1. Logs warnings for missing configuration.
2. If projects/groups are configured: runs an **initial blocking synchronization**
   (`await sync_manager.sync_all()`) before the server accepts traffic, then schedules
   `sync_manager.sync_all` as a recurring job (`SYNC_INTERVAL_MINUTES`) via APScheduler.
3. Otherwise: logs a warning, no sync is scheduled.
4. On shutdown: cleanly stops the scheduler.

### Authentication

Sign-in is delegated entirely to the `GITLAB_URL` instance via **Sign in with GitLab**
(`GITLAB_OAUTH_CLIENT_ID` + `GITLAB_OAUTH_CLIENT_SECRET`), a standard OAuth2 Authorization
Code flow ending in a signed session cookie. `GET /auth/gitlab` redirects to the instance's
`/oauth/authorize` with the `read_user` scope and an anti-CSRF `state` (random value stored
in a short-lived signed cookie). `GET /auth/gitlab/callback` verifies the state, exchanges
the code for an access token (`POST /oauth/token`), fetches the user's profile
(`GET /api/v4/user`) to get their username, then sets the session cookie and redirects to
`/`. Failures redirect to `/login?error=...`, which the login page displays. The redirect
URI is derived from the incoming request unless `GITLAB_OAUTH_REDIRECT_URI` is set (reverse
proxies).

A `@app.middleware("http")` function (`auth_middleware`) runs before every request. If
OAuth is configured (`config.auth_enabled`):

- `/login`, `/api/logout`, `/auth/*`, and `/assets/*` are always reachable.
- Other requests are authenticated via the session cookie (`session`,`httponly`,
  `samesite=lax`, 30-day expiry): `{username}.{HMAC-SHA256(username)}`. The HMAC key is
  `SESSION_SECRET` if set, otherwise derived from `GITLAB_OAUTH_CLIENT_SECRET` — so
  sessions remain valid across restarts without extra configuration, but rotate
  automatically if the secret changes. Comparisons use `secrets.compare_digest` to avoid
  timing attacks.
- If the cookie is missing/invalid: `/api/*` requests get a `401` JSON error, other
  requests are redirected to `/login`.

`GET /login` serves the login page, which shows the "Sign in with GitLab" button.
`POST /api/logout` clears the session cookie.

If OAuth is not configured, the middleware is a no-op and the app remains open — this
keeps the "no `.env` required" Docker quick-start working. The frontend reflects this via
`auth_enabled` in `/api/status`, which controls whether the "Log out" button is shown.

Routes:

| Route | Behavior |
|---|---|
| `GET /` | Serves `frontend/dist/index.html` (the chat UI) |
| `GET /assets/*` | Compiled JS/CSS bundles via `StaticFiles` |
| `GET /login` | Serves `frontend/dist/login.html` |
| `POST /api/logout` | Clears the session cookie |
| `GET /auth/gitlab` | Redirects to GitLab's `/oauth/authorize` (with anti-CSRF state) |
| `GET /auth/gitlab/callback` | Verifies the state, exchanges the code, opens the session |
| `GET /api/config` | UI configuration: `gitlab_url` (sidebar link) and `title` (header) |
| `GET /api/me` | Signed-in user's GitLab profile (username, name, avatar, web URL) for the sidebar; `{}` when no session |
| `POST /api/sync` | Triggers `sync_manager.sync_all()` (400 if no scope configured) and returns the resulting status |
| `GET /api/status` | Returns `sync_manager.status()`: number of indexed pages, last sync, errors, configured scopes, `auth_enabled` |
| `POST /api/chat` | See below |

### `POST /api/chat` in detail

1. Reads `{message, history}` from the JSON body. 503 if no LLM backend is configured, 400
   if the message is empty.
2. Builds the wiki context via `build_context(store, config.MAX_CONTEXT_TOKENS)` —
   **reloaded on every request** (so it immediately reflects the latest synchronization).
3. Returns a `StreamingResponse` (`text/event-stream`) that:
   - iterates over `chat_client.stream_response(message, history, context.text)`,
   - emits each fragment as `data: {"delta": "..."}\n\n`,
   - emits `data: {"error": "..."}\n\n` on exception,
   - always ends with `data: [DONE]\n\n`.

## Web interface (`frontend/`)

React + TypeScript application built with Vite. It is a **multi-page build** with two
entry documents matching the backend routes: `index.html` (the chat UI, entry
`src/chat/main.tsx`) and `login.html` (the sign-in page, entry `src/login/main.tsx`).
The production bundle is emitted into `frontend/dist/` and served directly by FastAPI
(`GET /` / `GET /login` return the HTML documents, `/assets/*` the hashed JS/CSS
bundles). All dependencies — including `marked` and `highlight.js` — are bundled locally,
so the UI works on restricted networks without any CDN access.

- **`src/chat/App.tsx`**: top-level state — the message list, streaming flag, sync
  status (polled from `/api/status` every 30s), UI config from `/api/config` (header
  title, GitLab link), the signed-in user from `/api/me`, and mobile sidebar visibility.
  `sendMessage()` iterates over the SSE stream and progressively updates the assistant
  message.
- **`src/chat/Sidebar.tsx`**: brand, "New conversation", status card, the "Sync wikis"
  button (with syncing/success/error states), the signed-in user card (avatar with an
  initial-letter fallback, name and `@username`, from `GET /api/me`), the GitLab instance
  link, and the "Log out" button (shown when `auth_enabled` is true; calls `POST /api/logout`
  then redirects to `/login`).
- **`src/chat/Messages.tsx`**: welcome screen, message rows (user/assistant/error
  bubbles), and the animated typing indicator.
- **`src/chat/Composer.tsx`**: auto-resizing textarea (Enter sends, Shift+Enter inserts
  a newline) and the send button.
- **`src/login/LoginPage.tsx`**: the sign-in page. Renders the "Sign in with GitLab"
  button (a link to `/auth/gitlab`) and displays errors passed back via the `?error=`
  query parameter after a failed OAuth flow.
- **`src/shared/api.ts`**: typed wrappers for every backend endpoint. `streamChat()` is
  an async generator that sends `POST /api/chat`, reads the response via
  `response.body.getReader()` (SSE is parsed manually since `EventSource` doesn't
  support POST), and yields `{delta}` / `{error}` events.
- **`src/shared/markdown.ts`**: markdown rendering with `marked` + `marked-highlight` +
  `highlight.js`, sanitized with DOMPurify before being injected into the DOM.
- **`src/styles/`**: `base.css` (shared variables — `--bg-app`, `--accent`, `--brand`,
  etc. — and reset), `chat.css` (sidebar, bubbles, typing indicator, composer), and
  `login.css` (centered card, pill-shaped inputs, error banner).

During development, `npm run dev` starts the Vite dev server (hot reload) which proxies
`/api` and `/auth` requests to the FastAPI backend on port 8000.

## Data synchronization: order of operations

```
App startup
   │
   ├─► sync_all() (blocking)
   │      ├─► for each project: reset_scope + save_page(s)
   │      └─► for each group: reset_scope + save_page(s)
   │
   ├─► scheduler.start()  (replays sync_all() every SYNC_INTERVAL_MINUTES)
   │
   └─► server accepts requests

/api/chat request
   │
   ├─► build_context()  ← reads data/wikis/**/*.md (current state, post-last sync)
   ├─► chat_client.stream_response(message, history, context)
   └─► SSE → browser (progressive rendering)

/api/sync request (manual, or UI button)
   └─► sync_all() (same logic as startup)
```

## Notable design decisions

- **No database**: markdown file storage is sufficient for the expected volume (wikis of a
  few projects/groups) and has the advantage of being directly inspectable/version-controllable.
- **Full resync per scope** rather than incremental (see GitLab API limitation in the
  README).
- **Context reloaded on every message** rather than cached: guarantees freshness of
  responses after a sync, at the cost of one disk read per request (negligible given the
  data volume).
- **Token heuristic (4 chars/token)** rather than an exact tokenizer: sufficient to stay
  under the context limit with a safety margin, without an extra dependency.
- **End-to-end streaming** (LLM model → SSE → fetch reader → DOM) for immediate visual
  feedback, as required by the spec.
