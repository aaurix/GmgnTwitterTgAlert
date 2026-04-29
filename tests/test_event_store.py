import tempfile
import unittest
from pathlib import Path

from gmgn_twitter_cli.models import Author, Content, Source, TwitterEvent
from gmgn_twitter_cli.store.sqlite import EventStore


def make_event(event_id: str, handle: str, received_at_ms: int = 1000) -> TwitterEvent:
    return TwitterEvent(
        event_id=event_id,
        source=Source(
            provider="gmgn",
            transport="direct_ws",
            coverage="public_stream",
            channel="twitter_monitor_basic",
        ),
        action="tweet",
        original_action=None,
        tweet_id="tweet-1",
        internal_id=event_id,
        timestamp=received_at_ms // 1000,
        received_at_ms=received_at_ms,
        author=Author(handle=handle, name=handle, avatar=None, followers=None, tags=[]),
        content=Content(text="hello", media=[]),
        reference=None,
        unfollow_target=None,
        avatar_change=None,
        bio_change=None,
        matched_handles=[handle],
        raw={"i": event_id},
    )


class EventStoreTests(unittest.TestCase):
    def test_insert_event_is_idempotent_and_recent_events_are_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(Path(tmpdir) / "events.sqlite3")
            first_insert = store.insert_event(make_event("event-1", "toly", 1000))
            duplicate_insert = store.insert_event(make_event("event-1", "toly", 1000))
            store.insert_event(make_event("event-2", "elonmusk", 2000))

            recent = store.recent_events(limit=10)
            store.close()

        self.assertTrue(first_insert)
        self.assertFalse(duplicate_insert)
        self.assertEqual([event["event_id"] for event in recent], ["event-2", "event-1"])

    def test_recent_events_can_filter_by_handles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EventStore(Path(tmpdir) / "events.sqlite3")
            store.insert_event(make_event("event-1", "toly", 1000))
            store.insert_event(make_event("event-2", "elonmusk", 2000))

            recent = store.recent_events(limit=10, handles={"toly"})
            store.close()

        self.assertEqual([event["author"]["handle"] for event in recent], ["toly"])


if __name__ == "__main__":
    unittest.main()
