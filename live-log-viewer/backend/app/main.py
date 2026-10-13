import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .manager import manager_instance, Subscriber


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await manager_instance.initial_scan()
    manager_instance.start_watching()
    poll_task = asyncio.create_task(manager_instance.poll_loop())
    try:
        yield
    finally:
        poll_task.cancel()
        manager_instance.stop_watching()


app = FastAPI(title="Live Log Viewer", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/groups")
async def get_groups():
    """Groups -> list of {key, name}. `key` is the service directory relative
    to the log root (unique); the absolute filesystem path is never exposed."""
    return manager_instance.discovery.to_api()


@app.get("/logs")
async def get_logs(
    services: Optional[List[str]] = Query(default=None, description="service keys from /groups"),
    levels: Optional[List[str]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    time_range: Optional[str] = Query(default=None, description="5m|30m|1h|6h|today"),
    since: Optional[float] = Query(default=None, description="epoch seconds"),
    until: Optional[float] = Query(default=None, description="epoch seconds"),
    limit: int = Query(default=1000, le=5000),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    entries = manager_instance.get_logs(
        services=services,
        levels=levels,
        search=search,
        time_range=time_range,
        since_epoch=since,
        until_epoch=until,
        limit=limit,
        order=order,
    )
    return {"count": len(entries), "entries": [e.model_dump() for e in entries]}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tracked_files": len(manager_instance.tailers),
        "buffered_entries": manager_instance.buffered_count,
        "root": manager_instance.root,
    }


@app.websocket("/ws/logs")
async def ws_logs(
    websocket: WebSocket,
    services: Optional[List[str]] = Query(default=None),
    levels: Optional[List[str]] = Query(default=None),
    search: Optional[str] = Query(default=None),
):
    await websocket.accept()
    subscriber = Subscriber(websocket, services=services, levels=levels, search=search)
    manager_instance.subscribers.append(subscriber)
    try:
        while True:
            # We don't need inbound messages for streaming, but allow the
            # client to push updated filters without reconnecting.
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "update_filters":
                subscriber.services = set(msg.get("services") or []) or None
                subscriber.levels = set(str(l).upper() for l in (msg.get("levels") or [])) or None
                subscriber.search = msg.get("search") or None
    except (WebSocketDisconnect, ValueError, RuntimeError):
        # ValueError: non-JSON frame; RuntimeError: socket already closed
        pass
    finally:
        if subscriber in manager_instance.subscribers:
            manager_instance.subscribers.remove(subscriber)
