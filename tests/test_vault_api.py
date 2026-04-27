from __future__ import annotations

import json
import asyncio
import hashlib
import sqlite3
import time

from fastapi.testclient import TestClient

from delamain_backend.db import Database
from delamain_backend.main import create_app
from delamain_backend.vault_heartbeat import VaultIndexHeartbeat
from delamain_backend.vault_generated import write_generated_metadata


class CapturingModelClient:
    def __init__(self):
        self.messages = None

    async def complete(self, *, model_route, messages, tools=None):
        self.messages = messages
        return {
            "id": "final",
            "model": model_route,
            "api_family": "responses",
            "text": "done",
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


class EnrichmentModelClient:
    def __init__(self):
        self.calls = []

    async def complete(self, *, model_route, messages, tools=None):
        self.calls.append({"model_route": model_route, "messages": messages, "tools": tools})
        return {
            "id": "enrichment",
            "model": model_route,
            "api_family": "responses",
            "text": json.dumps(
                {
                    "summary": "Source-grounded graph planning note summary.",
                    "tags": ["planning", "graph"],
                    "note_type": "project_note",
                    "stale_labels": [],
                    "owner_notes": ["Projects/DELAMAIN/owner.md"],
                    "duplicate_candidates": [
                        {
                            "path": "Projects/DELAMAIN/owner.md",
                            "reason": "Both describe graph planning.",
                            "confidence": 0.72,
                        }
                    ],
                    "relation_candidates": [
                        {
                            "path": "Projects/DELAMAIN/owner.md",
                            "relation": "owned_by",
                            "reason": "Owner note consolidates this topic.",
                            "confidence": 0.88,
                        }
                    ],
                    "decisions": ["Use graph-first retrieval before embeddings."],
                    "open_questions": ["Which generated relations should be accepted?"],
                }
            ),
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


def test_vault_graph_loads_fixture_and_filters_restricted_paths(test_config):
    _write_vault_fixture(test_config)
    (test_config.paths.vault / ".env").write_text("SECRET=1", encoding="utf-8")
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"].append(
        {
            "id": ".env",
            "path": ".env",
            "title": "Env",
            "tags": ["secret"],
            "aliases": [],
            "mtime": "2026-04-25T00:00:00Z",
            "bytes": 8,
        }
    )
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    app = create_app(test_config)
    with TestClient(app) as client:
        response = client.get("/api/vault/graph?limit=20")
        assert response.status_code == 200
        payload = response.json()

    assert [node["path"] for node in payload["nodes"]] == ["Projects/DELAMAIN/note.md"]
    assert payload["edges"] == []
    assert payload["missing"] is False
    assert payload["policy_exclusions"]


def test_vault_graph_missing_index_returns_empty_graph(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        response = client.get("/api/vault/graph")
        assert response.status_code == 200
        payload = response.json()
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["missing"] is True


def test_vault_policy_exclusions_only_show_real_ignore_globs(test_config):
    test_config.paths.vault.mkdir(parents=True, exist_ok=True)
    (test_config.paths.vault / "vault_policy.md").write_text(
        "\n".join(
            [
                "---",
                "tags: [vault, policy]",
                "---",
                "",
                "# Vault Policy",
                "",
                "- Never send the whole vault.",
                "- Use converted bundle `document.md`, not raw PDFs.",
                "- project/delamain",
                "",
                "## Ignore Globs",
                "",
                "```gitignore",
                ".obsidian/**",
                "*.tmp",
                "```",
                "",
                "- `Private/**`",
                "",
                "## Taxonomy",
                "",
                "- `project/delamain`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    app = create_app(test_config)
    with TestClient(app) as client:
        response = client.get("/api/vault/policy/exclusions")
        assert response.status_code == 200
        payload = response.json()

    globs = [
        item["path"]
        for item in payload["exclusions"]
        if item.get("kind") == "vault_policy_glob"
    ]
    assert globs == [".obsidian/**", "*.tmp", "Private/**"]


def test_vault_note_requires_index_known_allowed_path(test_config):
    _write_vault_fixture(test_config)
    outside = test_config.paths.vault.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (test_config.paths.vault / "unindexed.md").write_text("unindexed", encoding="utf-8")
    (test_config.paths.vault / ".env").write_text("SECRET=1", encoding="utf-8")

    app = create_app(test_config)
    with TestClient(app) as client:
        ok = client.get("/api/vault/note", params={"path": "Projects/DELAMAIN/note.md"})
        assert ok.status_code == 200
        assert ok.json()["path"] == "Projects/DELAMAIN/note.md"
        assert ok.json()["content"].startswith("# Test Note")
        assert ok.json()["backlinks"] == []

        traversal = client.get("/api/vault/note", params={"path": "../outside.md"})
        assert traversal.status_code == 403

        restricted = client.get("/api/vault/note", params={"path": ".env"})
        assert restricted.status_code == 403

        unindexed = client.get("/api/vault/note", params={"path": "unindexed.md"})
        assert unindexed.status_code == 403


def test_frontmatter_sensitivity_nodes_are_privacy_filtered_across_vault_surfaces(test_config):
    visible = test_config.paths.vault / "Projects" / "DELAMAIN" / "visible.md"
    private = test_config.paths.vault / "Projects" / "DELAMAIN" / "private.md"
    sensitive = test_config.paths.vault / "Projects" / "DELAMAIN" / "sensitive.md"
    visible.parent.mkdir(parents=True, exist_ok=True)
    visible.write_text("# Visible Normal\n\nNormal graph note.\n", encoding="utf-8")
    private.write_bytes(
        b"---\n"
        b"sensitivity: private\n"
        b"---\n"
        b"\xff\xfePRIVATE_BODY_UNIQUE_NEVER_READ\n"
    )
    sensitive.write_text(
        "---\nsensitivity: sensitive\n---\n# Sensitive Title\n\nSensitive body.\n",
        encoding="utf-8",
    )
    index = test_config.paths.llm_workspace / "vault-index"
    index.mkdir(parents=True, exist_ok=True)
    (index / "graph.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-25T00:00:00Z",
                "nodes": [
                    {
                        "id": "Projects/DELAMAIN/visible.md",
                        "path": "Projects/DELAMAIN/visible.md",
                        "title": "Visible Normal",
                        "tags": ["normal"],
                        "bytes": visible.stat().st_size,
                        "sensitivity": "normal",
                    },
                    {
                        "id": "Projects/DELAMAIN/private.md",
                        "path": "Projects/DELAMAIN/private.md",
                        "title": "Private Unique Title",
                        "tags": ["private-tag"],
                        "aliases": ["Private Alias"],
                        "bytes": private.stat().st_size,
                        "sensitivity": "private",
                    },
                    {
                        "id": "Projects/DELAMAIN/sensitive.md",
                        "path": "Projects/DELAMAIN/sensitive.md",
                        "title": "Sensitive Unique Title",
                        "tags": ["sensitive-tag"],
                        "bytes": sensitive.stat().st_size,
                        "sensitivity": "sensitive",
                    },
                ],
                "edges": [
                    {
                        "from": "Projects/DELAMAIN/visible.md",
                        "to": "Projects/DELAMAIN/private.md",
                        "kind": "wikilink",
                    },
                    {
                        "from": "Projects/DELAMAIN/visible.md",
                        "to": "Projects/DELAMAIN/sensitive.md",
                        "kind": "wikilink",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (index / "backlinks.json").write_text(
        json.dumps(
            {
                "Projects/DELAMAIN/private.md": ["Projects/DELAMAIN/visible.md"],
                "Projects/DELAMAIN/sensitive.md": ["Projects/DELAMAIN/visible.md"],
            }
        ),
        encoding="utf-8",
    )

    app = create_app(test_config)
    with TestClient(app) as client:
        graph = client.get("/api/vault/graph")
        preview = client.post("/api/vault/context/preview", json={"prompt": "Private Sensitive Visible Normal"})
        visible_note = client.get("/api/vault/note", params={"path": "Projects/DELAMAIN/visible.md"})
        private_note = client.get("/api/vault/note", params={"path": "Projects/DELAMAIN/private.md"})
        sensitive_note = client.get("/api/vault/note", params={"path": "Projects/DELAMAIN/sensitive.md"})
        neighborhood = client.get(
            "/api/vault/graph/neighborhood",
            params={"path": "Projects/DELAMAIN/visible.md"},
        )
        enrichment_status = client.get("/api/vault/enrichment/status")

    graph_text = json.dumps(graph.json(), sort_keys=True)
    preview_text = json.dumps(preview.json(), sort_keys=True)
    neighborhood_text = json.dumps(neighborhood.json(), sort_keys=True)
    assert graph.status_code == 200
    assert [node["path"] for node in graph.json()["nodes"]] == ["Projects/DELAMAIN/visible.md"]
    assert graph.json()["edges"] == []
    assert "Private Unique Title" not in graph_text
    assert "Sensitive Unique Title" not in graph_text
    assert "private-tag" not in graph_text
    assert "sensitive-tag" not in graph_text
    assert preview.status_code == 200
    assert [item["path"] for item in preview.json()["items"]] == ["Projects/DELAMAIN/visible.md"]
    assert "Private Unique Title" not in preview_text
    assert "Sensitive Unique Title" not in preview_text
    assert visible_note.status_code == 200
    assert visible_note.json()["path"] == "Projects/DELAMAIN/visible.md"
    assert visible_note.json()["backlinks"] == []
    assert private_note.status_code == 403
    assert sensitive_note.status_code == 403
    assert neighborhood.status_code == 200
    assert neighborhood.json()["edges"] == []
    assert neighborhood.json()["policy_omissions"] == []
    assert "Private Unique Title" not in neighborhood_text
    assert "Sensitive Unique Title" not in neighborhood_text
    assert enrichment_status.status_code == 200
    assert enrichment_status.json()["node_count"] == 1


def test_vault_note_filters_stale_private_backlinks(test_config):
    target = test_config.paths.vault / "Projects" / "DELAMAIN" / "target.md"
    public_source = test_config.paths.vault / "Projects" / "DELAMAIN" / "source.md"
    private_source = test_config.paths.vault / "Projects" / "DELAMAIN" / "private-source.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Target\n\nVisible body.\n", encoding="utf-8")
    public_source.write_text("# Source\n\nLinks to [[target]].\n", encoding="utf-8")
    private_source.write_text(
        "---\nsensitivity: private\n---\n# Private Source\n\nPRIVATE_BACKLINK_BODY\n",
        encoding="utf-8",
    )
    index = test_config.paths.llm_workspace / "vault-index"
    index.mkdir(parents=True, exist_ok=True)
    (index / "graph.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-25T00:00:00Z",
                "nodes": [
                    {
                        "id": "Projects/DELAMAIN/target.md",
                        "path": "Projects/DELAMAIN/target.md",
                        "title": "Target",
                    },
                    {
                        "id": "Projects/DELAMAIN/source.md",
                        "path": "Projects/DELAMAIN/source.md",
                        "title": "Source",
                    },
                    {
                        "id": "Projects/DELAMAIN/private-source.md",
                        "path": "Projects/DELAMAIN/private-source.md",
                        "title": "Private Source",
                        "sensitivity": "private",
                    },
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    (index / "backlinks.json").write_text(
        json.dumps(
            {
                "Projects/DELAMAIN/target.md": [
                    "Projects/DELAMAIN/source.md",
                    "Projects/DELAMAIN/private-source.md",
                ]
            }
        ),
        encoding="utf-8",
    )
    app = create_app(test_config)

    with TestClient(app) as client:
        note = client.get("/api/vault/note", params={"path": "Projects/DELAMAIN/target.md"})

    assert note.status_code == 200
    body = json.dumps(note.json(), sort_keys=True)
    assert note.json()["backlinks"] == ["Projects/DELAMAIN/source.md"]
    assert "private-source" not in body
    assert "Private Source" not in body


def test_context_pins_are_revalidated_against_current_privacy(test_config):
    _write_vault_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        pinned = client.post(
            f"/api/conversations/{conversation_id}/context/pin",
            json={"paths": ["Projects/DELAMAIN/note.md"]},
        )
        assert pinned.status_code == 200
        assert pinned.json()["paths"] == ["Projects/DELAMAIN/note.md"]

        graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["nodes"][0]["sensitivity"] = "private"
        graph["nodes"][0]["title"] = "Private Pin Title"
        graph_path.write_text(json.dumps(graph), encoding="utf-8")

        listed = client.get(f"/api/conversations/{conversation_id}/context/pins")
        preview = client.post(f"/api/conversations/{conversation_id}/context/preview", json={})

    assert listed.status_code == 200
    assert listed.json() == {"paths": [], "items": []}
    preview_text = json.dumps(preview.json(), sort_keys=True)
    assert preview.status_code == 200
    assert all(
        item.get("mode") != "vault_note_pin"
        for item in preview.json()["items"]
    )
    assert "Projects/DELAMAIN/note.md" not in preview_text
    assert "Private Pin Title" not in preview_text


def test_maintenance_proposal_list_suppresses_stale_private_metadata(test_config):
    _write_vault_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "kind": "generated_tag_suggestion",
                "title": "PRIVATE_STALE_PROPOSAL_TITLE",
                "paths": ["Projects/DELAMAIN/note.md"],
                "payload": {
                    "path": "Projects/DELAMAIN/note.md",
                    "tag": "PRIVATE_STALE_TAG",
                },
            },
        )
        assert created.status_code == 201

        graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["nodes"][0]["sensitivity"] = "private"
        graph_path.write_text(json.dumps(graph), encoding="utf-8")

        listed = client.get("/api/vault/maintenance/proposals")
        proposed = client.get("/api/vault/maintenance/proposals?status=proposed")

    assert listed.status_code == 200
    assert proposed.status_code == 200
    assert listed.json() == []
    assert proposed.json() == []
    listed_text = json.dumps(listed.json(), sort_keys=True)
    assert "Projects/DELAMAIN/note.md" not in listed_text
    assert "PRIVATE_STALE_PROPOSAL_TITLE" not in listed_text
    assert "PRIVATE_STALE_TAG" not in listed_text


def test_context_pin_preview_and_run_context_load(test_config):
    _write_vault_fixture(test_config)
    model_client = CapturingModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        pinned = client.post(
            f"/api/conversations/{conversation_id}/context/pin",
            json={"paths": ["Projects/DELAMAIN/note.md"]},
        )
        assert pinned.status_code == 200
        assert pinned.json()["paths"] == ["Projects/DELAMAIN/note.md"]

        preview = client.post(
            f"/api/conversations/{conversation_id}/context/preview",
            json={},
        )
        assert preview.status_code == 200
        assert any(item["mode"] == "vault_note_pin" for item in preview.json()["items"])

        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "use the pinned note"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

    assert model_client.messages is not None
    assert any(
        "Selected vault context for this run" in str(message["content"])
        and "Important pinned content" in str(message["content"])
        for message in model_client.messages
        if message["role"] == "system"
    )

    con = sqlite3.connect(test_config.database.path)
    selected = con.execute(
        "SELECT path, included FROM run_selected_context WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    audits = [
        json.loads(row[0])["action"]
        for row in con.execute(
            "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit'",
            (conversation_id,),
        )
    ]
    con.close()
    assert selected == [("Projects/DELAMAIN/note.md", 1)]
    assert "context.pin_added" in audits


def test_context_preview_scores_prompt_without_reading_full_index_to_model(test_config):
    _write_vault_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.post("/api/vault/context/preview", json={"prompt": "what is my graph schedule"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert items[0]["path"] == "Projects/DELAMAIN/note.md"
    assert items[0]["mode"] == "full_note"
    assert "score" in items[0]


def test_vault_enrichment_run_writes_cache_updates_graph_and_proposes_tags(test_config):
    _write_vault_fixture(test_config)
    owner = test_config.paths.vault / "Projects" / "DELAMAIN" / "owner.md"
    owner.write_text("# Owner\n\nConsolidates graph planning.\n", encoding="utf-8")
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"].append(
        {
            "id": "Projects/DELAMAIN/owner.md",
            "path": "Projects/DELAMAIN/owner.md",
            "title": "Owner",
            "tags": ["project/delamain"],
            "aliases": [],
            "mtime": "2026-04-25T00:00:00Z",
            "bytes": owner.stat().st_size,
            "sha256": hashlib.sha256(owner.read_bytes()).hexdigest(),
        }
    )
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    model_client = EnrichmentModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        status_before = client.get("/api/vault/enrichment/status")
        assert status_before.status_code == 200
        assert status_before.json()["counts"]["missing"] == 2

        enriched = client.post(
            "/api/vault/enrichment/run",
            json={"paths": ["Projects/DELAMAIN/note.md"], "limit": 1},
        )
        assert enriched.status_code == 200
        assert enriched.json()["processed"][0]["path"] == "Projects/DELAMAIN/note.md"
        assert enriched.json()["proposals_created"]

        graph = client.get("/api/vault/graph")
        assert graph.status_code == 200
        node = graph.json()["nodes"][0]
        assert node["generated_metadata_state"] == "fresh"
        assert node["generated_tags"] == ["planning", "graph"]
        assert node["note_type"] == "project_note"
        assert node["owner_notes"] == ["Projects/DELAMAIN/owner.md"]
        assert node["relation_candidate_count"] == 1
        assert any(edge["kind"] == "generated_candidate" for edge in graph.json()["edges"])

        preview = client.post("/api/vault/context/preview", json={"prompt": "planning"})
        assert preview.status_code == 200
        assert "generated_tag_match:planning" in preview.json()["items"][0]["reasons"]

        proposal_id = enriched.json()["proposals_created"][0]
        diff = client.get(f"/api/vault/maintenance/proposals/{proposal_id}/diff")
        assert diff.status_code == 200
        assert diff.json()["applicable"] is True
        assert "+  - planning" in diff.json()["diff"]

        relations = client.get("/api/vault/enrichment/relations")
        assert relations.status_code == 200
        assert relations.json()["relations"][0]["decision"] == "candidate"

        accepted = client.post(
            "/api/vault/enrichment/relations/feedback",
            json={
                "from_path": "Projects/DELAMAIN/note.md",
                "to_path": "Projects/DELAMAIN/owner.md",
                "relation_type": "owned_by",
                "decision": "accepted",
            },
        )
        assert accepted.status_code == 200
        graph_after_accept = client.get("/api/vault/graph").json()
        assert any(edge["kind"] == "accepted_generated" for edge in graph_after_accept["edges"])

        rejected = client.post(
            "/api/vault/enrichment/relations/feedback",
            json={
                "from_path": "Projects/DELAMAIN/note.md",
                "to_path": "Projects/DELAMAIN/owner.md",
                "relation_type": "owned_by",
                "decision": "rejected",
            },
        )
        assert rejected.status_code == 200
        graph_after_reject = client.get("/api/vault/graph").json()
        assert not any(edge.get("generated") for edge in graph_after_reject["edges"])

    assert model_client.calls
    assert model_client.calls[0]["model_route"] == test_config.models.fallback_cheap


def test_vault_enrichment_batch_runs_in_background(test_config):
    _write_vault_fixture(test_config)
    model_client = EnrichmentModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        started = client.post("/api/vault/enrichment/batch", json={"limit": 1})
        assert started.status_code == 202
        assert started.json()["running"] is True

        status_payload = _wait_for_enrichment_batch(client)

    assert status_payload["status"] == "completed"
    assert status_payload["result"]["processed"][0]["path"] == "Projects/DELAMAIN/note.md"
    assert model_client.calls


def test_vault_graph_marks_stale_generated_metadata_and_sync_conflicts(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"][0]["sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    write_generated_metadata(
        test_config,
        {
            "items": {
                "Projects/DELAMAIN/note.md": {
                    "path": "Projects/DELAMAIN/note.md",
                    "sha256": "old-sha",
                    "summary": "Old summary.",
                    "tags": ["old"],
                    "note_type": "project_note",
                    "stale_labels": ["needs-review"],
                }
            }
        },
    )
    report = test_config.paths.llm_workspace / "health" / "sync-guard" / "hosts" / "mac" / "latest.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "health": {"host": "mac"},
                "resolver": {
                    "review_items": [
                        {
                            "conflict": str(note),
                            "canonical": str(note),
                            "reason": "sync conflict",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.get("/api/vault/graph")

    assert response.status_code == 200
    node = response.json()["nodes"][0]
    assert node["generated_metadata_state"] == "stale"
    assert node["sync_status"] == "conflicted"
    assert node["staleness_status"] == "conflicted"
    assert "source_changed_since_enrichment" in node["stale_reasons"]
    assert "sync_conflict" in node["stale_reasons"]
    assert node["stale_score"] >= 0.9


def test_maintenance_exact_replace_blocks_sync_conflicted_file(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    report = test_config.paths.llm_workspace / "health" / "sync-guard" / "hosts" / "mac" / "latest.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "health": {"host": "mac"},
                "resolver": {
                    "review_items": [
                        {
                            "conflict": str(note),
                            "canonical": str(note),
                            "reason": "sync conflict",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(test_config)

    with TestClient(app) as client:
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "kind": "generated_tag_suggestion",
                "title": "Conflicted patch",
                "paths": ["Projects/DELAMAIN/note.md"],
                "payload": {
                    "action": "exact_replace",
                    "path": "Projects/DELAMAIN/note.md",
                    "old_text": "Important pinned content.",
                    "new_text": "Critical pinned content.",
                    "expected_sha256": hashlib.sha256(note.read_bytes()).hexdigest(),
                },
            },
        )
        proposal_id = created.json()["id"]
        preview = client.get(f"/api/vault/maintenance/proposals/{proposal_id}/diff")
        applied = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/apply")

    assert preview.status_code == 200
    assert preview.json()["applicable"] is False
    assert "Syncthing conflict" in preview.json()["reason"]
    assert applied.status_code == 409


def test_prompt_selected_context_paths_are_run_scoped(test_config):
    _write_vault_fixture(test_config)
    model_client = CapturingModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "use selected context",
                "selected_context_paths": ["Projects/DELAMAIN/note.md"],
            },
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

    con = sqlite3.connect(test_config.database.path)
    pending = con.execute(
        "SELECT path FROM pending_run_context WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    selected = con.execute(
        "SELECT path FROM run_selected_context WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    con.close()
    assert pending == [("Projects/DELAMAIN/note.md",)]
    assert selected == [("Projects/DELAMAIN/note.md",)]


def test_workspace_bundle_context_uses_converted_document_not_raw_source(test_config):
    _write_vault_fixture(test_config)
    workspace_doc = test_config.paths.llm_workspace / "reference" / "api-doc" / "document.md"
    raw_source = test_config.paths.llm_workspace / "reference" / "api-doc" / "original" / "api.pdf"
    workspace_doc.parent.mkdir(parents=True, exist_ok=True)
    raw_source.parent.mkdir(parents=True, exist_ok=True)
    workspace_doc.write_text("# API Reference\n\nConverted workspace content.\n", encoding="utf-8")
    raw_source.write_text("RAW PDF SHOULD NOT BE READ", encoding="utf-8")
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"].append(
        {
            "id": "reference:api-doc",
            "path": "reference/api-doc/document.md",
            "title": "API Reference",
            "source_type": "workspace_reference",
            "category": "reference",
            "bundle_id": "api-doc",
            "document_md": "reference/api-doc/document.md",
            "source_path": "reference/api-doc/original/api.pdf",
            "status": "fresh",
            "placement": "normal",
            "tags": ["api"],
            "aliases": ["API Docs"],
            "mtime": "2026-04-25T00:00:00Z",
            "size_bytes": workspace_doc.stat().st_size,
            "sha256": "doc-sha",
        }
    )
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    model_client = CapturingModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        preview = client.post("/api/vault/context/preview", json={"prompt": "api docs"})
        assert preview.status_code == 200
        assert preview.json()["items"][0]["path"] == "reference/api-doc/document.md"
        assert "reference_priority" in preview.json()["items"][0]["reasons"]

        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "use selected workspace context",
                "selected_context_paths": ["reference/api-doc/document.md"],
            },
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

    assert model_client.messages is not None
    system_text = "\n".join(
        str(message["content"])
        for message in model_client.messages
        if message["role"] == "system"
    )
    assert "Converted workspace content" in system_text
    assert "RAW PDF SHOULD NOT BE READ" not in system_text


def test_selected_large_note_uses_fresh_generated_summary(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    note.write_text("# Test Note\n\n" + ("Large source body.\n" * 900), encoding="utf-8")
    note_sha = hashlib.sha256(note.read_bytes()).hexdigest()
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"][0]["bytes"] = note.stat().st_size
    graph["nodes"][0]["sha256"] = note_sha
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    write_generated_metadata(
        test_config,
        {
            "items": {
                "Projects/DELAMAIN/note.md": {
                    "path": "Projects/DELAMAIN/note.md",
                    "sha256": note_sha,
                    "summary": "Compact generated summary for oversized note.",
                    "tags": ["large-note"],
                    "note_type": "project_note",
                    "stale_labels": [],
                }
            }
        },
    )
    model_client = CapturingModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "use selected context",
                "selected_context_paths": ["Projects/DELAMAIN/note.md"],
            },
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

    system_text = "\n".join(
        str(message["content"])
        for message in model_client.messages
        if message["role"] == "system"
    )
    assert "Compact generated summary for oversized note." in system_text
    assert "Large source body." not in system_text


def test_vault_graph_returns_unified_filters(test_config):
    _write_vault_fixture(test_config)
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"].append(
        {
            "id": "syllabi:course",
            "path": "syllabi/course/document.md",
            "title": "Course Syllabus",
            "source_type": "workspace_syllabus",
            "category": "syllabi",
            "status": "fresh",
            "placement": "normal",
            "tags": ["course"],
            "size_bytes": 100,
        }
    )
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    (test_config.paths.llm_workspace / "syllabi" / "course").mkdir(parents=True)
    (test_config.paths.llm_workspace / "syllabi" / "course" / "document.md").write_text("# Course\n", encoding="utf-8")
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.get("/api/vault/graph")

    assert response.status_code == 200
    payload = response.json()
    assert "vault_note" in payload["filters"]["source_types"]
    assert "workspace_syllabus" in payload["filters"]["source_types"]
    assert payload["index"]["status"] in {"ok", "stale"}


def test_vault_graph_neighborhood_returns_bounded_policy_filtered_neighbors(test_config):
    _write_graph_navigation_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.get(
            "/api/vault/graph/neighborhood",
            params={"path": "Projects/A.md", "hops": 1, "limit": 80},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["center"]["path"] == "Projects/A.md"
    assert [node["path"] for node in payload["nodes"]] == ["Projects/A.md", "Projects/B.md"]
    assert [(edge["from"], edge["to"], edge["reason"]) for edge in payload["edges"]] == [
        ("Projects/A.md", "Projects/B.md", "wikilink")
    ]
    assert payload["omitted"]["policy_nodes"] == 2
    assert {item["reason"] for item in payload["policy_omissions"]} == {"ignored", "path_policy"}
    assert all(item["id"] is None for item in payload["policy_omissions"])
    assert all(item["path"] is None for item in payload["policy_omissions"])
    assert all(item["title"] == "Policy-excluded node" for item in payload["policy_omissions"])


def test_vault_graph_neighborhood_limit_reports_omitted_nodes(test_config):
    _write_graph_navigation_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.get(
            "/api/vault/graph/neighborhood",
            params={"path": "Projects/A.md", "hops": 2, "limit": 2},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [node["path"] for node in payload["nodes"]] == ["Projects/A.md", "Projects/B.md"]
    assert payload["omitted"]["limit_nodes"] == 1


def test_vault_graph_path_returns_shortest_explicit_path(test_config):
    _write_graph_navigation_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.get(
            "/api/vault/graph/path",
            params={"from": "Projects/A.md", "to": "Projects/D.md"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["hops"] == 3
    assert [node["path"] for node in payload["nodes"]] == [
        "Projects/A.md",
        "Projects/B.md",
        "Projects/C.md",
        "Projects/D.md",
    ]
    assert [(edge["from"], edge["to"]) for edge in payload["edges"]] == [
        ("Projects/A.md", "Projects/B.md"),
        ("Projects/B.md", "Projects/C.md"),
        ("Projects/C.md", "Projects/D.md"),
    ]


def test_vault_graph_path_reports_no_path_without_reading_bodies(test_config):
    _write_graph_navigation_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.get(
            "/api/vault/graph/path",
            params={"from": "Projects/A.md", "to": "Projects/Isolated.md"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is False
    assert payload["nodes"] == []
    assert payload["edges"] == []


def test_vault_graph_navigation_blocks_policy_excluded_targets(test_config):
    _write_graph_navigation_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        ignored = client.get(
            "/api/vault/graph/neighborhood",
            params={"path": "Private/hidden.md"},
        )
        restricted = client.get(
            "/api/vault/graph/path",
            params={"from": "Projects/A.md", "to": ".env"},
        )

    assert ignored.status_code == 403
    assert restricted.status_code == 403


def test_generated_relations_filter_stale_source_sha(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    owner = test_config.paths.vault / "Projects" / "DELAMAIN" / "owner.md"
    owner.write_text("# Owner\n\nCurrent owner note.\n", encoding="utf-8")
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"][0]["sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    graph["nodes"].append(
        {
            "id": "Projects/DELAMAIN/owner.md",
            "path": "Projects/DELAMAIN/owner.md",
            "title": "Owner",
            "sha256": hashlib.sha256(owner.read_bytes()).hexdigest(),
        }
    )
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    write_generated_metadata(
        test_config,
        {
            "items": {
                "Projects/DELAMAIN/note.md": {
                    "path": "Projects/DELAMAIN/note.md",
                    "sha256": "stale-sha",
                    "generated_at": "2026-04-25T00:00:00Z",
                    "relation_candidates": [
                        {
                            "path": "Projects/DELAMAIN/owner.md",
                            "relation": "owned_by",
                            "reason": "Stale generated relation.",
                        }
                    ],
                }
            }
        },
    )
    app = create_app(test_config)

    with TestClient(app) as client:
        relations = client.get("/api/vault/enrichment/relations")
        graph_response = client.get("/api/vault/graph")

    assert relations.status_code == 200
    assert relations.json()["relations"] == []
    assert graph_response.status_code == 200
    assert not any(edge.get("generated") for edge in graph_response.json()["edges"])


def test_generated_relations_filter_policy_blocked_paths(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    graph_path = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    note_sha = hashlib.sha256(note.read_bytes()).hexdigest()
    graph["nodes"][0]["sha256"] = note_sha
    graph["nodes"].append(
        {
            "id": "Projects/DELAMAIN/blocked.md",
            "path": "Projects/DELAMAIN/blocked.md",
            "title": "Blocked",
            "policy_state": "blocked",
            "sha256": "blocked-sha",
        }
    )
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    write_generated_metadata(
        test_config,
        {
            "items": {
                "Projects/DELAMAIN/note.md": {
                    "path": "Projects/DELAMAIN/note.md",
                    "sha256": note_sha,
                    "generated_at": "2026-04-25T00:00:00Z",
                    "relation_candidates": [
                        {
                            "path": "Projects/DELAMAIN/blocked.md",
                            "relation": "related",
                            "reason": "Blocked target must not leak.",
                        }
                    ],
                },
                "Projects/DELAMAIN/blocked.md": {
                    "path": "Projects/DELAMAIN/blocked.md",
                    "sha256": "blocked-sha",
                    "generated_at": "2026-04-25T00:00:00Z",
                    "relation_candidates": [
                        {
                            "path": "Projects/DELAMAIN/note.md",
                            "relation": "related",
                            "reason": "Blocked source must not leak.",
                        }
                    ],
                },
            }
        },
    )
    app = create_app(test_config)

    with TestClient(app) as client:
        relations = client.get("/api/vault/enrichment/relations")
        graph_response = client.get("/api/vault/graph")

    assert relations.status_code == 200
    assert relations.json()["relations"] == []
    assert graph_response.status_code == 200
    assert not any(edge.get("generated") for edge in graph_response.json()["edges"])


def test_vault_index_heartbeat_run_once_executes_after_inactivity(test_config):
    heartbeat = VaultIndexHeartbeat(test_config, cadence_seconds=300, inactivity_seconds=0)
    first = asyncio.run(heartbeat.run_once())
    second = asyncio.run(heartbeat.run_once())

    assert first["status"] == "observed"
    assert second["status"] in {"ok", "error"}
    assert (test_config.paths.llm_workspace / "vault-index" / "_heartbeat.json").exists()


def test_vault_folder_init_endpoint_runs_helper_and_audits(test_config):
    helper = test_config.paths.llm_workspace / "bin" / "delamain-vault-index"
    helper.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$0.args\"\n"
        "printf '{\"ok\":true,\"status\":\"initialized\",\"changed_paths\":[\"Projects/Graph Demo/INDEX.md\"]}\\n'\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    app = create_app(test_config)

    with TestClient(app) as client:
        response = client.post(
            "/api/vault/folders/init",
            json={"kind": "project", "name": "Graph Demo"},
        )

    assert response.status_code == 200
    assert response.json()["changed_paths"] == ["Projects/Graph Demo/INDEX.md"]
    args = (test_config.paths.llm_workspace / "bin" / "delamain-vault-index.args").read_text(
        encoding="utf-8"
    ).splitlines()
    assert args == ["init-folder", "--kind", "project", "--name", "Graph Demo", "--json"]

    con = sqlite3.connect(test_config.database.path)
    audits = [
        json.loads(row[0])["action"]
        for row in con.execute("SELECT payload FROM events WHERE type = 'audit'")
    ]
    con.close()
    assert "vault_folder.initialized" in audits


def test_heartbeat_records_ingest_warnings_as_maintenance_proposals(test_config):
    helper = test_config.paths.llm_workspace / "bin" / "delamain-vault-index"
    helper.write_text(
        "#!/usr/bin/env bash\n"
        "printf '{\"ok\":true,\"status\":\"ok\",\"summary\":{\"auto_ingest\":{\"errors\":[\"failed bundle\"],\"warnings\":[\"needs OCR\"]}}}\\n'\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)

    rows = asyncio.run(_run_heartbeat_and_fetch_proposals(test_config))

    kinds = {row["kind"] for row in rows}
    descriptions = {row["description"] for row in rows}
    assert "workspace_ingest_error" in kinds
    assert "workspace_ingest_warning" in kinds
    assert "failed bundle" in descriptions
    assert "needs OCR" in descriptions


def test_maintenance_proposal_crud(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "conversation_id": conversation_id,
                "kind": "generated_tag_suggestion",
                "title": "Add project tag",
                "paths": ["Projects/DELAMAIN/note.md"],
                "payload": {"tag": "project/delamain"},
            },
        )
        assert created.status_code == 201
        proposal_id = created.json()["id"]
        assert created.json()["status"] == "proposed"
        assert created.json()["paths"] == ["Projects/DELAMAIN/note.md"]

        updated = client.patch(
            f"/api/vault/maintenance/proposals/{proposal_id}",
            json={"status": "rejected"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "rejected"
        assert updated.json()["resolved_at"] is not None

        listed = client.get("/api/vault/maintenance/proposals?status=rejected")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [proposal_id]


def test_maintenance_proposal_exact_replace_diff_apply_and_revert(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    original = note.read_text(encoding="utf-8")
    original_sha = hashlib.sha256(note.read_bytes()).hexdigest()
    app = create_app(test_config)

    with TestClient(app) as client:
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "kind": "generated_tag_suggestion",
                "title": "Tighten note wording",
                "paths": ["Projects/DELAMAIN/note.md"],
                "payload": {
                    "action": "exact_replace",
                    "path": "Projects/DELAMAIN/note.md",
                    "old_text": "Important pinned content.",
                    "new_text": "Critical pinned content.",
                    "expected_sha256": original_sha,
                },
            },
        )
        assert created.status_code == 201
        proposal_id = created.json()["id"]

        preview = client.get(f"/api/vault/maintenance/proposals/{proposal_id}/diff")
        assert preview.status_code == 200
        assert preview.json()["applicable"] is True
        assert "-Important pinned content." in preview.json()["diff"]
        assert "+Critical pinned content." in preview.json()["diff"]

        applied = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/apply")
        assert applied.status_code == 200
        assert applied.json()["status"] == "applied"
        assert applied.json()["payload"]["applied"]["mode"] == "exact_replace"
        assert note.read_text(encoding="utf-8") == original.replace(
            "Important pinned content.",
            "Critical pinned content.",
        )

        reverted = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/revert")
        assert reverted.status_code == 200
        assert reverted.json()["status"] == "reverted"
        assert note.read_text(encoding="utf-8") == original

    con = sqlite3.connect(test_config.database.path)
    audits = [
        json.loads(row[0])["action"]
        for row in con.execute("SELECT payload FROM events WHERE type = 'audit'")
    ]
    con.close()
    assert "vault_maintenance.proposal_applied" in audits
    assert "vault_maintenance.proposal_reverted" in audits


def test_maintenance_proposal_reject_endpoint_audits(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "kind": "workspace_ingest_warning",
                "title": "Review OCR warning",
                "payload": {"message": "needs OCR"},
            },
        )
        proposal_id = created.json()["id"]
        rejected = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/reject")

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    con = sqlite3.connect(test_config.database.path)
    audits = [
        json.loads(row[0])["action"]
        for row in con.execute("SELECT payload FROM events WHERE type = 'audit'")
    ]
    con.close()
    assert "vault_maintenance.proposal_rejected" in audits


def test_maintenance_exact_replace_blocks_stale_sha(test_config):
    _write_vault_fixture(test_config)
    app = create_app(test_config)

    with TestClient(app) as client:
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "kind": "generated_tag_suggestion",
                "title": "Stale patch",
                "paths": ["Projects/DELAMAIN/note.md"],
                "payload": {
                    "action": "exact_replace",
                    "path": "Projects/DELAMAIN/note.md",
                    "old_text": "Important pinned content.",
                    "new_text": "Critical pinned content.",
                    "expected_sha256": "not-the-current-sha",
                },
            },
        )
        proposal_id = created.json()["id"]
        preview = client.get(f"/api/vault/maintenance/proposals/{proposal_id}/diff")
        applied = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/apply")

    assert preview.status_code == 200
    assert preview.json()["applicable"] is False
    assert applied.status_code == 409


def test_maintenance_revert_rejects_tampered_backup_path(test_config):
    _write_vault_fixture(test_config)
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    app = create_app(test_config)

    with TestClient(app) as client:
        created = client.post(
            "/api/vault/maintenance/proposals",
            json={
                "kind": "generated_tag_suggestion",
                "title": "Tighten note wording",
                "paths": ["Projects/DELAMAIN/note.md"],
                "payload": {
                    "action": "exact_replace",
                    "path": "Projects/DELAMAIN/note.md",
                    "old_text": "Important pinned content.",
                    "new_text": "Critical pinned content.",
                    "expected_sha256": hashlib.sha256(note.read_bytes()).hexdigest(),
                },
            },
        )
        proposal_id = created.json()["id"]
        applied = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/apply")
        assert applied.status_code == 200

        payload = applied.json()["payload"]
        payload["applied"]["changes"][0]["backup_path"] = str(test_config.paths.vault / "outside.bak")
        con = sqlite3.connect(test_config.database.path)
        con.execute(
            "UPDATE vault_maintenance_proposals SET payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), proposal_id),
        )
        con.commit()
        con.close()

        reverted = client.post(f"/api/vault/maintenance/proposals/{proposal_id}/revert")

    assert reverted.status_code == 409
    assert "outside DELAMAIN maintenance backups" in reverted.json()["detail"]


async def _run_heartbeat_and_fetch_proposals(test_config) -> list[dict]:
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    heartbeat = VaultIndexHeartbeat(test_config, cadence_seconds=300, inactivity_seconds=0, db=db)
    await heartbeat.run_once()
    await heartbeat.run_once()
    rows = await db.fetchall(
        "SELECT kind, description FROM vault_maintenance_proposals ORDER BY created_at ASC"
    )
    await db.close()
    return rows


def _write_vault_fixture(test_config):
    note = test_config.paths.vault / "Projects" / "DELAMAIN" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Test Note\n\nImportant pinned content.\n", encoding="utf-8")
    index = test_config.paths.llm_workspace / "vault-index"
    index.mkdir(parents=True, exist_ok=True)
    (index / "graph.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-25T00:00:00Z",
                "nodes": [
                    {
                        "id": "Projects/DELAMAIN/note.md",
                        "path": "Projects/DELAMAIN/note.md",
                        "title": "Test Note",
                        "tags": ["project/delamain", "graph"],
                        "aliases": ["Pinned"],
                        "mtime": "2026-04-25T00:00:00Z",
                        "bytes": note.stat().st_size,
                    }
                ],
                "edges": [
                    {
                        "from": "Projects/DELAMAIN/note.md",
                        "to": "missing.md",
                        "kind": "wikilink",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (index / "backlinks.json").write_text(
        json.dumps({"Projects/DELAMAIN/note.md": ["Projects/DELAMAIN/source.md"]}),
        encoding="utf-8",
    )


def _write_graph_navigation_fixture(test_config):
    test_config.paths.vault.mkdir(parents=True, exist_ok=True)
    (test_config.paths.vault / "vault_policy.md").write_text(
        "## Ignore Globs\n\n- `Private/*`\n",
        encoding="utf-8",
    )
    index = test_config.paths.llm_workspace / "vault-index"
    index.mkdir(parents=True, exist_ok=True)
    nodes = [
        {"id": "Projects/A.md", "path": "Projects/A.md", "title": "A"},
        {"id": "Projects/B.md", "path": "Projects/B.md", "title": "B"},
        {"id": "Projects/C.md", "path": "Projects/C.md", "title": "C"},
        {"id": "Projects/D.md", "path": "Projects/D.md", "title": "D"},
        {"id": "Projects/Isolated.md", "path": "Projects/Isolated.md", "title": "Isolated"},
        {"id": "Private/hidden.md", "path": "Private/hidden.md", "title": "Hidden"},
        {"id": ".env", "path": ".env", "title": "Env"},
    ]
    edges = [
        {"from": "Projects/A.md", "to": "Projects/B.md", "kind": "wikilink"},
        {"from": "Projects/B.md", "to": "Projects/C.md", "kind": "wikilink"},
        {"from": "Projects/C.md", "to": "Projects/D.md", "kind": "wikilink"},
        {"from": "Projects/A.md", "to": "Private/hidden.md", "kind": "wikilink"},
        {"from": "Projects/A.md", "to": ".env", "kind": "wikilink"},
    ]
    (index / "graph.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-25T00:00:00Z",
                "nodes": nodes,
                "edges": edges,
            }
        ),
        encoding="utf-8",
    )


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def _wait_for_enrichment_batch(client: TestClient) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status_payload = client.get("/api/vault/enrichment/batch").json()
        if not status_payload["running"]:
            return status_payload
        time.sleep(0.05)
    raise AssertionError("enrichment batch did not finish")
