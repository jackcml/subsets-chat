from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from subsets_chat.auth import (
    AuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    resolve_secret_key,
    unauthorized,
    verify_password,
)
from subsets_chat.db import ChatStore, NotFoundError, ValidationError


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def allowed_origins_from_env() -> list[str]:
    configured_origins = os.getenv("SUBSETS_CHAT_ALLOWED_ORIGINS", "")
    return [
        origin.strip()
        for origin in configured_origins.split(",")
        if origin.strip()
    ]


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=4000)


class ReplaceSetRequest(BaseModel):
    followed_user_ids: list[int] = Field(default_factory=list)


class CreateMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    reply_to_message_id: int | None = None


class ApiRootResponse(BaseModel):
    name: str


class HealthResponse(BaseModel):
    status: str


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class MessageResponse(BaseModel):
    id: int
    author_user_id: int
    author_display_name: str
    body: str
    reply_to_message_id: int | None
    created_at: str


class FeedReplyResponse(BaseModel):
    id: int
    author_user_id: int
    author_display_name: str
    body: str
    created_at: str


class FeedMessageResponse(MessageResponse):
    reply_to: FeedReplyResponse | None


class WebSocketMessageResponse(BaseModel):
    type: str
    message: FeedMessageResponse


class WebSocketUserJoinedResponse(BaseModel):
    type: str
    user: UserResponse


class WebSocketPresenceInitResponse(BaseModel):
    type: str
    user_ids: list[int]


class WebSocketUserPresenceResponse(BaseModel):
    type: str
    user_id: int


class ConnectionManager:
    def __init__(self, store: ChatStore):
        self.store = store
        self.connections: list[tuple[int, WebSocket]] = []

    def online_user_ids(self) -> list[int]:
        seen: set[int] = set()
        ordered: list[int] = []
        for viewer_id, _ in self.connections:
            if viewer_id in seen:
                continue
            seen.add(viewer_id)
            ordered.append(viewer_id)
        return ordered

    def connect(self, viewer_id: int, websocket: WebSocket) -> bool:
        already_online = any(vid == viewer_id for vid, _ in self.connections)
        self.connections.append((viewer_id, websocket))
        return not already_online

    def disconnect(self, websocket: WebSocket) -> tuple[int | None, bool]:
        departing_user_id: int | None = None
        for viewer_id, connection in self.connections:
            if connection is websocket:
                departing_user_id = viewer_id
                break
        self.connections = [
            (viewer_id, connection)
            for viewer_id, connection in self.connections
            if connection is not websocket
        ]
        if departing_user_id is None:
            return None, False
        still_online = any(vid == departing_user_id for vid, _ in self.connections)
        return departing_user_id, still_online

    async def broadcast_message(self, message_id: int) -> None:
        stale_connections: list[WebSocket] = []
        for viewer_id, websocket in list(self.connections):
            visible_message = self.store.message_visible_to(viewer_id, message_id)
            if visible_message is None:
                continue
            try:
                await websocket.send_json({"type": "message", "message": visible_message})
            except RuntimeError:
                stale_connections.append(websocket)

        for websocket in stale_connections:
            self.disconnect(websocket)

    async def broadcast_user_joined(self, user: dict[str, Any]) -> None:
        await self._broadcast_payload({"type": "user_joined", "user": user})

    async def broadcast_user_online(self, user_id: int) -> None:
        await self._broadcast_payload({"type": "user_online", "user_id": user_id})

    async def broadcast_user_offline(self, user_id: int) -> None:
        await self._broadcast_payload({"type": "user_offline", "user_id": user_id})

    async def send_presence_init(self, websocket: WebSocket) -> None:
        try:
            await websocket.send_json(
                {"type": "presence_init", "user_ids": self.online_user_ids()}
            )
        except RuntimeError:
            self.disconnect(websocket)

    async def _broadcast_payload(self, payload: dict[str, Any]) -> None:
        stale_connections: list[WebSocket] = []
        for _, websocket in list(self.connections):
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale_connections.append(websocket)

        for websocket in stale_connections:
            self.disconnect(websocket)


