from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from delamain_backend.db.migrations import MIGRATIONS

SQLITE_BUSY_TIMEOUT_MS = 5000


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await self._connect_one()
        await self._configure_connection(self._conn, verify_wal=True)
        self._read_conn = await self._connect_one()
        await self._configure_connection(self._read_conn, verify_wal=True)

    async def close(self) -> None:
        if self._read_conn is not None:
            await self._read_conn.close()
            self._read_conn = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    @property
    def read_conn(self) -> aiosqlite.Connection:
        if self._read_conn is None:
            raise RuntimeError("Database is not connected")
        return self._read_conn

    async def _connect_one(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = aiosqlite.Row
        return conn

    async def _configure_connection(
        self, conn: aiosqlite.Connection, *, verify_wal: bool
    ) -> None:
        journal_mode = await self._fetch_pragma_value(conn, "journal_mode", "WAL")
        await conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        await conn.execute("PRAGMA synchronous = NORMAL")
        await conn.execute("PRAGMA temp_store = MEMORY")
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.commit()
        if verify_wal and str(journal_mode).lower() != "wal":
            raise RuntimeError(
                f"SQLite database {self.path} did not enter WAL mode; got {journal_mode!r}"
            )

    async def _fetch_pragma_value(
        self,
        conn: aiosqlite.Connection,
        name: str,
        value: str | int | None = None,
    ) -> Any:
        sql = f"PRAGMA {name}" if value is None else f"PRAGMA {name} = {value}"
        async with conn.execute(sql) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

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
        async with self.read_conn.execute(sql, tuple(params)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        async with self.read_conn.execute(sql, tuple(params)) as cursor:
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
        async with self.read_conn.execute("SELECT 1 AS ok") as cursor:
            row = await cursor.fetchone()
        return bool(row and int(row["ok"]) == 1)

    async def health_report(self) -> dict[str, Any]:
        write = await self._connection_pragmas(self.conn)
        read = await self._connection_pragmas(self.read_conn)
        return {
            "ok": await self.healthcheck(),
            "path": str(self.path),
            "wal_verified": write["journal_mode"] == "wal"
            and read["journal_mode"] == "wal",
            "write": write,
            "read": read,
        }

    async def _connection_pragmas(self, conn: aiosqlite.Connection) -> dict[str, Any]:
        return {
            "journal_mode": str(await self._fetch_pragma_value(conn, "journal_mode")).lower(),
            "busy_timeout_ms": int(await self._fetch_pragma_value(conn, "busy_timeout")),
            "synchronous": int(await self._fetch_pragma_value(conn, "synchronous")),
            "temp_store": int(await self._fetch_pragma_value(conn, "temp_store")),
            "foreign_keys": bool(await self._fetch_pragma_value(conn, "foreign_keys")),
        }


def event_row_to_envelope(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "conversation_id": row["conversation_id"],
        "run_id": row["run_id"],
        "type": row["type"],
        "created_at": row["created_at"],
        "payload": json.loads(row["payload"]),
    }
