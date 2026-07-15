# AskYourWiki

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A chat application for querying the wikis (projects and/or groups) of a self-hosted GitLab
instance in natural language, powered by a large language model (LLM) as the response engine.

The generation engine is **pluggable**: by default the application uses a self-hosted model via
an **OpenAI**-compatible API (for example served by **vLLM**, but also Ollama, llama.cpp, TGI,
...). A hosted API (Anthropic) can be used as an alternative.

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Configuration (.env)](#configuration-env)
- [Running locally](#running-locally)
- [Running with Docker](#running-with-docker)
- [OpenAI-compatible self-hosted model (vLLM, etc.)](#openai-compatible-self-hosted-model-vllm-etc)
- [Hosted API (Anthropic) as an alternative](#hosted-api-anthropic-as-an-alternative)
- [Authentication](#authentication)
- [Usage](#usage)
- [API](#api)
- [Known limitations](#known-limitations)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## Features

- Synchronization of wiki pages from GitLab projects and groups to local markdown storage
- For projects, also synchronizes the Markdown files (`*.md`) found at the root of the
  repository's default branch (e.g. `README.md`, `CONTRIBUTING.md`)
- Periodic automatic synchronization + manual sync endpoint
- Natural language chat based on wiki content, with streaming responses (SSE)
- Configurable LLM engine: OpenAI-compatible self-hosted model (vLLM, ...) by default, or hosted API
- A clean dark-mode web interface (React + Vite), with markdown rendering and syntax
  highlighting for responses — all assets bundled locally, no CDN required at runtime
- Ready-to-use Docker setup

## Requirements

- Python 3.11+
- Node.js 20+ (only to build the web UI; not needed when running with Docker)
- A GitLab Personal Access Token with the `read_api` (or `api`) scope
- An LLM engine:
  - either a server exposing an OpenAI-compatible API (e.g. [vLLM](https://github.com/vllm-project/vllm), Ollama, TGI, llama.cpp) — default
  - or an API key for an Anthropic-compatible provider, as an alternative
- (Optional) Docker and Docker Compose

## Configuration (.env)

1. Copy the example file:

   ```bash
   cp .env.example .env
   ```

2. Fill in the variables:

   | Variable | Description |
   |---|---|
   | `GITLAB_URL` | Base URL of your GitLab instance (e.g. `https://gitlab.mycompany.com`) |
   | `GITLAB_TOKEN` | GitLab Personal Access Token (`read_api` scope) |
   | `GITLAB_PROJECT_IDS` | IDs of the projects whose wikis should be indexed, comma-separated |
   | `GITLAB_GROUP_IDS` | IDs of the groups whose wikis should be indexed (optional) |
   | `LLM_PROVIDER` | `vllm` (default) or `anthropic` |
   | `VLLM_BASE_URL` / `VLLM_MODEL` / `VLLM_API_KEY` | Self-hosted model configuration (if `LLM_PROVIDER=vllm`) |
   | `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Hosted API configuration (if `LLM_PROVIDER=anthropic`) |
   | `SYNC_INTERVAL_MINUTES` | Frequency of automatic synchronization (in minutes) |
   | `APP_PORT` | Port the application listens on |
   | `APP_TITLE` | Title displayed in the web UI header (optional) |
   | `SAVE_CONVERSATIONS` | Persist users' chat history to `data/conversations/` (default `true`) |
   | `ACCESS_CONTROL` / `ACCESS_CACHE_TTL` | Restrict each signed-in user to the wikis they can access on GitLab (default `true`; see [Access control](#access-control)) |
   | `GITLAB_OAUTH_CLIENT_ID` / `GITLAB_OAUTH_CLIENT_SECRET` | "Sign in with GitLab" OAuth application (see [Authentication](#authentication)) |
   | `GITLAB_OAUTH_REDIRECT_URI` / `SESSION_SECRET` | Optional OAuth callback URL override and session-cookie signing secret |

### Finding GitLab project/group IDs

- **Project**: open the project on GitLab, the ID is shown under the project name on the
  project's home page (or via `Settings > General`). It is also visible in the response of
  `GET /api/v4/projects/<namespace>%2F<project>` (encode `/` as `%2F`).
- **Group**: open the group on GitLab, the ID is shown under the group name on the group's
  home page (or via `Settings > General`).

> The wiki must be enabled for the relevant project or group, and the token must have read
> access to that project/group.

## Running locally

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Web UI (built once, then served by the backend from frontend/dist)
make front-install front-build

uvicorn main:app --reload --port 8000
```

The application will be available at http://localhost:8000.

To work on the web UI itself, start the Vite dev server alongside the backend
(`make front-dev`, served at http://localhost:5173 with hot reload); it proxies API
calls to the backend on port 8000.

On startup, an initial wiki synchronization is triggered automatically (if any
projects/groups are configured), then a periodic synchronization is scheduled every
`SYNC_INTERVAL_MINUTES` minutes.

## Running with Docker

```bash
docker compose up --build
```

That's it — a single command builds the image and starts the app, available at
http://localhost:8000. The `.env` file is optional: without it the app starts with no
GitLab/LLM configuration (and logs warnings), which is enough to check that everything
runs. To enable synchronization and chat, create a `.env` from `.env.example` (see
[Configuration](#configuration-env)) before running the command above.

Synchronized wiki pages are persisted in `./data/wikis` (mounted as a volume).

## OpenAI-compatible self-hosted model (vLLM, etc.)

By default (`LLM_PROVIDER=vllm`), the application calls a server exposing an OpenAI-compatible
"chat completions" API. Configure your `.env`:

```bash
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://<host>:8000/v1
VLLM_MODEL=<served-model-name>
VLLM_API_KEY=EMPTY
```

- `VLLM_BASE_URL` must point to the server's `/v1` endpoint (started for example with
  `vllm serve <model> --port 8000`).
- `VLLM_MODEL` must exactly match the name returned by `GET /v1/models` on your server (by
  default the HuggingFace path/name of the model, or the value passed to
  `--served-model-name`).
- `VLLM_API_KEY`: leave as `EMPTY` if the server is started without authentication.
  Otherwise, provide the expected key.

> The chosen model must have a context window large enough to hold the wiki content + the
> history. If your model has a window smaller than 150k tokens, reduce `MAX_CONTEXT_TOKENS`
> in `.env` accordingly.

## Hosted API (Anthropic) as an alternative

To use a hosted API instead of a self-hosted model, configure:

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=<your-key>
ANTHROPIC_MODEL=<model-id>
```

The rest of the application (wiki synchronization, context, interface, streaming) works
identically regardless of the chosen engine: only the `chat/` module changes internally
(`chat/vllm.py` or `chat/anthropic_chat.py`).

## Authentication

Authentication is optional and, when enabled, is handled entirely by your GitLab instance
via OAuth2. Once configured, every route (the UI and all `/api/*` endpoints) requires a
sign-in: unauthenticated visitors are redirected to a login page at `/login`, a signed
session cookie is set on success, and a **"Log out"** button appears at the bottom of the
sidebar. Leave the OAuth variables empty (the default) to keep the app open.

### Sign in with GitLab (OAuth2)

Let users sign in with their existing account on your GitLab instance (`GITLAB_URL`):

1. On GitLab, create an OAuth application (**User/Group/Admin Settings > Applications**)
   with the `read_user` scope and the redirect URI
   `https://<your-app-host>/auth/gitlab/callback`.
2. Fill in `.env`:

   ```bash
   GITLAB_OAUTH_CLIENT_ID=<application-id>
   GITLAB_OAUTH_CLIENT_SECRET=<application-secret>
   # Optional; set it explicitly when running behind a reverse proxy:
   GITLAB_OAUTH_REDIRECT_URI=https://<your-app-host>/auth/gitlab/callback
   ```

The login page then shows a **"Sign in with GitLab"** button that runs the standard OAuth2
Authorization Code flow against your instance.

> Any user who can sign in to the GitLab instance can access the app (the app only asks
> for the `read_user` scope to identify them — it never sees the user's password and gets
> no access to their repositories). If you need finer-grained access control, put the app
> behind your own reverse proxy / SSO.

### Sessions

Sessions are HMAC-signed cookies. The signing secret is derived from the OAuth client
secret by default (sessions survive restarts); set `SESSION_SECRET` to control it
explicitly (e.g. when running several replicas).

## Access control

When GitLab sign-in is enabled, each user only sees answers drawn from the wikis of the
projects/groups **they can access on GitLab** (`ACCESS_CONTROL=true`, the default). For
every configured scope the app decides access with its own `GITLAB_TOKEN`:

- **public / internal** projects and groups → readable by any signed-in user;
- **private** ones → readable only if the user is a (direct or inherited) **member**.

The wiki context sent to the model is filtered to the allowed scopes, so content the user
can't access is never included in an answer. The decision is cached per user for
`ACCESS_CACHE_TTL` seconds (default 300), so membership changes take effect within a few
minutes. On a GitLab error the app **fails closed** (denies the scope) rather than leaking
content.

> Notes: this needs a `GITLAB_TOKEN` that can read the projects/groups' membership (the
> same token that syncs them). It reflects GitLab **membership and visibility**, not
> per-feature `wiki_access_level` overrides. Set `ACCESS_CONTROL=false` to let every
> signed-in user query all indexed wikis. When authentication is disabled the app is fully
> open and no filtering applies.

## Usage

- Ask your questions in the chat area: answers are generated from the content of the
  indexed wikis and streamed in real time.
- The **"Sync wikis"** button triggers a full manual resynchronization.
- The status bar shows the number of indexed pages and the date of the last synchronization.
- The **"History"** section of the sidebar lists your past conversations: click one to
  reopen and continue it, or delete it. Conversations are saved per user under
  `data/conversations/`; set `SAVE_CONVERSATIONS=false` to disable saving entirely.

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the chat interface |
| `POST` | `/api/chat` | `{message, history, conversation_id}` → streaming SSE response (persists the turn) |
| `POST` | `/api/sync` | Triggers a manual wiki synchronization |
| `GET` | `/api/status` | Indexed pages (and accessible pages under access control), last sync, errors |
| `GET` | `/api/config` | UI configuration (GitLab instance URL, app title, history enabled) |
| `GET` | `/api/me` | Signed-in user's GitLab profile (username, name, avatar) for the sidebar |
| `GET` | `/api/conversations` | Current user's past conversations (summaries, newest first) |
| `GET` | `/api/conversations/{id}` | Full message history of one conversation |
| `DELETE` | `/api/conversations/{id}` | Deletes one conversation |
| `GET` | `/auth/gitlab` | Starts the "Sign in with GitLab" OAuth2 flow |
| `GET` | `/auth/gitlab/callback` | OAuth2 callback (exchanges the code, opens the session) |

## Known limitations

- The GitLab REST API for wikis (`/wikis`) does not provide a last-modified date per page.
  Synchronization is therefore a **full resync** of each configured project/group (not an
  incremental page-by-page diff).
- The token count estimate used for context truncation is a simple heuristic
  (~4 characters per token), not an exact count from the model's tokenizer.
- Wiki pages in formats other than Markdown (e.g. AsciiDoc, RDoc) are stored as-is; their
  rendering in the context sent to the model is not converted to markdown.
- With `ACCESS_CONTROL` enabled, users are restricted to the wikis of the GitLab
  projects/groups they can access (membership + visibility). If authentication is not
  configured the app is fully open — deploy it behind a reverse proxy / VPN if it
  shouldn't be publicly accessible.
- Saved conversations are stored as plain JSON on disk, scoped per user but unencrypted;
  when authentication is disabled they are all filed under `anonymous`. Set
  `SAVE_CONVERSATIONS=false` if conversation content shouldn't be persisted.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed description of the components, data
flow, and design decisions.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started.

## License

This project is licensed under the [MIT License](LICENSE).
