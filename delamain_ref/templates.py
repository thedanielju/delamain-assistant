from __future__ import annotations

from collections import defaultdict

from .manifest import BundleRecord
from .util import utc_now_iso


def warning_block(warnings: list[str]) -> str:
    if not warnings:
        return ""
    lines = ["> [!warning] Extraction warnings"]
    for item in warnings:
        lines.append(f"> - {item}")
    return "\n".join(lines) + "\n\n"


def render_category_index(category: str, bundles: list[BundleRecord]) -> str:
    now = utc_now_iso()
    grouped: dict[str, list[BundleRecord]] = defaultdict(list)
    for bundle in sorted(bundles, key=lambda item: item.id):
        grouped[bundle.placement].append(bundle)

    lines: list[str] = [
        f"# {category.title()} Reference Index",
        "",
        f"Generated at: `{now}`",
        "",
    ]

    normal = grouped.get("normal", [])
    long_term = grouped.get("long-term", [])

    lines.extend(["## Active Bundles", ""])
    if not normal:
        lines.append("_No active bundles._")
        lines.append("")
    else:
        for bundle in normal:
            lines.extend(_bundle_lines(bundle))

    lines.extend(["## Long-Term Bundles", ""])
    if not long_term:
        lines.append("_No long-term bundles._")
        lines.append("")
    else:
        for bundle in long_term:
            lines.extend(_bundle_lines(bundle))

    return "\n".join(lines).rstrip() + "\n"


def _bundle_lines(bundle: BundleRecord) -> list[str]:
    warning_text = ", ".join(bundle.warnings) if bundle.warnings else "none"
    return [
        f"### `{bundle.id}`",
        f"- Title: {bundle.title}",
        f"- Status: `{bundle.status}`",
        f"- Placement: `{bundle.placement}`",
        f"- Pinned: `{str(bundle.pinned).lower()}`",
        f"- Last processed: `{bundle.last_processed_at}`",
        f"- Last accessed: `{bundle.last_accessed_at}`",
        f"- Converter: `{bundle.converter}`",
        f"- Warnings: {warning_text}",
        f"- Document: [{bundle.document_md}]({bundle.document_md})",
        f"- Metadata: [{bundle.bundle_path}/metadata.json]({bundle.bundle_path}/metadata.json)",
        f"- Source: [{bundle.source_path}]({bundle.source_path})",
        "",
    ]
