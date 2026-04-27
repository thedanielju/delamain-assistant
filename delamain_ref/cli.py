from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delamain_ref.index_md import rebuild_category_index
from delamain_ref.ingest import (
    ensure_bundle,
    ensure_category_ready,
    list_category,
    open_bundle,
    reprocess_bundle,
    search_bundles,
    set_pin_state,
    status as ref_status,
)
from delamain_ref.lifecycle import move_inactive_to_long_term
from delamain_ref.manifest import load_manifest, save_manifest
from delamain_ref.paths import detect_runtime, discover_runtime_paths, ensure_base_layout
from delamain_ref.reconcile import reconcile
from delamain_ref.vault_index import (
    build_vault_index,
    init_vault_folder,
    vault_index_backlinks,
    vault_index_dangling,
    vault_index_heartbeat,
    vault_index_query,
    vault_index_root_notes,
    vault_index_status,
)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = discover_runtime_paths(workspace_root=args.workspace, vault_root=args.vault)
    ensure_base_layout(paths)
    if args.tool == "ref":
        _seed_manifests(paths)

    if args.tool == "ref":
        result = _run_ref_command(paths, args)
    else:
        result = _run_vault_command(paths, args)

    use_json = bool(getattr(args, "json", False))
    _emit(result, json_mode=use_json)
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delamain",
        description="Delamain deterministic ingestion and vault indexing tools.",
    )
    parser.add_argument("--workspace", help="Override llm-workspace root path.")
    parser.add_argument("--vault", help="Override Vault root path.")

    top = parser.add_subparsers(dest="tool", required=True)

    ref = top.add_parser("ref", help="Reference ingestion commands.")
    _build_ref_parser(ref)

    vault = top.add_parser("vault", help="Vault index commands.")
    _build_vault_parser(vault)

    return parser


