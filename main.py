"""FastAPI entry point for the GitLab wiki chat application."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


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
    return JSONResponse(content=sync_manager.status())


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
