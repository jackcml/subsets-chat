from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from subsets_chat.app import create_app
from subsets_chat.auth import ALGORITHM, resolve_secret_key


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


def register_user(
    client: TestClient,
    username: str,
    display_name: str | None = None,
    password: str = "secret",
) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "display_name": display_name or username.title(),
            "password": password,
        },
    )
    assert response.status_code == 201
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registration_hashes_password_and_returns_token(client: TestClient) -> None:
    payload = register_user(client, "alice", "Alice")

    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["user"]["username"] == "alice"
    app = cast(FastAPI, client.app)
    stored_user = app.state.store.get_user_by_username("alice")
    assert stored_user is not None
    assert stored_user["password_hash"] != "secret"


def test_duplicate_usernames_are_rejected_case_insensitively(client: TestClient) -> None:
    register_user(client, "Alice")

    response = client.post(
        "/auth/register",
        json={"username": "alice", "display_name": "Other Alice", "password": "secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "username is already taken"


def test_login_returns_token_and_uses_generic_invalid_credentials(
    client: TestClient,
) -> None:
    register_user(client, "alice", "Alice", "correct")

    login_response = client.post(
        "/auth/token",
        data={"username": "alice", "password": "correct"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["token_type"] == "bearer"

    wrong_password = client.post(
        "/auth/token",
        data={"username": "alice", "password": "wrong"},
    )
    missing_user = client.post(
        "/auth/token",
        data={"username": "missing", "password": "wrong"},
    )

    assert wrong_password.status_code == 401
    assert missing_user.status_code == 401
    assert wrong_password.json() == missing_user.json()


def test_me_rejects_missing_invalid_and_expired_tokens(client: TestClient) -> None:
    response = client.get("/me")
    assert response.status_code == 401

    invalid = client.get("/me", headers=auth_headers("not-a-token"))
    assert invalid.status_code == 401

    expired_token = jwt.encode(
        {
            "sub": "1",
            "typ": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        resolve_secret_key(),
        algorithm=ALGORITHM,
    )
    expired = client.get("/me", headers=auth_headers(expired_token))
    assert expired.status_code == 401


def test_authenticated_routes_use_token_user_identity(client: TestClient) -> None:
    alice_payload = register_user(client, "alice", "Alice")
    bob_payload = register_user(client, "bob", "Bob")
    alice_headers = auth_headers(alice_payload["access_token"])
    bob_headers = auth_headers(bob_payload["access_token"])

    set_response = client.put(
        "/me/set",
        json={"followed_user_ids": [alice_payload["user"]["id"]]},
        headers=bob_headers,
    )
    assert set_response.status_code == 200

    message_response = client.post(
        "/messages",
        json={"body": "hello from alice"},
        headers=alice_headers,
    )
    assert message_response.status_code == 201
    assert message_response.json()["author_user_id"] == alice_payload["user"]["id"]

    bob_feed = client.get("/feed", headers=bob_headers)
    assert bob_feed.status_code == 200
    assert [message["body"] for message in bob_feed.json()] == ["hello from alice"]

    alice_set = client.get("/me/set", headers=alice_headers)
    assert alice_set.status_code == 200
    assert alice_set.json() == []


def test_websocket_authenticates_with_initial_message(client: TestClient) -> None:
    alice_payload = register_user(client, "alice", "Alice")
    bob_payload = register_user(client, "bob", "Bob")
    client.put(
        "/me/set",
        json={"followed_user_ids": [alice_payload["user"]["id"]]},
        headers=auth_headers(bob_payload["access_token"]),
    )

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "auth", "access_token": bob_payload["access_token"]})
        presence = websocket.receive_json()
        assert presence["type"] == "presence_init"
        assert presence["user_ids"] == [bob_payload["user"]["id"]]

        response = client.post(
            "/messages",
            json={"body": "visible to bob"},
            headers=auth_headers(alice_payload["access_token"]),
        )
        assert response.status_code == 201

        pushed = websocket.receive_json()
        while pushed.get("type") != "message":
            pushed = websocket.receive_json()

    assert pushed["type"] == "message"
    assert pushed["message"]["body"] == "visible to bob"


def test_websocket_uses_updated_set_for_future_messages(client: TestClient) -> None:
    alice_payload = register_user(client, "alice", "Alice")
    bob_payload = register_user(client, "bob", "Bob")
    alice_headers = auth_headers(alice_payload["access_token"])
    bob_headers = auth_headers(bob_payload["access_token"])

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "auth", "access_token": bob_payload["access_token"]})
        presence = websocket.receive_json()
        assert presence["type"] == "presence_init"

        set_response = client.put(
            "/me/set",
            json={"followed_user_ids": [alice_payload["user"]["id"]]},
            headers=bob_headers,
        )
        assert set_response.status_code == 200

        message_response = client.post(
            "/messages",
            json={"body": "visible after set update"},
            headers=alice_headers,
        )
        assert message_response.status_code == 201

        pushed = websocket.receive_json()
        while pushed.get("type") != "message":
            pushed = websocket.receive_json()

    assert pushed["message"]["body"] == "visible after set update"


def test_websocket_emits_presence_events(client: TestClient) -> None:
    alice_payload = register_user(client, "alice", "Alice")
    bob_payload = register_user(client, "bob", "Bob")

    with client.websocket_connect("/ws") as alice_ws:
        alice_ws.send_json({"type": "auth", "access_token": alice_payload["access_token"]})
        alice_init = alice_ws.receive_json()
        assert alice_init["type"] == "presence_init"
        assert alice_init["user_ids"] == [alice_payload["user"]["id"]]

        alice_self_online = alice_ws.receive_json()
        assert alice_self_online == {
            "type": "user_online",
            "user_id": alice_payload["user"]["id"],
        }

        with client.websocket_connect("/ws") as bob_ws:
            bob_ws.send_json({"type": "auth", "access_token": bob_payload["access_token"]})
            bob_init = bob_ws.receive_json()
            assert bob_init["type"] == "presence_init"
            assert set(bob_init["user_ids"]) == {
                alice_payload["user"]["id"],
                bob_payload["user"]["id"],
            }

            alice_saw_bob_online = alice_ws.receive_json()
            assert alice_saw_bob_online == {
                "type": "user_online",
                "user_id": bob_payload["user"]["id"],
            }

        alice_saw_bob_offline = alice_ws.receive_json()
        assert alice_saw_bob_offline == {
            "type": "user_offline",
            "user_id": bob_payload["user"]["id"],
        }


def test_websocket_rejects_missing_or_invalid_auth(client: TestClient) -> None:
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "auth", "access_token": "not-a-token"})
        with pytest.raises(Exception):
            websocket.receive_json()


def test_configured_cors_allows_preflight_with_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://localhost:5173"
    monkeypatch.setenv(
        "SUBSETS_CHAT_ALLOWED_ORIGINS",
        f"{origin}, http://127.0.0.1:5173",
    )
    database_path = Path(f"test-cors-{uuid4().hex}.db")
    try:
        app = create_app(database_path)
        cors_client = TestClient(app)

        response = cors_client.options(
            "/feed",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    finally:
        database_path.unlink(missing_ok=True)

    assert response.status_code in {200, 204}
    assert response.headers["access-control-allow-origin"] == origin
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_unconfigured_cors_does_not_emit_allow_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUBSETS_CHAT_ALLOWED_ORIGINS", raising=False)
    database_path = Path(f"test-no-cors-{uuid4().hex}.db")
    try:
        app = create_app(database_path)
        cors_client = TestClient(app)

        response = cors_client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
    finally:
        database_path.unlink(missing_ok=True)

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
