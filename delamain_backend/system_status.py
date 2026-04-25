from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import time
from typing import Any

import psutil

from delamain_backend.db import Database

STATUS_TTL_SECONDS = 60.0
_BYTES_PER_MB = 1024 * 1024
_CACHE: tuple[float, dict[str, Any]] | None = None
_PROCESS_CPU_SAMPLE: tuple[float, float] | None = None


async def system_status(db: Database, *, force_refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not force_refresh and _CACHE is not None and now - _CACHE[0] < _ttl_seconds():
        return _CACHE[1]

    payload = await _collect_system_status(db, now)
    globals()["_CACHE"] = (now, payload)
    return payload


async def _collect_system_status(db: Database, now_monotonic: float) -> dict[str, Any]:
    return {
        "delamain_backend": _backend_process_metrics(now_monotonic),
        "host": _host_metrics(),
        "tmux_workers": await _tmux_worker_metrics(db),
    }


def _backend_process_metrics(now_monotonic: float) -> dict[str, Any]:
    process = psutil.Process(os.getpid())
    create_time = process.create_time()
    cpu_times = process.cpu_times()
    cpu_total = float(cpu_times.user + cpu_times.system)
    uptime_seconds = max(0, int(time.time() - create_time))
    cpu_percent = _process_cpu_percent(now_monotonic, cpu_total, uptime_seconds)

    return {
        "uptime_seconds": uptime_seconds,
        "rss_mb": _mb(process.memory_info().rss),
        "cpu_percent_1min": round(cpu_percent, 2),
        "num_threads": process.num_threads(),
        "pid": process.pid,
    }


def _process_cpu_percent(
    now_monotonic: float,
    cpu_total_seconds: float,
    uptime_seconds: int,
) -> float:
    previous = _PROCESS_CPU_SAMPLE
    globals()["_PROCESS_CPU_SAMPLE"] = (now_monotonic, cpu_total_seconds)
    if previous is not None:
        elapsed = now_monotonic - previous[0]
        if elapsed > 0:
            return max(0.0, (cpu_total_seconds - previous[1]) / elapsed * 100.0)
    if uptime_seconds <= 0:
        return 0.0
    return max(0.0, cpu_total_seconds / uptime_seconds * 100.0)


def _host_metrics() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    load1, load5, load15 = _load_average()
    return {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "load_avg": {
            "one": load1,
            "five": load5,
            "fifteen": load15,
        },
        "memory_total_mb": _mb(memory.total),
        "memory_available_mb": _mb(memory.available),
        "disks": _disk_metrics(),
    }


def _load_average() -> tuple[float | None, float | None, float | None]:
    try:
        values = os.getloadavg()
    except (AttributeError, OSError):
        return (None, None, None)
    return tuple(round(float(value), 2) for value in values)


def _disk_metrics() -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    seen_mounts: set[str] = set()
    ignored_fstypes = {
        "",
        "autofs",
        "devfs",
        "proc",
        "procfs",
        "squashfs",
        "tmpfs",
    }
    for partition in psutil.disk_partitions(all=False):
        mountpoint = partition.mountpoint
        fstype = (partition.fstype or "").lower()
        if mountpoint in seen_mounts or fstype in ignored_fstypes:
            continue
        seen_mounts.add(mountpoint)
        try:
            usage = psutil.disk_usage(mountpoint)
        except OSError:
            continue
        if usage.total <= 0:
            continue
        disks.append(
            {
                "mountpoint": mountpoint,
                "device": partition.device,
                "fstype": partition.fstype,
                "total_mb": _mb(usage.total),
                "used_mb": _mb(usage.used),
                "free_mb": _mb(usage.free),
                "percent_used": round(float(usage.percent), 1),
            }
        )
    disks.sort(key=lambda item: item["mountpoint"])
    return disks


async def _tmux_worker_metrics(db: Database) -> dict[str, Any]:
    rows = await db.fetchall(
        """
        SELECT host, tmux_session, tmux_socket
        FROM workers
        WHERE status IN ('running', 'starting', 'stopping')
        ORDER BY created_at DESC
        """
    )
    count = 0
    rss_total_bytes = 0
    for row in rows:
        if row.get("host") == "winpc":
            continue
        pane_pid = await _pane_pid_for_session(
            row.get("tmux_session"),
            row.get("tmux_socket"),
        )
        if pane_pid is None:
            continue
        count += 1
        rss_total_bytes += _process_tree_rss_bytes(pane_pid)

    return {
        "count": count,
        "rss_mb_total": _mb(rss_total_bytes),
    }


async def _pane_pid_for_session(
    session_name: str | None,
    tmux_socket: str | None,
) -> int | None:
    if not session_name:
        return None
    tmux_bin = shutil.which("tmux")
    if not tmux_bin:
        return None

    argv = [tmux_bin]
    if tmux_socket:
        argv.extend(["-S", tmux_socket])
    argv.extend(["list-panes", "-t", session_name, "-F", "#{pane_pid}"])

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return None

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return None
    if proc.returncode != 0:
        return None

    for line in stdout.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _process_tree_rss_bytes(root_pid: int) -> int:
    try:
        root = psutil.Process(root_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0

    total = 0
    seen: set[int] = set()
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    for process in processes:
        if process.pid in seen:
            continue
        seen.add(process.pid)
        try:
            total += int(process.memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return total


def _mb(value: int | float) -> float:
    return round(float(value) / _BYTES_PER_MB, 1)


def _ttl_seconds() -> float:
    raw = os.environ.get("DELAMAIN_SYSTEM_STATUS_TTL_SECONDS")
    if not raw:
        return STATUS_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return STATUS_TTL_SECONDS
