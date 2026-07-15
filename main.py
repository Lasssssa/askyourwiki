"""FastAPI entry point for the GitLab wiki chat application."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlencode

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from chat.anthropic_chat import AnthropicChat
from chat.base import BaseChat
from chat.context import build_context
from chat.vllm import VLLMChat
from config import config
from gitlab.access import AccessResolver
from gitlab.sync import SyncManager
from storage.conversation_store import ConversationStore
from storage.wiki_store import WikiStore

logger = logging.getLogger(__name__)

store = WikiStore(config.DATA_DIR)
conversation_store = ConversationStore(config.CONVERSATIONS_DIR)
sync_manager = SyncManager(config, store)
access_resolver = AccessResolver(config, config.ACCESS_CACHE_TTL)
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
OAUTH_STATE_COOKIE = "oauth_state"


def _derive_session_secret() -> str:
    """Secret used to sign session cookies (HMAC key).

    Prefers an explicit SESSION_SECRET; otherwise derives one from the OAuth client
    secret so sessions remain valid across restarts without extra config. As a last
    resort (no auth configured), a random per-process secret is generated.
    """
    if config.SESSION_SECRET:
        return config.SESSION_SECRET
    if config.GITLAB_OAUTH_CLIENT_SECRET:
        return hashlib.sha256(config.GITLAB_OAUTH_CLIENT_SECRET.encode()).hexdigest()
    return secrets.token_hex(32)


_SESSION_SECRET = _derive_session_secret()

# Paths reachable without a session, even when authentication is enabled.
PUBLIC_PATHS = {"/login", "/api/logout"}
PUBLIC_PREFIXES = ("/assets/", "/auth/")


def _sign(value: str) -> str:
    return hmac.new(_SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_signed_cookie(value: str) -> str:
    return f"{value}.{_sign(value)}"


def _verify_signed_cookie(cookie: str) -> Optional[str]:
    """Returns the cookie's payload if its signature is valid, None otherwise."""
    value, _, signature = cookie.rpartition(".")
    if value and signature and secrets.compare_digest(signature, _sign(value)):
        return value
    return None


def _is_authenticated(request: Request) -> bool:
    return _verify_signed_cookie(request.cookies.get(SESSION_COOKIE, "")) is not None


def _current_user(request: Request) -> str:
    """The signed-in username, or 'anonymous' when authentication is disabled."""
    return _verify_signed_cookie(request.cookies.get(SESSION_COOKIE, "")) or "anonymous"


