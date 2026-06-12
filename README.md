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
- A clean dark-mode web interface, with markdown rendering and syntax highlighting for responses
- Ready-to-use Docker setup

## Requirements

- Python 3.11+
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
   | `AUTH_USERNAME` / `AUTH_PASSWORD` | Optional HTTP Basic Auth credentials (see [Authentication](#authentication)) |

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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

The application will be available at http://localhost:8000.

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

The app has no user accounts, but it can be protected with a single shared HTTP Basic Auth
credential. Set both `AUTH_USERNAME` and `AUTH_PASSWORD` in `.env` to require a login for
every route (the UI and all `/api/*` endpoints):

```bash
AUTH_USERNAME=admin
AUTH_PASSWORD=<a-strong-password>
```

Leave both empty (the default) to disable authentication entirely. If only one of the two
is set, the app logs a warning and authentication stays disabled.

> This is a single shared credential, not per-user accounts — suitable for personal or
> small-team use. For multi-user access control, put the app behind your own
> reverse proxy / SSO, or run it on a private network / VPN.

## Usage

- Ask your questions in the chat area: answers are generated from the content of the
  indexed wikis and streamed in real time.
- The **"Sync wikis"** button triggers a full manual resynchronization.
- The status bar shows the number of indexed pages and the date of the last synchronization.

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the chat interface |
| `POST` | `/api/chat` | `{message, history}` → streaming SSE response |
| `POST` | `/api/sync` | Triggers a manual wiki synchronization |
| `GET` | `/api/status` | Number of indexed pages, last sync date, any errors |

## Known limitations

- The GitLab REST API for wikis (`/wikis`) does not provide a last-modified date per page.
  Synchronization is therefore a **full resync** of each configured project/group (not an
  incremental page-by-page diff).
- The token count estimate used for context truncation is a simple heuristic
  (~4 characters per token), not an exact count from the model's tokenizer.
- Wiki pages in formats other than Markdown (e.g. AsciiDoc, RDoc) are stored as-is; their
  rendering in the context sent to the model is not converted to markdown.
- Authentication is a single shared HTTP Basic Auth credential (no per-user accounts). If
  it's not configured, deploy the app behind a reverse proxy / VPN if it shouldn't be
  publicly accessible.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed description of the components, data
flow, and design decisions.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started.

## License

This project is licensed under the [MIT License](LICENSE).
