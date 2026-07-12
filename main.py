"""FastAPI entry point for the GitLab wiki chat application."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from chat.anthropic_chat import AnthropicChat
from chat.base import BaseChat
from chat.context import build_context
from chat.vllm import VLLMChat
from config import config
from gitlab.sync import SyncManager
from storage.wiki_store import WikiStore

logger = logging.getLogger(__name__)

store = WikiStore(config.DATA_DIR)
sync_manager = SyncManager(config, store)
scheduler = AsyncIOScheduler()


def _build_chat_client() -> BaseChat | None:
    if config.LLM_PROVIDER == "vllm":
        if not (config.VLLM_BASE_URL and config.VLLM_MODEL):
            logger.warning("VLLM_BASE_URL/VLLM_MODEL not configured: the /api/chat endpoint will be unavailable.")
            return None
        return VLLMChat(
            base_url=config.VLLM_BASE_URL,
            model=config.VLLM_MODEL,
            api_key=config.VLLM_API_KEY,
            max_history_messages=config.MAX_HISTORY_MESSAGES,
        )

    if config.LLM_PROVIDER == "anthropic":
        if not (config.ANTHROPIC_API_KEY and config.ANTHROPIC_MODEL):
            logger.warning(
                "ANTHROPIC_API_KEY/ANTHROPIC_MODEL not configured: the /api/chat endpoint will be unavailable."
            )
            return None
        return AnthropicChat(
            api_key=config.ANTHROPIC_API_KEY,
            model=config.ANTHROPIC_MODEL,
            max_history_messages=config.MAX_HISTORY_MESSAGES,
        )

    logger.warning("Unknown LLM_PROVIDER=%r: the /api/chat endpoint will be unavailable.", config.LLM_PROVIDER)
    return None


chat_client = _build_chat_client()


@asynccontextmanager
async def lifespan(app: FastAPI):
    for warning in config.validate():
        logger.warning("Configuration: %s", warning)

    if config.GITLAB_PROJECT_IDS or config.GITLAB_GROUP_IDS:
        logger.info("Starting initial wiki synchronization...")
        await sync_manager.sync_all()

        scheduler.add_job(
            sync_manager.sync_all,
            "interval",
            minutes=config.SYNC_INTERVAL_MINUTES,
            id="wiki_sync",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Automatic synchronization scheduled every %d minute(s).", config.SYNC_INTERVAL_MINUTES)
    else:
        logger.warning("No GitLab project/group configured: synchronization is disabled.")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="GitLab Wiki Chat", lifespan=lifespan)

SESSION_COOKIE = "session"
# Derived from AUTH_PASSWORD so sessions remain valid across restarts without extra config.
_SESSION_SECRET = hashlib.sha256(config.AUTH_PASSWORD.encode()).hexdigest()

# Paths reachable without a session, even when authentication is enabled.
PUBLIC_PATHS = {"/login", "/api/login", "/api/logout"}


def _sign(value: str) -> str:
    return hmac.new(_SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_session_cookie() -> str:
    return f"{config.AUTH_USERNAME}.{_sign(config.AUTH_USERNAME)}"


def _is_authenticated(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    username, _, signature = cookie.partition(".")
    return bool(signature) and secrets.compare_digest(username, config.AUTH_USERNAME) and secrets.compare_digest(
        signature, _sign(username)
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protects the whole app with a session login if AUTH_USERNAME/AUTH_PASSWORD are set."""
    if not (config.AUTH_USERNAME and config.AUTH_PASSWORD):
        return await call_next(request)

    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/assets/") or _is_authenticated(request):
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"error": "Authentication required."})

    return RedirectResponse("/login")


# The web UI is built with Vite (see frontend/); the compiled bundle is served from
# frontend/dist. During frontend development, use the Vite dev server instead
# (`npm run dev` in frontend/), which proxies API calls to this application.
if (config.FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")
else:
    logger.warning(
        "Frontend build not found in %s: run `npm install && npm run build` in frontend/.",
        config.FRONTEND_DIST,
    )


def _frontend_page(name: str) -> Response:
    page = config.FRONTEND_DIST / name
    if not page.is_file():
        return JSONResponse(
            status_code=503,
            content={"error": "Frontend build not found: run `npm install && npm run build` in frontend/."},
        )
    return FileResponse(page)


@app.get("/")
async def index() -> Response:
    return _frontend_page("index.html")


@app.get("/login")
async def login_page() -> Response:
    return _frontend_page("login.html")


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if secrets.compare_digest(username, config.AUTH_USERNAME) and secrets.compare_digest(
        password, config.AUTH_PASSWORD
    ):
        response = JSONResponse(content={"ok": True})
        response.set_cookie(
            SESSION_COOKIE,
            _make_session_cookie(),
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 3600,
        )
        return response

    return JSONResponse(status_code=401, content={"error": "Invalid username or password."})


@app.post("/api/logout")
async def logout() -> JSONResponse:
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/config")
async def app_config() -> JSONResponse:
    return JSONResponse(content={"gitlab_url": config.GITLAB_URL, "title": config.APP_TITLE})


@app.post("/api/sync")
async def trigger_sync() -> JSONResponse:
    if not (config.GITLAB_PROJECT_IDS or config.GITLAB_GROUP_IDS):
        return JSONResponse(
            status_code=400,
            content={"error": "No GitLab project/group configured."},
        )

    result = await sync_manager.sync_all()
    return JSONResponse(content=result)


@app.get("/api/status")
async def status() -> JSONResponse:
    result = sync_manager.status()
    result["auth_enabled"] = bool(config.AUTH_USERNAME and config.AUTH_PASSWORD)
    return JSONResponse(content=result)


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    if chat_client is None:
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': 'No LLM backend configured (see LLM_PROVIDER).'})}\n\n"]),
            media_type="text/event-stream",
            status_code=503,
        )

    body = await request.json()
    message = (body.get("message") or "").strip()
    history = body.get("history") or []

    if not message:
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': 'The message cannot be empty.'})}\n\n"]),
            media_type="text/event-stream",
            status_code=400,
        )

    context = build_context(store, config.MAX_CONTEXT_TOKENS)

    async def event_stream():
        try:
            async for delta in chat_client.stream_response(message, history, context.text):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as exc:  # pragma: no cover - last-resort safeguard for streaming
            logger.exception("Unexpected error while streaming the response.")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=config.APP_PORT, reload=True)
