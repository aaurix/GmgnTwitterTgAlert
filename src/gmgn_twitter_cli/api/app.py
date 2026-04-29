from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse
from loguru import logger

from ..collector.direct_ws import DirectGmgnWebSocketClient
from ..collector.service import CollectorService
from ..settings import Settings, load_settings
from ..store.sqlite import EventStore
from .ws import PublicWebSocketHub


@dataclass(slots=True)
class CliRuntime:
    settings: Settings
    store: EventStore
    hub: PublicWebSocketHub
    collector: CollectorService
    collector_task: asyncio.Task | None = None
    retention_task: asyncio.Task | None = None


def create_app(settings: Settings | None = None, *, start_collector: bool = True) -> FastAPI:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = _build_runtime(resolved_settings, start_collector=start_collector)
        app.state.service = runtime
        logger.info(
            "Starting GMGN Twitter CLI | "
            f"handles={','.join(resolved_settings.handles) or 'all'} "
            f"channels={','.join(resolved_settings.upstream_channels)} "
            f"db={resolved_settings.event_db_path}"
        )
        try:
            yield
        finally:
            await _stop_runtime(runtime)

    app = FastAPI(title="GMGN Twitter CLI", lifespan=lifespan)

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok\n"

    @app.get("/readyz")
    async def readyz() -> dict:
        runtime = app.state.service
        return {
            "collector": runtime.collector.status.to_dict(),
            "handles": list(runtime.settings.handles),
            "store": str(runtime.settings.event_db_path),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await app.state.service.hub.handle(websocket)

    return app


def _build_runtime(settings: Settings, *, start_collector: bool) -> CliRuntime:
    store = EventStore(settings.event_db_path)
    hub = PublicWebSocketHub(token=settings.ws_token, store=store, default_replay_limit=settings.replay_limit)
    collector = CollectorService(
        handles=settings.handles,
        store=store,
        publisher=hub,
        upstream_client=None,
    )
    runtime = CliRuntime(settings=settings, store=store, hub=hub, collector=collector)
    if start_collector:
        upstream = DirectGmgnWebSocketClient(
            app_version=settings.upstream_app_version,
            channels=list(settings.upstream_channels),
            chains=list(settings.upstream_chains),
            proxy=settings.upstream_proxy,
            reconnect_delay=settings.upstream_reconnect_delay,
            heartbeat_interval=settings.upstream_heartbeat_interval,
            on_frame=collector.handle_frame,
        )
        collector.upstream_client = upstream
        runtime.collector_task = asyncio.create_task(collector.run())
    runtime.retention_task = asyncio.create_task(_retention_loop(store, settings.retention_days))
    return runtime


async def _stop_runtime(runtime: CliRuntime) -> None:
    tasks = [task for task in (runtime.collector_task, runtime.retention_task) if task is not None]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await runtime.collector.stop()
    runtime.store.close()


async def _retention_loop(store: EventStore, retention_days: int) -> None:
    retention_ms = retention_days * 24 * 60 * 60 * 1000
    while True:
        cutoff_ms = int(time.time() * 1000) - retention_ms
        deleted = store.prune_older_than(cutoff_ms)
        if deleted:
            logger.info(f"Pruned {deleted} old events from SQLite store")
        await asyncio.sleep(3600)
