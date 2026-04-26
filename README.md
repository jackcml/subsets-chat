# Subsets Chat

Backend MVP for a constructive personal-set chat system. Messages are stored globally, but each viewer's feed is assembled from their own followed-user set.

## Run

```powershell
python -m uvicorn subsets_chat.app:app --reload
```

The service writes to `subsets.db` by default. Set `SUBSETS_CHAT_DB` to use a different SQLite path.

Open `http://127.0.0.1:8000/` for the single-page demo. It includes user creation, set editing, message compose/reply controls, and side-by-side feeds for every local user.

## API

- `GET /users`
- `POST /users` with `{ "display_name": "Alice" }`
- `GET /users/{user_id}/set`
- `PUT /users/{user_id}/set` with `{ "followed_user_ids": [1, 2] }`
- `POST /messages` with `{ "author_user_id": 1, "body": "hello", "reply_to_message_id": null }`
- `GET /feed?viewer_id=1`
- `WS /ws?viewer_id=1`

Feed visibility is computed at query time:

- A viewer sees authors in their set and always sees themselves.
- Replies are visible only when both the reply author and the parent author are visible to that viewer.
- WebSocket pushes use the same visibility rule as `GET /feed`.
