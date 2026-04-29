from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..collector.subscriptions import event_matches_handles
from ..models import TwitterEvent


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def insert_event(self, event: TwitterEvent) -> bool:
        event_json = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        raw_json = json.dumps(event.raw, ensure_ascii=False, separators=(",", ":")) if event.raw is not None else None
        watch_key = ",".join(event.matched_handles)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                insert or ignore into events (
                    event_id, source_channel, coverage, action, author_handle,
                    tweet_id, matched_handles, event_json, raw_json, received_at_ms
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.source.channel,
                    event.source.coverage,
                    event.action,
                    event.author.handle,
                    event.tweet_id,
                    watch_key,
                    event_json,
                    raw_json,
                    event.received_at_ms,
                ),
            )
            return cursor.rowcount == 1

    def recent_events(self, *, limit: int, handles: set[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                select event_json
                from events
                order by received_at_ms desc, rowid desc
                limit ?
                """,
                (limit * 5 if handles else limit,),
            ).fetchall()

        events = [json.loads(row["event_json"]) for row in rows]
        if handles:
            events = [event for event in events if event_matches_handles(event, handles)]
        return events[:limit]

    def prune_older_than(self, cutoff_ms: int) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "delete from events where received_at_ms < ?",
                (cutoff_ms,),
            )
            return cursor.rowcount

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("pragma journal_mode=WAL")
            self._connection.execute("pragma synchronous=NORMAL")
            self._connection.execute(
                """
                create table if not exists events (
                    event_id text primary key,
                    source_channel text not null,
                    coverage text not null,
                    action text not null,
                    author_handle text,
                    tweet_id text,
                    matched_handles text not null,
                    event_json text not null,
                    raw_json text,
                    received_at_ms integer not null,
                    created_at text not null default current_timestamp
                )
                """
            )
            self._connection.execute(
                "create index if not exists idx_events_received_at on events(received_at_ms desc)"
            )
            self._connection.execute(
                "create index if not exists idx_events_author_handle on events(author_handle)"
            )