def _build_ref_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)

    ensure = sub.add_parser("ensure")
    ensure.add_argument("target")
    ensure.add_argument("--category", choices=["syllabi", "reference"])
    ensure.add_argument("--json", action="store_true")
    ensure.add_argument("--dry-run", action="store_true")
    ensure.add_argument("--force", action="store_true")

    listing = sub.add_parser("list")
    listing.add_argument("category", nargs="?", choices=["syllabi", "reference"])
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--long-term", action="store_true")

    open_cmd = sub.add_parser("open")
    open_cmd.add_argument("doc_id")
    open_cmd.add_argument("--json", action="store_true")
    open_cmd.add_argument("--category", choices=["syllabi", "reference"])

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("category", nargs="?", choices=["syllabi", "reference"])
    search.add_argument("--json", action="store_true")

    reprocess = sub.add_parser("reprocess")
    reprocess.add_argument("doc_id")
    reprocess.add_argument("--json", action="store_true")
    reprocess.add_argument("--force", action="store_true")
    reprocess.add_argument("--category", choices=["syllabi", "reference"])

    pin = sub.add_parser("pin")
    pin.add_argument("doc_id")
    pin.add_argument("--json", action="store_true")
    pin.add_argument("--category", choices=["syllabi", "reference"])

    unpin = sub.add_parser("unpin")
    unpin.add_argument("doc_id")
    unpin.add_argument("--json", action="store_true")
    unpin.add_argument("--category", choices=["syllabi", "reference"])

    inactive = sub.add_parser("long-term-inactive")
    inactive.add_argument("--days", type=int, default=30)
    inactive.add_argument("--category", choices=["syllabi", "reference"])
    inactive.add_argument("--json", action="store_true")
    inactive.add_argument("--dry-run", action="store_true")

    reconcile_cmd = sub.add_parser("reconcile")
    reconcile_cmd.add_argument("category", nargs="?", choices=["syllabi", "reference"])
    reconcile_cmd.add_argument("--json", action="store_true")
    reconcile_cmd.add_argument("--dry-run", action="store_true")

    rebuild = sub.add_parser("rebuild-index")
    rebuild.add_argument("category", nargs="?", choices=["syllabi", "reference"])
    rebuild.add_argument("--json", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")


def _build_vault_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--auto-ingest", action="store_true")
    build.add_argument("--json", action="store_true")

    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--json", action="store_true")

    init_folder = sub.add_parser("init-folder")
    init_folder.add_argument("--kind", choices=["project", "course", "reference"], required=True)
    init_folder.add_argument("--name", required=True)
    init_folder.add_argument("--json", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")

    query = sub.add_parser("query")
    query.add_argument("term")
    query.add_argument("--json", action="store_true")

    backlinks = sub.add_parser("backlinks")
    backlinks.add_argument("note")
    backlinks.add_argument("--json", action="store_true")

    dangling = sub.add_parser("dangling")
    dangling.add_argument("--json", action="store_true")

    root = sub.add_parser("root-notes")
    root.add_argument("--json", action="store_true")


def _run_ref_command(paths, args) -> dict:
    cmd = args.command
    if cmd == "ensure":
        return ensure_bundle(
            paths,
            args.target,
            category=args.category,
            dry_run=args.dry_run,
            force=args.force,
        )
    if cmd == "list":
        categories = [args.category] if args.category else ["syllabi", "reference"]
        rows = []
        for category in categories:
            rows.extend(
                list_category(
                    paths,
                    category,
                    include_long_term=bool(args.long_term),
                    include_all=bool(args.all),
                )
            )
        return {
            "ok": True,
            "command": "list",
            "status": "ok",
            "warnings": [],
            "errors": [],
            "changed_paths": [],
            "bundles": rows,
            "message": f"Listed {len(rows)} bundle(s).",
        }
    if cmd == "open":
        return open_bundle(paths, args.doc_id, category=args.category)
    if cmd == "search":
        return search_bundles(paths, args.query, category=args.category)
    if cmd == "reprocess":
        return reprocess_bundle(
            paths, args.doc_id, category=args.category, force=bool(args.force or True)
        )
    if cmd == "pin":
        return set_pin_state(paths, args.doc_id, pinned=True, category=args.category)
    if cmd == "unpin":
        return set_pin_state(paths, args.doc_id, pinned=False, category=args.category)
    if cmd == "long-term-inactive":
        return move_inactive_to_long_term(
            paths, days=args.days, category=args.category, dry_run=args.dry_run
        )
    if cmd == "reconcile":
        return reconcile(paths, category=args.category, dry_run=args.dry_run)
    if cmd == "rebuild-index":
        categories = [args.category] if args.category else ["syllabi", "reference"]
        changed: list[str] = []
        for category in categories:
            manifest = load_manifest(paths, category)
            changed.append(rebuild_category_index(paths, manifest))
            changed.append(f"{category}/_manifest.json")
            save_manifest(paths, manifest)
        return {
            "ok": True,
            "command": "rebuild-index",
            "status": "ok",
            "warnings": [],
            "errors": [],
            "changed_paths": sorted(set(changed)),
            "message": f"Rebuilt index for {len(categories)} category folder(s).",
        }
    if cmd == "status":
        result = ref_status(paths)
        result["summary"]["runtime"] = detect_runtime()
        return result
    raise ValueError(f"Unhandled ref command: {cmd}")


def _run_vault_command(paths, args) -> dict:
    cmd = args.command
    if cmd == "build":
        return build_vault_index(paths, auto_ingest=args.auto_ingest)
    if cmd == "heartbeat":
        return vault_index_heartbeat(paths)
    if cmd == "init-folder":
        return init_vault_folder(paths, kind=args.kind, name=args.name)
    if cmd == "status":
        return vault_index_status(paths)
    if cmd == "query":
        return vault_index_query(paths, args.term)
    if cmd == "backlinks":
        return vault_index_backlinks(paths, args.note)
    if cmd == "dangling":
        return vault_index_dangling(paths)
    if cmd == "root-notes":
        return vault_index_root_notes(paths)
    raise ValueError(f"Unhandled vault command: {cmd}")


def _emit(result: dict, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return
    if result.get("ok"):
        print(f"[ok] {result.get('message', 'Command complete.')}")
        for warning in result.get("warnings", []):
            print(f"[warning] {warning}")
    else:
        print(f"[error] {result.get('message', 'Command failed.')}")
        for err in result.get("errors", []):
            print(f"[error] {err}")


def _seed_manifests(paths) -> None:
    for category in ("syllabi", "reference"):
        ensure_category_ready(paths, category)


if __name__ == "__main__":
    raise SystemExit(main())
