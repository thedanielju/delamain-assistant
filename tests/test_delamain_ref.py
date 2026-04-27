from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from delamain_ref.converters import ConversionResult
from delamain_ref.index_md import rebuild_category_index
from delamain_ref.ingest import ensure_bundle, set_pin_state
from delamain_ref.lifecycle import move_inactive_to_long_term
from delamain_ref.manifest import BundleRecord, CategoryManifest, load_manifest, replace_bundle, save_manifest
from delamain_ref.paths import discover_runtime_paths
from delamain_ref.reconcile import reconcile
from delamain_ref.util import resolve_collision, slugify_bundle_id, utc_now_iso
from delamain_ref.vault_index import (
    _read_frontmatter_prescan,
    build_vault_index,
    init_vault_folder,
    vault_index_heartbeat,
)
import delamain_ref.paths as paths_mod
import delamain_ref.ingest as ingest_mod


def _make_runtime(tmp_path: Path):
    workspace = tmp_path / "llm-workspace"
    vault = tmp_path / "Vault"
    for rel in ["syllabi", "reference", "reference/_long-term", "syllabi/_long-term", "vault-index"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    vault.mkdir(parents=True, exist_ok=True)
    return discover_runtime_paths(workspace_root=workspace, vault_root=vault)


def _stub_conversion(*_args, **_kwargs):
    return ConversionResult(
        ok=True,
        status="fresh",
        converter="stub",
        markdown="# Converted\n\nHello world.\n",
        warnings=[],
        extraction_report={"kind": "stub"},
    )


def test_path_discovery_candidate_includes_windows_wsl_ubuntu():
    candidates = [str(path).replace("\\", "/") for path in paths_mod._iter_workspace_candidates()]
    assert any("C:/Users/Daniel/llm-workspace" in item for item in candidates)
    assert any("/mnt/c/Users/Daniel/llm-workspace" in item for item in candidates)
    assert any("/home/danielju/llm-workspace" in item for item in candidates)


def test_bundle_id_sanitization_and_collision():
    base = slugify_bundle_id("CSCI 3401 SP26 syllabus (rev0)")
    assert base == "csci-3401-sp26-syllabus-rev0"
    resolved = resolve_collision(base, "stable-key", {base})
    assert resolved.startswith(base + "-")
    assert resolved != base


def test_manifest_read_write_and_rebuild_index(tmp_path: Path):
    runtime = _make_runtime(tmp_path)
    now = utc_now_iso()
    manifest = CategoryManifest.empty("reference")
    bundle = BundleRecord(
        id="sample-doc",
        title="Sample Doc",
        category="reference",
        bundle_path="reference/sample-doc",
        source_path="reference/sample-doc/original/sample.docx",
        source_sha256="abc",
        source_mtime=now,
        document_md="reference/sample-doc/document.md",
        figures_path="reference/sample-doc/figures",
        converter="stub",
        status="fresh",
        placement="normal",
        pinned=False,
        first_seen_at=now,
        last_processed_at=now,
        last_accessed_at=now,
        warnings=[],
    )
    replace_bundle(manifest, bundle)
    save_manifest(runtime, manifest)
    loaded = load_manifest(runtime, "reference")
    assert len(loaded.bundles) == 1
    index_path = rebuild_category_index(runtime, loaded)
    content = (runtime.workspace_root / index_path).read_text(encoding="utf-8")
    assert "sample-doc" in content


def test_ensure_idempotent_pin_unpin_and_long_term(tmp_path: Path, monkeypatch):
    runtime = _make_runtime(tmp_path)
    monkeypatch.setattr(ingest_mod, "convert_rich_document", _stub_conversion)
    source = runtime.syllabi_root / "My Syllabus.rtf"
    source.write_text(r"{\rtf1\ansi Test}", encoding="utf-8")

    first = ensure_bundle(runtime, str(source), category="syllabi")
    assert first["ok"] is True
    assert all(not Path(path).is_absolute() for path in first["changed_paths"])
    bundle_id = first["bundle"]["id"]
    second = ensure_bundle(runtime, bundle_id, category="syllabi")
    assert second["ok"] is True
    assert second["changed_paths"] == []

    pin_result = set_pin_state(runtime, bundle_id, pinned=True, category="syllabi")
    assert pin_result["bundle"]["pinned"] is True
    unpin_result = set_pin_state(runtime, bundle_id, pinned=False, category="syllabi")
    assert unpin_result["bundle"]["pinned"] is False

    manifest = load_manifest(runtime, "syllabi")
    bundle = manifest.bundles[0]
    bundle.last_accessed_at = "2000-01-01T00:00:00+00:00"
    save_manifest(runtime, manifest)
    move = move_inactive_to_long_term(runtime, days=30, category="syllabi")
    assert move["ok"] is True
    refreshed = load_manifest(runtime, "syllabi")
    assert refreshed.bundles[0].placement == "long-term"


def test_reconcile_manual_move_and_manual_delete(tmp_path: Path, monkeypatch):
    runtime = _make_runtime(tmp_path)
    monkeypatch.setattr(ingest_mod, "convert_rich_document", _stub_conversion)
    source = runtime.reference_root / "Ref Doc.rtf"
    source.write_text(r"{\rtf1\ansi Ref}", encoding="utf-8")
    ensured = ensure_bundle(runtime, str(source), category="reference")
    bundle_id = ensured["bundle"]["id"]
    manifest = load_manifest(runtime, "reference")
    bundle = manifest.bundles[0]
    src = runtime.workspace_root / bundle.bundle_path
    dst = runtime.reference_root / "_long-term" / bundle.id
    shutil.move(str(src), str(dst))

    moved = reconcile(runtime, category="reference")
    assert moved["ok"] is True
    updated = load_manifest(runtime, "reference")
    assert updated.bundles[0].placement == "long-term"

    shutil.rmtree(runtime.workspace_root / updated.bundles[0].bundle_path)
    deleted = reconcile(runtime, category="reference")
    assert deleted["ok"] is True
    after_delete = load_manifest(runtime, "reference")
    assert all(item.id != bundle_id for item in after_delete.bundles)


def test_vault_index_parsing_features(tmp_path: Path):
    runtime = _make_runtime(tmp_path)
    (runtime.vault_root / "Notes").mkdir(parents=True, exist_ok=True)
    (runtime.vault_root / "Projects" / "DELAMAIN" / "design").mkdir(
        parents=True, exist_ok=True
    )
    (runtime.vault_root / ".stversions").mkdir(parents=True, exist_ok=True)
    (runtime.vault_root / ".stversions" / "Old.md").write_text(
        "# Old\n[[Missing Versioned Link]]\n",
        encoding="utf-8",
    )
    (runtime.vault_root / "Timeline.md").write_text(
        "---\n"
        "aliases: [Roadmap]\n"
        "tags: [home]\n"
        "---\n"
        "# Timeline\n",
        encoding="utf-8",
    )
    (runtime.vault_root / "Projects" / "DELAMAIN" / "design" / "master-plan.md").write_text(
        "# Master Plan\n",
        encoding="utf-8",
    )
    (runtime.vault_root / "Notes" / "a.md").write_text(
        "# A\n"
        "See [[Timeline|main]], [[design/master-plan]], and [[Missing Note]].\n"
        "Inline tag #project\n"
        "[B](b.md)\n",
        encoding="utf-8",
    )
    (runtime.vault_root / "Notes" / "b.md").write_text(
        "# B\n"
        "Backlink to [[a]].\n",
        encoding="utf-8",
    )
    result = build_vault_index(runtime)
    assert result["ok"] is True

    backlinks = json.loads((runtime.vault_index_root / "backlinks.json").read_text(encoding="utf-8"))
    assert "Timeline.md" in backlinks
    assert "Notes/a.md" in backlinks["Timeline.md"]
    assert "Projects/DELAMAIN/design/master-plan.md" in backlinks
    assert "Notes/a.md" in backlinks["Projects/DELAMAIN/design/master-plan.md"]

    tags = json.loads((runtime.vault_index_root / "tags.json").read_text(encoding="utf-8"))
    tag_names = {row["tag"] for row in tags["tags"]}
    assert {"home", "project"} <= tag_names
    dangling = (runtime.vault_index_root / "dangling-links.md").read_text(encoding="utf-8")
    assert "Missing Note" in dangling
    assert "design/master-plan" not in dangling
    assert "Missing Versioned Link" not in dangling
    root_notes = (runtime.vault_index_root / "root-notes.md").read_text(encoding="utf-8")
    assert "Timeline.md" in root_notes


def test_frontmatter_prescan_reads_only_bounded_yaml(tmp_path: Path):
    note = tmp_path / "private.md"
    note.write_bytes(
        b"---\n"
        b"sensitivity: private\n"
        b"aliases: [Secret Alias]\n"
        b"...\n"
        b"\xff\xfeBODY WOULD FAIL FULL UTF-8 READ\n"
    )

    frontmatter = _read_frontmatter_prescan(note)

    assert frontmatter["sensitivity"] == "private"
    assert frontmatter["aliases"] == ["Secret Alias"]


def test_vault_index_frontmatter_sensitivity_skips_before_body_and_suppresses_links(tmp_path: Path):
    runtime = _make_runtime(tmp_path)
    (runtime.vault_root / "Notes").mkdir(parents=True, exist_ok=True)
    (runtime.vault_root / "Private").mkdir(parents=True, exist_ok=True)
    (runtime.vault_root / "Notes" / "visible.md").write_text(
        "# Visible\n\nSee [[Secret Alias]], [[Private/private-note]], and [[Missing Note]].\n",
        encoding="utf-8",
    )
    (runtime.vault_root / "Private" / "private-note.md").write_bytes(
        b"---\n"
        b"sensitivity: private\n"
        b"aliases: [Secret Alias]\n"
        b"tags: [never/leak]\n"
        b"---\n"
        b"\xff\xfePRIVATE_UNIQUE_BODY_SHOULD_NOT_BE_READ\n"
    )
    (runtime.vault_root / "Private" / "sensitive-note.md").write_bytes(
        b"---\n"
        b"sensitivity: sensitive\n"
        b"---\n"
        b"\xff\xfeSENSITIVE_UNIQUE_BODY_SHOULD_NOT_BE_READ\n"
    )

    result = build_vault_index(runtime)

    assert result["ok"] is True
    graph_text = (runtime.vault_index_root / "graph.json").read_text(encoding="utf-8")
    dangling = (runtime.vault_index_root / "dangling-links.md").read_text(encoding="utf-8")
    manifest = json.loads((runtime.vault_index_root / "_manifest.json").read_text(encoding="utf-8"))
    assert "Notes/visible.md" in graph_text
    assert "Private/private-note.md" not in graph_text
    assert "Private/sensitive-note.md" not in graph_text
    assert "Secret Alias" not in graph_text
    assert "never/leak" not in graph_text
    assert "PRIVATE_UNIQUE_BODY_SHOULD_NOT_BE_READ" not in graph_text
    assert "SENSITIVE_UNIQUE_BODY_SHOULD_NOT_BE_READ" not in graph_text
    assert "Missing Note" in dangling
    assert "Secret Alias" not in dangling
    assert "Private/private-note" not in dangling
    assert any(item["reason"] == "frontmatter:private" and item.get("path") is None for item in manifest["skipped_paths"])
    assert any(item["reason"] == "frontmatter:sensitive" and item.get("path") is None for item in manifest["skipped_paths"])


def test_unified_vault_index_includes_workspace_bundles_and_policy_skips(tmp_path: Path, monkeypatch):
    runtime = _make_runtime(tmp_path)
    monkeypatch.setattr(ingest_mod, "convert_rich_document", _stub_conversion)
    (runtime.vault_root / "vault_policy.md").write_text("## Ignore Globs\n\n- `Secret/**`\n", encoding="utf-8")
    (runtime.vault_root / "Visible.md").write_text("# Visible\n\nSee [[Converted]].\n", encoding="utf-8")
    (runtime.vault_root / "Secret").mkdir()
    (runtime.vault_root / "Secret" / "hidden.md").write_text("# Hidden\n", encoding="utf-8")
    source = runtime.reference_root / "API Docs.rtf"
    source.write_text(r"{\rtf1\ansi API}", encoding="utf-8")
    ensured = ensure_bundle(runtime, str(source), category="reference")
    assert ensured["ok"] is True

    result = build_vault_index(runtime)
    assert result["ok"] is True
    manifest = json.loads((runtime.vault_index_root / "_manifest.json").read_text(encoding="utf-8"))
    graph = json.loads((runtime.vault_index_root / "graph.json").read_text(encoding="utf-8"))
    source_types = {node["source_type"] for node in graph["nodes"]}
    paths = {node["path"] for node in graph["nodes"]}

    assert manifest["schema_version"] == 2
    assert manifest["workspace_bundle_count"] == 1
    assert manifest["skipped_count"] == 1
    assert {"vault_note", "workspace_reference"} <= source_types
    assert "Visible.md" in paths
    assert "Secret/hidden.md" not in paths
    assert any(node["document_md"].endswith("document.md") for node in graph["nodes"] if node["source_type"] == "workspace_reference")


def test_vault_policy_markdown_only_contributes_ignore_globs(tmp_path: Path):
    runtime = _make_runtime(tmp_path)
    (runtime.vault_root / "vault_policy.md").write_text(
        "\n".join(
            [
                "---",
                "tags: [vault, policy]",
                "---",
                "",
                "# Vault Policy",
                "",
                "- Never send the whole vault.",
                "- Index converted `document.md`, not raw files.",
                "- project/delamain",
                "",
                "## Ignore Globs",
                "",
                "```gitignore",
                ".obsidian/**",
                "*.tmp",
                "```",
                "",
                "- `Secret/**`",
                "",
                "## Taxonomy",
                "",
                "- `project/delamain`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (runtime.vault_root / "Visible.md").write_text("# Visible\n", encoding="utf-8")
    (runtime.vault_root / "Secret").mkdir()
    (runtime.vault_root / "Secret" / "hidden.md").write_text("# Hidden\n", encoding="utf-8")

    result = build_vault_index(runtime)
    assert result["ok"] is True
    graph = json.loads((runtime.vault_index_root / "graph.json").read_text(encoding="utf-8"))
    paths = {node["path"] for node in graph["nodes"]}

    assert "Visible.md" in paths
    assert "Secret/hidden.md" not in paths
    assert result["summary"]["skipped_count"] == 1


def test_init_folder_creates_templates_and_rebuilds_index(tmp_path: Path):
    runtime = _make_runtime(tmp_path)
    result = init_vault_folder(runtime, kind="project", name="Graph Demo")

    assert result["ok"] is True
    assert (runtime.vault_root / "Projects" / "Graph Demo" / "INDEX.md").exists()
    assert (runtime.vault_root / "Projects" / "Graph Demo" / "state.md").exists()
    assert (runtime.reference_root / "graph-demo" / "original").exists()
    graph = json.loads((runtime.vault_index_root / "graph.json").read_text(encoding="utf-8"))
    assert any(node["path"] == "Projects/Graph Demo/INDEX.md" for node in graph["nodes"])


def test_vault_index_heartbeat_auto_ingests_supported_documents(tmp_path: Path, monkeypatch):
    runtime = _make_runtime(tmp_path)
    monkeypatch.setattr(ingest_mod, "convert_rich_document", _stub_conversion)
    source = runtime.syllabi_root / "Course Syllabus.rtf"
    source.write_text(r"{\rtf1\ansi Course}", encoding="utf-8")

    result = vault_index_heartbeat(runtime)

    assert result["ok"] is True
    assert "Course Syllabus.rtf" in result["summary"].get("auto_ingest", {}).get("ingested", []) or result["summary"]["workspace_bundle_count"] == 1
    assert (runtime.vault_index_root / "_heartbeat.json").exists()
    graph = json.loads((runtime.vault_index_root / "graph.json").read_text(encoding="utf-8"))
    assert any(node["source_type"] == "workspace_syllabus" for node in graph["nodes"])


def test_cli_json_output_mode(tmp_path: Path):
    runtime = _make_runtime(tmp_path)
    cli = Path(__file__).resolve().parents[1] / "delamain_ref" / "cli.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--workspace",
            str(runtime.workspace_root),
            "--vault",
            str(runtime.vault_root),
            "ref",
            "status",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "status"
