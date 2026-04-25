from __future__ import annotations

import pytest

from delamain_backend import system_status as system_status_module


@pytest.mark.asyncio
async def test_system_status_uses_cache(monkeypatch):
    monkeypatch.setattr(system_status_module, "_CACHE", None)
    monkeypatch.setattr(system_status_module, "_PROCESS_CPU_SAMPLE", None)
    monkeypatch.setattr(system_status_module, "_ttl_seconds", lambda: 60.0)

    values = iter((10.0, 20.0, 90.0))
    monkeypatch.setattr(
        system_status_module.time,
        "monotonic",
        lambda: next(values, 90.0),
    )

    calls = {"count": 0}

    async def fake_collect(db, now_monotonic):
        calls["count"] += 1
        return {"sample": calls["count"], "at": now_monotonic}

    monkeypatch.setattr(system_status_module, "_collect_system_status", fake_collect)

    first = await system_status_module.system_status(object())
    second = await system_status_module.system_status(object())
    third = await system_status_module.system_status(object())

    assert first == {"sample": 1, "at": 10.0}
    assert second == first
    assert third == {"sample": 2, "at": 90.0}


@pytest.mark.asyncio
async def test_tmux_worker_metrics_only_counts_local_sessions(monkeypatch):
    monkeypatch.setattr(system_status_module, "_CACHE", None)
    monkeypatch.setattr(system_status_module, "_PROCESS_CPU_SAMPLE", None)

    class DummyDb:
        async def fetchall(self, sql, params=()):
            del sql, params
            return [
                {
                    "host": "serrano",
                    "tmux_session": "dw-local",
                    "tmux_socket": "/tmp/workers.sock",
                },
                {
                    "host": "winpc",
                    "tmux_session": "dw-winpc",
                    "tmux_socket": "/tmp/workers.sock",
                },
            ]

    async def fake_pane_pid(session_name, tmux_socket):
        del tmux_socket
        return 4242 if session_name == "dw-local" else None

    monkeypatch.setattr(system_status_module, "_pane_pid_for_session", fake_pane_pid)
    monkeypatch.setattr(
        system_status_module,
        "_process_tree_rss_bytes",
        lambda pid: 150 * 1024 * 1024 if pid == 4242 else 0,
    )

    metrics = await system_status_module._tmux_worker_metrics(DummyDb())

    assert metrics == {"count": 1, "rss_mb_total": 150.0}
