from __future__ import annotations

from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.syncthing_status import syncthing_conflicts


def vault_sync_conflict_paths(config: AppConfig) -> set[str]:
    try:
        conflicts = syncthing_conflicts(config).get("conflicts", [])
    except Exception:
        return set()
    paths: set[str] = set()
    for item in conflicts if isinstance(conflicts, list) else []:
        if not isinstance(item, dict):
            continue
        for key in ("path", "canonical_path"):
            raw = item.get(key)
            if not isinstance(raw, str) or not raw:
                continue
            paths.update(_relative_aliases(config, raw))
    return paths


def apply_staleness_metadata(node: dict[str, Any], conflict_paths: set[str]) -> dict[str, Any]:
    path = str(node.get("path") or "")
    reasons: list[str] = []
    score = 0.0

    if path in conflict_paths:
        score += 0.7
        reasons.append("sync_conflict")
        node["sync_status"] = "conflicted"
    else:
        node["sync_status"] = "ok"

    generated_state = str(node.get("generated_metadata_state") or "missing")
    if generated_state == "stale":
        score += 0.35
        reasons.append("source_changed_since_enrichment")
    elif generated_state == "missing":
        score += 0.08
        reasons.append("missing_generated_metadata")

    status = str(node.get("status") or "").lower()
    if status in {"failed", "needs_ocr", "needs_reprocess", "conflicted"}:
        score += 0.55
        reasons.append(f"bundle_status:{status}")

    if node.get("warnings"):
        score += 0.2
        reasons.append("index_warnings")

    dangling = node.get("dangling_link_count")
    if isinstance(dangling, int) and dangling > 0:
        score += min(0.15, dangling * 0.03)
        reasons.append("dangling_links")

    if str(node.get("archive_state") or "").lower() in {"archive", "archived", "long-term"}:
        score += 0.05
        reasons.append("archived_or_long_term")

    stale_labels = node.get("stale_labels") if isinstance(node.get("stale_labels"), list) else []
    if stale_labels:
        score += 0.18
        reasons.append("generated_stale_label")

    score = round(min(score, 1.0), 3)
    node["stale_score"] = score
    node["stale_reasons"] = list(dict.fromkeys(reasons))
    if "sync_conflict" in reasons:
        node["staleness_status"] = "conflicted"
    elif score >= 0.45:
        node["staleness_status"] = "stale"
    elif score >= 0.18:
        node["staleness_status"] = "needs_review"
    else:
        node["staleness_status"] = "fresh"
    return node


def _relative_aliases(config: AppConfig, raw_path: str) -> set[str]:
    aliases = {raw_path.replace("\\", "/")}
    path = Path(raw_path).expanduser().resolve(strict=False)
    for root in (config.paths.vault, config.paths.llm_workspace):
        try:
            aliases.add(path.relative_to(root.expanduser().resolve(strict=False)).as_posix())
        except ValueError:
            continue
    return {alias for alias in aliases if alias}