async def _allowed_scope_keys(request: Request) -> Optional[set]:
    """Scope keys the caller may read, or None when access control is off (= all).

    None means "no filtering" (authentication or access control disabled); an empty
    set means the user may read nothing.
    """
    if not config.wiki_access_control:
        return None
    return await access_resolver.accessible_scope_keys(_current_user(request))


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protects the whole app with a session login if any auth method is configured."""
    if not config.auth_enabled:
        return await call_next(request)

    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES) or _is_authenticated(request):
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


def _set_session_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        _make_signed_cookie(username),
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )


def _oauth_redirect_uri(request: Request) -> str:
    return config.GITLAB_OAUTH_REDIRECT_URI or str(request.url_for("gitlab_auth_callback"))


def _login_error_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(f"/login?{urlencode({'error': message})}")


@app.get("/auth/gitlab")
async def gitlab_auth_start(request: Request) -> RedirectResponse:
    """Starts the OAuth2 Authorization Code flow against the GitLab instance."""
    if not config.gitlab_auth_enabled:
        return _login_error_redirect("GitLab sign-in is not configured.")

    state = secrets.token_urlsafe(32)
    params = urlencode(
        {
            "client_id": config.GITLAB_OAUTH_CLIENT_ID,
            "redirect_uri": _oauth_redirect_uri(request),
            "response_type": "code",
            "scope": "read_user",
            "state": state,
        }
    )
    response = RedirectResponse(f"{config.GITLAB_URL}/oauth/authorize?{params}")
    # Short-lived, signed anti-CSRF state, checked on callback.
    response.set_cookie(
        OAUTH_STATE_COOKIE, _make_signed_cookie(state), httponly=True, samesite="lax", max_age=600
    )
    return response


@app.get("/auth/gitlab/callback")
async def gitlab_auth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> RedirectResponse:
    """Exchanges the authorization code for a token and opens a session."""
    if not config.gitlab_auth_enabled:
        return _login_error_redirect("GitLab sign-in is not configured.")

    if error:
        return _login_error_redirect(error_description or f"GitLab sign-in failed ({error}).")

    expected_state = _verify_signed_cookie(request.cookies.get(OAUTH_STATE_COOKIE, ""))
    if not code or not state or expected_state is None or not secrets.compare_digest(state, expected_state):
        return _login_error_redirect("GitLab sign-in failed (invalid state). Please try again.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_response = await client.post(
                f"{config.GITLAB_URL}/oauth/token",
                data={
                    "client_id": config.GITLAB_OAUTH_CLIENT_ID,
                    "client_secret": config.GITLAB_OAUTH_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": _oauth_redirect_uri(request),
                },
            )
            token_response.raise_for_status()
            access_token = token_response.json().get("access_token", "")
            if not access_token:
                return _login_error_redirect("GitLab sign-in failed (no access token returned).")

            user_response = await client.get(
                f"{config.GITLAB_URL}/api/v4/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
            username = user_response.json().get("username", "")
    except httpx.HTTPStatusError:
        logger.exception("GitLab OAuth flow rejected by the instance.")
        return _login_error_redirect("GitLab sign-in failed: the GitLab instance rejected the request.")
    except httpx.HTTPError:
        logger.exception("GitLab OAuth flow failed.")
        return _login_error_redirect("GitLab sign-in failed: could not reach the GitLab instance.")

    if not username:
        return _login_error_redirect("GitLab sign-in failed (no username in the GitLab profile).")

    logger.info("GitLab sign-in successful for %r.", username)
    response = RedirectResponse("/")
    _set_session_cookie(response, username)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@app.post("/api/logout")
async def logout() -> JSONResponse:
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/config")
async def app_config() -> JSONResponse:
    return JSONResponse(
        content={
            "gitlab_url": config.GITLAB_URL,
            "title": config.APP_TITLE,
            "history_enabled": config.SAVE_CONVERSATIONS,
        }
    )


@app.get("/api/me")
async def me(request: Request) -> JSONResponse:
    """Returns the signed-in user's GitLab profile, for display in the sidebar.

    The session only stores the username; the display fields (name, avatar) are
    looked up from GitLab with the app token. Returns an empty object when there
    is no session (e.g. authentication disabled).
    """
    username = _verify_signed_cookie(request.cookies.get(SESSION_COOKIE, ""))
    if username is None:
        return JSONResponse(content={})

    profile = {"username": username, "name": None, "avatar_url": None, "web_url": None}
    if config.GITLAB_URL and config.GITLAB_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{config.GITLAB_URL}/api/v4/users",
                    params={"username": username},
                    headers={"PRIVATE-TOKEN": config.GITLAB_TOKEN},
                )
                response.raise_for_status()
                users = response.json()
            if users:
                user = users[0]
                profile["name"] = user.get("name")
                profile["avatar_url"] = user.get("avatar_url")
                profile["web_url"] = user.get("web_url")
        except httpx.HTTPError:
            logger.warning("Could not fetch the GitLab profile for %r.", username)

    return JSONResponse(content=profile)


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
async def status(request: Request) -> JSONResponse:
    result = sync_manager.status()
    result["auth_enabled"] = config.auth_enabled
    result["access_control"] = config.wiki_access_control
    if config.wiki_access_control:
        allowed = await access_resolver.accessible_scope_keys(_current_user(request))
        result["pages_accessible"] = store.count_pages(allowed)
    return JSONResponse(content=result)


@app.get("/api/conversations")
async def list_conversations(request: Request) -> JSONResponse:
    """Summaries of the current user's past conversations, newest first."""
    if not config.SAVE_CONVERSATIONS:
        return JSONResponse(content={"conversations": []})
    conversations = conversation_store.list_conversations(_current_user(request))
    return JSONResponse(content={"conversations": conversations})


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request) -> JSONResponse:
    """Full message history of one of the current user's conversations."""
    conversation = conversation_store.get_conversation(_current_user(request), conversation_id)
    if conversation is None:
        return JSONResponse(status_code=404, content={"error": "Conversation not found."})
    return JSONResponse(content=conversation)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request) -> JSONResponse:
    if conversation_store.delete_conversation(_current_user(request), conversation_id):
        return JSONResponse(content={"ok": True})
    return JSONResponse(status_code=404, content={"error": "Conversation not found."})


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
    conversation_id = (body.get("conversation_id") or "").strip()
    user = _current_user(request)

    if not message:
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': 'The message cannot be empty.'})}\n\n"]),
            media_type="text/event-stream",
            status_code=400,
        )

    # Restrict the context to the wikis this user is allowed to read (None = all).
    allowed_scopes = await _allowed_scope_keys(request)
    context = build_context(store, config.MAX_CONTEXT_TOKENS, allowed_scopes)

    async def event_stream():
        answer_parts: list[str] = []
        failed = False
        try:
            async for delta in chat_client.stream_response(message, history, context.text):
                answer_parts.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as exc:  # pragma: no cover - last-resort safeguard for streaming
            failed = True
            logger.exception("Unexpected error while streaming the response.")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            answer = "".join(answer_parts)
            if config.SAVE_CONVERSATIONS and not failed and answer.strip():
                try:
                    conversation_store.append_turn(user, conversation_id, message, answer)
                except Exception:  # pragma: no cover - persistence must never break the stream
                    logger.exception("Failed to persist the conversation turn.")
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=config.APP_PORT, reload=True)