def create_app(database_path: str | Path | None = None) -> FastAPI:
    resolved_database_path: str | Path = (
        database_path
        if database_path is not None
        else os.getenv("SUBSETS_CHAT_DB", "subsets.db")
    )
    store = ChatStore(resolved_database_path)
    manager = ConnectionManager(store)
    secret_key = resolve_secret_key()

    app = FastAPI(
        title="Subsets Chat",
        summary="Constructive personal-set chat feed backend.",
        version="0.1.0",
    )
    app.state.store = store
    app.state.connection_manager = manager

    allowed_origins = allowed_origins_from_env()
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    def get_store() -> ChatStore:
        return store

    def user_for_token(token: str) -> dict[str, Any]:
        try:
            user_id = decode_access_token(token, secret_key)
            return store.get_user(user_id)
        except (AuthError, NotFoundError) as exc:
            raise unauthorized() from exc

    def current_user(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
        return user_for_token(token)

    def token_response(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "access_token": create_access_token(user["id"], secret_key),
            "token_type": "bearer",
            "user": user,
        }

    @app.get("/", include_in_schema=False, response_model=ApiRootResponse)
    def api_root() -> dict[str, str]:
        return {"name": "Subsets Chat API"}

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/register", status_code=201, response_model=TokenResponse)
    async def register(
        request: RegisterRequest,
        chat_store: ChatStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            user = chat_store.create_user(
                username=request.username,
                display_name=request.display_name,
                password_hash=hash_password(request.password),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await manager.broadcast_user_joined(user)
        return token_response(user)

    @app.post("/auth/token", response_model=TokenResponse)
    def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        chat_store: ChatStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = chat_store.get_user_by_username(form_data.username)
        if user is None or not verify_password(form_data.password, user["password_hash"]):
            raise unauthorized("Incorrect username or password")
        return token_response(
            {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "created_at": user["created_at"],
            }
        )

    @app.get("/me", response_model=UserResponse)
    def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return user

    @app.get("/users", response_model=list[UserResponse])
    def list_users(
        user: dict[str, Any] = Depends(current_user),
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict[str, Any]]:
        _ = user
        return chat_store.list_users()

    @app.get("/me/set", response_model=list[UserResponse])
    def get_my_follow_set(
        user: dict[str, Any] = Depends(current_user),
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict[str, Any]]:
        return chat_store.get_follow_set(user["id"])

    @app.put("/me/set", response_model=list[UserResponse])
    def replace_my_follow_set(
        request: ReplaceSetRequest,
        user: dict[str, Any] = Depends(current_user),
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict[str, Any]]:
        try:
            return chat_store.replace_follow_set(user["id"], request.followed_user_ids)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/messages", status_code=201, response_model=MessageResponse)
    async def create_message(
        request: CreateMessageRequest,
        user: dict[str, Any] = Depends(current_user),
        chat_store: ChatStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            message = chat_store.create_message(
                author_user_id=user["id"],
                body=request.body,
                reply_to_message_id=request.reply_to_message_id,
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await manager.broadcast_message(message["id"])
        return message

    @app.get("/feed", response_model=list[FeedMessageResponse])
    def get_feed(
        user: dict[str, Any] = Depends(current_user),
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict[str, Any]]:
        return chat_store.get_feed(user["id"])

    @app.websocket("/ws")
    async def websocket_feed(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            auth_message = await websocket.receive_json()
            token = auth_message.get("access_token")
            if auth_message.get("type") != "auth" or not isinstance(token, str):
                await websocket.close(code=1008)
                return
            user = user_for_token(token)
        except Exception:
            await websocket.close(code=1008)
            return

        first_connection = manager.connect(user["id"], websocket)
        await manager.send_presence_init(websocket)
        if first_connection:
            await manager.broadcast_user_online(user["id"])
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            departing_user_id, still_online = manager.disconnect(websocket)
            if departing_user_id is not None and not still_online:
                await manager.broadcast_user_offline(departing_user_id)

    return app


app = create_app()
