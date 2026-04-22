from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from delamain_backend.db.migrations import MIGRATIONS


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def migrate(self) -> None:
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
        )
        async with self.conn.execute("SELECT version FROM schema_migrations") as cursor:
            applied = {int(row["version"]) async for row in cursor}
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            await self.conn.executescript(sql)
            await self.conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )
        await self.conn.commit()

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        async with self._write_lock:
            await self.conn.execute(sql, tuple(params))
            await self.conn.commit()

    async def execute_transaction(
        self, statements: Iterable[tuple[str, Iterable[Any]]]
    ) -> None:
        async with self._write_lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in statements:
                    await self.conn.execute(sql, tuple(params))
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        async with self.conn.execute(sql, tuple(params)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        async with self.conn.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def insert_event(
        self,
        *,
        conversation_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._write_lock:
            cursor = await self.conn.execute(
                """
                INSERT INTO events(conversation_id, run_id, type, payload)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, run_id, event_type, json.dumps(payload, sort_keys=True)),
            )
            await self.conn.commit()
            event_id = int(cursor.lastrowid)
            async with self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)) as row_cursor:
                row_data = await row_cursor.fetchone()
        row = dict(row_data) if row_data is not None else None
        assert row is not None
        return event_row_to_envelope(row)

    async def healthcheck(self) -> bool:
        async with self.conn.execute("SELECT 1 AS ok") as cursor:
            row = await cursor.fetchone()
        return bool(row and int(row["ok"]) == 1)


def event_row_to_envelope(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "conversation_id": row["conversation_id"],
        "run_id": row["run_id"],
        "type": row["type"],
        "created_at": row["created_at"],
        "payload": json.loads(row["payload"]),
    }
