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
                                  │  static/ (web UI)   │
                                  │ index.html / app.js │
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
- `MAX_CONTEXT_TOKENS` (150,000 by default): token budget for the context sent to the model
- `MAX_HISTORY_MESSAGES` (5 by default): number of history exchanges kept
- `DATA_DIR`: `data/wikis/`, root of local storage

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

### Authentication middleware

A `@app.middleware("http")` function (`auth_middleware`) runs before every request. If
`AUTH_USERNAME` and `AUTH_PASSWORD` are both set:

- `/login`, `/logout`, and `/static/*` are always reachable.
- Other requests are authenticated via a signed session cookie (`session`). The cookie's
  signature is an HMAC-SHA256 of the username, keyed by a secret derived from
  `AUTH_PASSWORD` (`hashlib.sha256(AUTH_PASSWORD)`) — so sessions remain valid across
  restarts without extra configuration, but rotate automatically if the password changes.
  Comparisons use `secrets.compare_digest` to avoid timing attacks.
- If the cookie is missing/invalid: `/api/*` requests get a `401` JSON error, other
  requests are redirected to `/login`.

`GET /login` serves `static/login.html` (styled like the rest of the app). `POST /login`
checks `{username, password}` (JSON body) against `AUTH_USERNAME`/`AUTH_PASSWORD` and, on
success, sets the session cookie (`httponly`, `samesite=lax`, 30-day expiry). `POST
/logout` clears it.

If either `AUTH_USERNAME` or `AUTH_PASSWORD` is unset, the middleware is a no-op and the
app remains open — this keeps the "no `.env` required" Docker quick-start working. The
frontend reflects this via `auth_enabled` in `/api/status`, which controls whether the
"Log out" button is shown.

Routes:

| Route | Behavior |
|---|---|
| `GET /` | Serves `static/index.html` |
| `GET /static/*` | Static files (CSS/JS) via `StaticFiles` |
| `GET /login` | Serves `static/login.html` |
| `POST /login` | Checks `{username, password}` and sets the session cookie on success |
| `POST /logout` | Clears the session cookie |
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

## Web interface (`static/`)

- **`index.html`** / **`login.html`**: page structure. `index.html` is the chat UI (status
  bar + sync button, message area, textarea + send button) and loads `marked.js` via CDN
  for markdown rendering; `login.html` is the sign-in form shown when authentication is
  enabled.
- **`css/base.css`**: shared variables (`--bg-app`, `--accent`, `--brand`, etc.), reset, and
  a global `[hidden] { display: none !important; }` rule so JS-toggled elements hide
  correctly regardless of other `display` rules.
- **`css/chat.css`**: the chat UI — sidebar, message bubbles (styled differently for
  user/assistant/error), animated typing indicator, composer.
- **`css/login.css`**: the login page — centered card, pill-shaped inputs matching the
  chat composer, and the error banner.
- **`js/app.js`**:
  - `sendMessage()`: appends the user message to local history (`conversationHistory`),
    sends `POST /api/chat`, reads the response via `response.body.getReader()` (SSE is
    parsed manually since `EventSource` doesn't support POST), accumulates the `delta`
    chunks and progressively re-renders the markdown in the assistant bubble.
  - `refreshStatus()`: polls `/api/status` every 30s and displays
    "X indexed pages · last synced N minutes ago".
  - `triggerSync()`: calls `POST /api/sync`, disables the button during the operation and
    shows the result (number of pages) before reverting to the initial state.
  - The "Log out" button is shown/hidden based on `auth_enabled` from `/api/status` and
    calls `POST /logout` before redirecting to `/login`.
- **`js/login.js`**: submits `{username, password}` to `POST /login` as JSON and
  redirects to `/` on success, or shows the returned error message otherwise.

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
