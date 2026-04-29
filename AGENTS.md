# AGENTS.md

Guidance for coding agents working in this repository.

## Development Commands

```bash
uv sync
uv run pytest
uv run ruff check .
uv run python -m compileall src tests
```

Run the CLI service:

```bash
uv run gmgn-twitter-cli serve
```

Equivalent module entrypoint:

```bash
uv run python -m gmgn_twitter_cli serve
```

Query stored events:

```bash
uv run gmgn-twitter-cli recent --limit 20
```

## Architecture

This is a standard `uv` project using `src/gmgn_twitter_cli`.

The CLI service consumes GMGN anonymous public Twitter WebSocket channels, normalizes events, filters by a simple handle list, stores matching events in SQLite, and exposes an authenticated FastAPI WebSocket API at `/ws`.

The public configuration surface is intentionally small:

- `MONITOR_HANDLES`: comma-separated Twitter handles.
- `WS_TOKEN`: public WebSocket API token.
- `API_HOST` / `API_PORT`: FastAPI bind address.
- SQLite and retention settings.

GMGN chains, channels, app versions, and protocol frames are internal collector strategy, not user-facing subscription concepts.

## Module Responsibilities

- `src/gmgn_twitter_cli/settings.py`: pydantic-settings environment loader.
- `src/gmgn_twitter_cli/api/app.py`: FastAPI app, health probes, WebSocket route, lifespan tasks.
- `src/gmgn_twitter_cli/api/ws.py`: authenticated WebSocket subscribe/replay/live push hub.
- `src/gmgn_twitter_cli/collector/direct_ws.py`: GMGN upstream WebSocket adapter.
- `src/gmgn_twitter_cli/collector/normalizer.py`: raw frame parsing and stable event normalization.
- `src/gmgn_twitter_cli/collector/service.py`: collector pipeline, `cp=0/cp=1` snapshot gate, handle matching, store-first publish.
- `src/gmgn_twitter_cli/store/sqlite.py`: SQLite WAL event journal and replay queries.
- `src/gmgn_twitter_cli/cli.py`: `serve` and `recent` commands.

## Runtime Notes

- Public clients authenticate with `{"type":"auth","token":"..."}`.
- Public clients subscribe with `{"type":"subscribe","handles":["toly"],"replay":20}`.
- `coverage=public_stream` means events are filtered from GMGN's anonymous public stream; it is not a full Twitter firehose guarantee.
- Run one ASGI worker unless the collector and API are split into separate processes.
- Systemd unit lives at `deploy/systemd/gmgn-twitter-cli.service`.
- macOS LaunchAgent installer lives at `deploy/macos/install_launchd.sh`.
- Runtime artifacts should live under ignored `data/` and `logs/`.

## MCP

Do not use MCP as the live event stream. FastMCP can be added later as an optional query/control plane, but `/ws` remains the production push API.
