from __future__ import annotations

import asyncio

import pytest

from delamain_backend.db import Database
from delamain_backend.db.database import SQLITE_BUSY_TIMEOUT_MS


@pytest.mark.asyncio
async def test_database_applies_wal_and_reliability_pragmas(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    try:
        report = await db.health_report()
    finally:
        await db.close()

    assert report["ok"] is True
    assert report["wal_verified"] is True
    for name in ("write", "read"):
        assert report[name]["journal_mode"] == "wal"
        assert report[name]["busy_timeout_ms"] == SQLITE_BUSY_TIMEOUT_MS
        assert report[name]["synchronous"] == 1
        assert report[name]["temp_store"] == 2
        assert report[name]["foreign_keys"] is True


@pytest.mark.asyncio
async def test_database_concurrent_writes_and_read_health_remain_usable(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    try:
        await db.execute(
            """
            CREATE TABLE reliability_items (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        async def write_item(index: int) -> None:
            await db.execute(
                "INSERT INTO reliability_items(value) VALUES (?)",
                (f"item-{index}",),
            )

        async def read_health() -> None:
            for _ in range(20):
                assert await db.healthcheck() is True
                rows = await db.fetchall("SELECT COUNT(*) AS count FROM reliability_items")
                assert rows[0]["count"] >= 0
                await asyncio.sleep(0)

        await asyncio.gather(
            *(write_item(index) for index in range(50)),
            *(read_health() for _ in range(5)),
        )

        row = await db.fetchone("SELECT COUNT(*) AS count FROM reliability_items")
    finally:
        await db.close()

    assert row == {"count": 50}
