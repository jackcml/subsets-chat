# Subsets Chat

Backend MVP for a constructive personal-set chat system. Messages are stored globally, but each viewer's feed is assembled from their own followed-user set.

## Run

```powershell
python -m uvicorn subsets_chat.app:app --reload
```

The service writes to `subsets.db` by default. Set `SUBSETS_CHAT_DB` to use a different SQLite path. Set `SUBSETS_CHAT_SECRET_KEY` outside local dev/test environments.

When the frontend is served from a different origin than FastAPI, opt in to CORS for that frontend origin:

```bash
SUBSETS_CHAT_ALLOWED_ORIGINS="http://localhost:5173"
```

Multiple allowed origins are comma-separated, for example
`SUBSETS_CHAT_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`.
If `SUBSETS_CHAT_ALLOWED_ORIGINS` is not set, browser cross-origin calls are not allowed by default.

## API

- `POST /auth/register` with `{ "username": "alice", "display_name": "Alice", "password": "secret" }`
- `POST /auth/token` with OAuth2 form fields `username` and `password`
- `GET /me`
- `GET /users`
- `GET /me/set`
- `PUT /me/set` with `{ "followed_user_ids": [1, 2] }`
- `POST /messages` with `{ "body": "hello", "reply_to_message_id": null }`
- `GET /feed`
- `WS /ws`, then send `{ "type": "auth", "access_token": "..." }`

Authenticated HTTP requests use `Authorization: Bearer <token>`.

Feed visibility is computed at query time:

- A viewer sees authors in their set and always sees themselves.
- Replies are visible only when the full reply chain is visible to that viewer.
- WebSocket pushes use the same visibility rule as `GET /feed`.
