from pathlib import Path
from uuid import uuid4

import pytest

from subsets_chat.db import ChatStore


@pytest.fixture()
def store() -> ChatStore:
    database_path = Path(f"test-feed-{uuid4().hex}.db")
    try:
        yield ChatStore(database_path)
    finally:
        for path in [
            database_path,
            database_path.with_suffix(".db-shm"),
            database_path.with_suffix(".db-wal"),
        ]:
            path.unlink(missing_ok=True)


@pytest.fixture()
def users(store: ChatStore) -> dict[str, int]:
    return {
        "alice": store.create_user("Alice")["id"],
        "bob": store.create_user("Bob")["id"],
        "charlie": store.create_user("Charlie")["id"],
    }


def feed_bodies(store: ChatStore, viewer_id: int) -> list[str]:
    return [message["body"] for message in store.get_feed(viewer_id)]


def test_bob_sees_alice_root_message_when_alice_is_in_his_set(
    store: ChatStore, users: dict[str, int]
) -> None:
    store.replace_follow_set(users["bob"], [users["alice"]])
    store.create_message(users["alice"], "alice root")

    assert feed_bodies(store, users["bob"]) == ["alice root"]


def test_bob_does_not_see_alice_root_message_without_following_her(
    store: ChatStore, users: dict[str, int]
) -> None:
    store.create_message(users["alice"], "alice root")

    assert feed_bodies(store, users["bob"]) == []


def test_reply_to_non_set_member_is_hidden(store: ChatStore, users: dict[str, int]) -> None:
    charlie_message = store.create_message(users["charlie"], "charlie root")
    store.create_message(
        users["alice"],
        "alice replies to charlie",
        reply_to_message_id=charlie_message["id"],
    )
    store.replace_follow_set(users["bob"], [users["alice"]])

    assert feed_bodies(store, users["bob"]) == []


def test_reply_to_set_member_is_visible_with_parent_context(
    store: ChatStore, users: dict[str, int]
) -> None:
    charlie_message = store.create_message(users["charlie"], "charlie root")
    store.create_message(
        users["alice"],
        "alice replies to charlie",
        reply_to_message_id=charlie_message["id"],
    )
    store.replace_follow_set(users["bob"], [users["alice"], users["charlie"]])

    feed = store.get_feed(users["bob"])

    assert [message["body"] for message in feed] == [
        "charlie root",
        "alice replies to charlie",
    ]
    assert feed[1]["reply_to"] == {
        "id": charlie_message["id"],
        "author_user_id": users["charlie"],
        "author_display_name": "Charlie",
        "body": "charlie root",
        "created_at": charlie_message["created_at"],
    }


def test_user_always_sees_their_own_messages(store: ChatStore, users: dict[str, int]) -> None:
    store.create_message(users["bob"], "bob root")

    assert feed_bodies(store, users["bob"]) == ["bob root"]


def test_set_updates_change_future_feed_results_without_rewriting_messages(
    store: ChatStore, users: dict[str, int]
) -> None:
    store.create_message(users["alice"], "already global")

    assert feed_bodies(store, users["bob"]) == []

    store.replace_follow_set(users["bob"], [users["alice"]])

    assert feed_bodies(store, users["bob"]) == ["already global"]
