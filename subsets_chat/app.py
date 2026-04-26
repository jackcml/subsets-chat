from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from subsets_chat.db import ChatStore, NotFoundError, ValidationError


class CreateUserRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class ReplaceSetRequest(BaseModel):
    followed_user_ids: list[int] = Field(default_factory=list)


class CreateMessageRequest(BaseModel):
    author_user_id: int
    body: str = Field(min_length=1, max_length=4000)
    reply_to_message_id: int | None = None


class ConnectionManager:
    def __init__(self, store: ChatStore):
        self.store = store
        self.connections: list[tuple[int, WebSocket]] = []

    async def connect(self, viewer_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append((viewer_id, websocket))

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections = [
            (viewer_id, connection)
            for viewer_id, connection in self.connections
            if connection is not websocket
        ]

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


def create_app(database_path: str | Path | None = None) -> FastAPI:
    resolved_database_path: str | Path = (
        database_path
        if database_path is not None
        else os.getenv("SUBSETS_CHAT_DB", "subsets.db")
    )
    store = ChatStore(resolved_database_path)
    manager = ConnectionManager(store)

    app = FastAPI(
        title="Subsets Chat",
        summary="Constructive personal-set chat feed backend.",
        version="0.1.0",
    )
    app.state.store = store
    app.state.connection_manager = manager

    def get_store() -> ChatStore:
        return store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/users")
    def list_users(chat_store: ChatStore = Depends(get_store)) -> list[dict]:
        return chat_store.list_users()

    @app.post("/users", status_code=201)
    def create_user(
        request: CreateUserRequest,
        chat_store: ChatStore = Depends(get_store),
    ) -> dict:
        try:
            return chat_store.create_user(request.display_name)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/users/{user_id}/set")
    def get_follow_set(
        user_id: int,
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict]:
        try:
            return chat_store.get_follow_set(user_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/users/{user_id}/set")
    def replace_follow_set(
        user_id: int,
        request: ReplaceSetRequest,
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict]:
        try:
            return chat_store.replace_follow_set(user_id, request.followed_user_ids)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/messages", status_code=201)
    async def create_message(
        request: CreateMessageRequest,
        chat_store: ChatStore = Depends(get_store),
    ) -> dict:
        try:
            message = chat_store.create_message(
                author_user_id=request.author_user_id,
                body=request.body,
                reply_to_message_id=request.reply_to_message_id,
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await manager.broadcast_message(message["id"])
        return message

    @app.get("/feed")
    def get_feed(
        viewer_id: int = Query(gt=0),
        chat_store: ChatStore = Depends(get_store),
    ) -> list[dict]:
        try:
            return chat_store.get_feed(viewer_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.websocket("/ws")
    async def websocket_feed(
        websocket: WebSocket,
        viewer_id: int = Query(gt=0),
    ) -> None:
        try:
            store.ensure_user_exists(viewer_id)
        except NotFoundError:
            await websocket.close(code=1008)
            return

        await manager.connect(viewer_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app


app = create_app()
