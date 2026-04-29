from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

import uvicorn

from .api.app import create_app
from .logging_setup import setup_logging
from .settings import load_settings
from .store.sqlite import EventStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gmgn-twitter-cli")
    subcommands = parser.add_subparsers(dest="command")

    serve = subcommands.add_parser("serve", help="run the collector service")
    serve.add_argument("--host", default=None, help="override API bind host")
    serve.add_argument("--port", type=int, default=None, help="override API bind port")

    recent = subcommands.add_parser("recent", help="print recent stored events")
    recent.add_argument("--db", type=Path, default=None, help="override SQLite event store path")
    recent.add_argument("--limit", type=int, default=20)
    recent.add_argument("--handles", default="")

    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "serve":
        settings = load_settings()
        setup_logging(settings.log_file)
        host = args.host or settings.api_host
        port = args.port or settings.api_port
        uvicorn.run(
            create_app(settings=settings),
            host=host,
            port=port,
            log_config=None,
            ws_ping_interval=settings.ws_heartbeat_interval,
            ws_ping_timeout=settings.ws_heartbeat_interval * 2,
        )
        return 0

    if command == "recent":
        handles = {item.strip().lstrip("@").lower() for item in args.handles.split(",") if item.strip()}
        db_path = args.db or load_settings().event_db_path
        store = EventStore(db_path)
        try:
            events = store.recent_events(limit=args.limit, handles=handles)
        finally:
            store.close()
        _emit({"ok": True, "data": {"events": events}}, stdout)
        return 0

    parser.error(f"unknown command: {command}")
    return 2


def _emit(payload: dict, stdout: TextIO) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
