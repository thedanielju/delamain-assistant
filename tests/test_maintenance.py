from __future__ import annotations

import os
import time
from dataclasses import replace

from delamain_backend.config import MaintenanceConfig
from delamain_backend.maintenance import run_startup_cleanup


def test_startup_cleanup_removes_old_artifacts_and_backups(test_config):
    config = replace(
        test_config,
        maintenance=MaintenanceConfig(
            action_output_retention_days=7,
            context_backup_retention_days=7,
        ),
    )
    action_old = config.database.path.parent / "action-outputs" / "old"
    action_new = config.database.path.parent / "action-outputs" / "new"
    backup_old = config.database.path.parent / "context-backups" / "system-context" / "old.bak"
    backup_new = config.database.path.parent / "context-backups" / "system-context" / "new.bak"
    for path in (action_old, action_new):
        path.mkdir(parents=True)
        (path / "stdout.txt").write_text("x", encoding="utf-8")
    for path in (backup_old, backup_new):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    old_time = time.time() - 10 * 24 * 60 * 60
    os.utime(action_old, (old_time, old_time))
    os.utime(backup_old, (old_time, old_time))

    result = run_startup_cleanup(config)

    assert result["action_outputs_removed"] == 1
    assert result["context_backups_removed"] == 1
    assert not action_old.exists()
    assert action_new.exists()
    assert not backup_old.exists()
    assert backup_new.exists()
