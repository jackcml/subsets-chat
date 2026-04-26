from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS follows (
    viewer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followed_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (viewer_user_id, followed_user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    reply_to_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


class NotFoundError(ValueError):
    """Raised when a requested local record does not exist."""


class ValidationError(ValueError):
    """Raised when a request is structurally valid but violates chat rules."""


class ChatStore:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)

    def list_users(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT id, display_name, created_at FROM users ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_user(self, display_name: str) -> dict[str, Any]:
        normalized = display_name.strip()
        if not normalized:
            raise ValidationError("display_name must not be empty")

        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO users (display_name) VALUES (?)",
                (normalized,),
            )
            user_id = cursor.lastrowid
            if user_id is None:
                raise NotFoundError("created user id could not be loaded")
            row = conn.execute(
                "SELECT id, display_name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("created user could not be loaded")
        return dict(row)

    def ensure_user_exists(self, user_id: int) -> None:
        with self.session() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"user {user_id} does not exist")

    def get_follow_set(self, viewer_user_id: int) -> list[dict[str, Any]]:
        self.ensure_user_exists(viewer_user_id)
        with self.session() as conn:
            rows = conn.execute(
                """
                SELECT users.id, users.display_name, users.created_at
                FROM follows
                JOIN users ON users.id = follows.followed_user_id
                WHERE follows.viewer_user_id = ?
                ORDER BY users.display_name COLLATE NOCASE, users.id
                """,
                (viewer_user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_follow_set(
        self, viewer_user_id: int, followed_user_ids: Iterable[int]
    ) -> list[dict[str, Any]]:
        self.ensure_user_exists(viewer_user_id)
        normalized_ids = sorted(set(followed_user_ids))
        if any(user_id <= 0 for user_id in normalized_ids):
            raise ValidationError("followed_user_ids must contain positive user ids")

        with self.session() as conn:
            if normalized_ids:
                placeholders = ",".join("?" for _ in normalized_ids)
                rows = conn.execute(
                    f"SELECT id FROM users WHERE id IN ({placeholders})",
                    normalized_ids,
                ).fetchall()
                existing_ids = {row["id"] for row in rows}
                missing_ids = sorted(set(normalized_ids) - existing_ids)
                if missing_ids:
                    raise NotFoundError(
                        "followed user ids do not exist: "
                        + ", ".join(str(user_id) for user_id in missing_ids)
                    )

            conn.execute("BEGIN")
            try:
                conn.execute(
                    "DELETE FROM follows WHERE viewer_user_id = ?",
                    (viewer_user_id,),
                )
                conn.executemany(
                    """
                    INSERT INTO follows (viewer_user_id, followed_user_id)
                    VALUES (?, ?)
                    """,
                    [(viewer_user_id, followed_id) for followed_id in normalized_ids],
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        return self.get_follow_set(viewer_user_id)

    def create_message(
        self,
        author_user_id: int,
        body: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_user_exists(author_user_id)
        normalized_body = body.strip()
        if not normalized_body:
            raise ValidationError("body must not be empty")
        if reply_to_message_id is not None:
            self.get_message(reply_to_message_id)

        with self.session() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (author_user_id, body, reply_to_message_id)
                VALUES (?, ?, ?)
                """,
                (author_user_id, normalized_body, reply_to_message_id),
            )
            message_id = cursor.lastrowid
            if message_id is None:
                raise NotFoundError("created message id could not be loaded")
            row = self._fetch_message_row(conn, message_id)
        if row is None:
            raise NotFoundError("created message could not be loaded")
        return dict(row)

    def get_message(self, message_id: int) -> dict[str, Any]:
        with self.session() as conn:
            row = self._fetch_message_row(conn, message_id)
        if row is None:
            raise NotFoundError(f"message {message_id} does not exist")
        return dict(row)

    def get_feed(self, viewer_user_id: int) -> list[dict[str, Any]]:
        self.ensure_user_exists(viewer_user_id)
        with self.session() as conn:
            rows = conn.execute(
                """
                WITH RECURSIVE visible_authors(user_id) AS (
                    SELECT ? AS user_id
                    UNION
                    SELECT followed_user_id
                    FROM follows
                    WHERE viewer_user_id = ?
                ),
                visible_messages(id) AS (
                    SELECT id
                    FROM messages
                    WHERE reply_to_message_id IS NULL
                      AND author_user_id IN (SELECT user_id FROM visible_authors)

                    UNION

                    SELECT child.id
                    FROM messages AS child
                    JOIN visible_messages AS parent_visible
                        ON parent_visible.id = child.reply_to_message_id
                    WHERE child.author_user_id IN (SELECT user_id FROM visible_authors)
                )
                SELECT
                    messages.id,
                    messages.author_user_id,
                    author.display_name AS author_display_name,
                    messages.body,
                    messages.reply_to_message_id,
                    messages.created_at,
                    parent.id AS parent_id,
                    parent.author_user_id AS parent_author_user_id,
                    parent_author.display_name AS parent_author_display_name,
                    parent.body AS parent_body,
                    parent.created_at AS parent_created_at
                FROM visible_messages
                JOIN messages ON messages.id = visible_messages.id
                JOIN users AS author ON author.id = messages.author_user_id
                LEFT JOIN messages AS parent ON parent.id = messages.reply_to_message_id
                LEFT JOIN users AS parent_author ON parent_author.id = parent.author_user_id
                ORDER BY messages.created_at, messages.id
                """,
                (viewer_user_id, viewer_user_id),
            ).fetchall()
        return [self._row_to_feed_message(row) for row in rows]

    def message_visible_to(self, viewer_user_id: int, message_id: int) -> dict[str, Any] | None:
        self.ensure_user_exists(viewer_user_id)
        with self.session() as conn:
            row = conn.execute(
                """
                WITH RECURSIVE visible_authors(user_id) AS (
                    SELECT ? AS user_id
                    UNION
                    SELECT followed_user_id
                    FROM follows
                    WHERE viewer_user_id = ?
                ),
                visible_messages(id) AS (
                    SELECT id
                    FROM messages
                    WHERE reply_to_message_id IS NULL
                      AND author_user_id IN (SELECT user_id FROM visible_authors)

                    UNION

                    SELECT child.id
                    FROM messages AS child
                    JOIN visible_messages AS parent_visible
                        ON parent_visible.id = child.reply_to_message_id
                    WHERE child.author_user_id IN (SELECT user_id FROM visible_authors)
                )
                SELECT
                    messages.id,
                    messages.author_user_id,
                    author.display_name AS author_display_name,
                    messages.body,
                    messages.reply_to_message_id,
                    messages.created_at,
                    parent.id AS parent_id,
                    parent.author_user_id AS parent_author_user_id,
                    parent_author.display_name AS parent_author_display_name,
                    parent.body AS parent_body,
                    parent.created_at AS parent_created_at
                FROM visible_messages
                JOIN messages ON messages.id = visible_messages.id
                JOIN users AS author ON author.id = messages.author_user_id
                LEFT JOIN messages AS parent ON parent.id = messages.reply_to_message_id
                LEFT JOIN users AS parent_author ON parent_author.id = parent.author_user_id
                WHERE messages.id = ?
                """,
                (viewer_user_id, viewer_user_id, message_id),
            ).fetchone()
        return self._row_to_feed_message(row) if row else None

    def _fetch_message_row(
        self, conn: sqlite3.Connection, message_id: int
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT
                messages.id,
                messages.author_user_id,
                author.display_name AS author_display_name,
                messages.body,
                messages.reply_to_message_id,
                messages.created_at
            FROM messages
            JOIN users AS author ON author.id = messages.author_user_id
            WHERE messages.id = ?
            """,
            (message_id,),
        ).fetchone()

    def _row_to_feed_message(self, row: sqlite3.Row) -> dict[str, Any]:
        message = {
            "id": row["id"],
            "author_user_id": row["author_user_id"],
            "author_display_name": row["author_display_name"],
            "body": row["body"],
            "reply_to_message_id": row["reply_to_message_id"],
            "created_at": row["created_at"],
            "reply_to": None,
        }
        if row["parent_id"] is not None:
            message["reply_to"] = {
                "id": row["parent_id"],
                "author_user_id": row["parent_author_user_id"],
                "author_display_name": row["parent_author_display_name"],
                "body": row["parent_body"],
                "created_at": row["parent_created_at"],
            }
        return message
