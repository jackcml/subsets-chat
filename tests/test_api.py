from pathlib import Path
from uuid import uuid4
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from subsets_chat.app import create_app


@pytest.fixture()
def client() -> Generator[TestClient]:
    database_path = Path(f"test-api-{uuid4().hex}.db")
    try:
        app = create_app(database_path)
        yield TestClient(app)
    finally:
        for path in [
            database_path,
            database_path.with_suffix(".db-shm"),
            database_path.with_suffix(".db-wal"),
        ]:
            path.unlink(missing_ok=True)


def create_user(client: TestClient, display_name: str) -> int:
    response = client.post("/users", json={"display_name": display_name})
    assert response.status_code == 201
    return response.json()["id"]


def test_http_feed_filtering_matches_constructive_set_rules(client: TestClient) -> None:
    alice = create_user(client, "Alice")
    bob = create_user(client, "Bob")
    charlie = create_user(client, "Charlie")

    charlie_root = client.post(
        "/messages",
        json={"author_user_id": charlie, "body": "charlie root"},
    ).json()
    client.post(
        "/messages",
        json={
            "author_user_id": alice,
            "body": "alice to charlie",
            "reply_to_message_id": charlie_root["id"],
        },
    )
    client.put(f"/users/{bob}/set", json={"followed_user_ids": [alice]})

    assert client.get(f"/feed?viewer_id={bob}").json() == []

    client.put(f"/users/{bob}/set", json={"followed_user_ids": [alice, charlie]})

    feed = client.get(f"/feed?viewer_id={bob}").json()
    assert [message["body"] for message in feed] == ["charlie root", "alice to charlie"]
    assert feed[1]["reply_to"]["body"] == "charlie root"


def test_websocket_receives_only_visible_messages(client: TestClient) -> None:
    alice = create_user(client, "Alice")
    bob = create_user(client, "Bob")
    charlie = create_user(client, "Charlie")
    client.put(f"/users/{bob}/set", json={"followed_user_ids": [alice]})

    with client.websocket_connect(f"/ws?viewer_id={bob}") as websocket:
        hidden_response = client.post(
            "/messages",
            json={"author_user_id": charlie, "body": "hidden from bob"},
        )
        assert hidden_response.status_code == 201

        visible_response = client.post(
            "/messages",
            json={"author_user_id": alice, "body": "visible to bob"},
        )
        assert visible_response.status_code == 201

        pushed = websocket.receive_json()

    assert pushed["type"] == "message"
    assert pushed["message"]["body"] == "visible to bob"


def test_websocket_uses_updated_set_for_future_messages(client: TestClient) -> None:
    alice = create_user(client, "Alice")
    bob = create_user(client, "Bob")

    with client.websocket_connect(f"/ws?viewer_id={bob}") as websocket:
        client.put(f"/users/{bob}/set", json={"followed_user_ids": [alice]})
        response = client.post(
            "/messages",
            json={"author_user_id": alice, "body": "visible after set update"},
        )
        assert response.status_code == 201

        pushed = websocket.receive_json()

    assert pushed["message"]["body"] == "visible after set update"
