from __future__ import annotations

import dataclasses
import base64
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from delamain_backend.agent.litellm_client import format_messages_for_api_family
from delamain_backend.agent.router import api_family_for_route
from delamain_backend.main import create_app


class CaptureModelClient:
    def __init__(self):
        self.calls = []

    async def complete(self, *, model_route, messages, tools=None):
        del tools
        self.calls.append(messages)
        return {
            "id": "capture",
            "model": model_route,
            "api_family": api_family_for_route(model_route),
            "text": "captured",
            "tool_calls": [],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "premium_units": 0,
                "usage_source": "test",
                "usage_estimated": False,
            },
            "raw": None,
        }


def test_text_upload_lifecycle(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        created = client.post(
            "/api/uploads",
            files={"file": ("notes.txt", b"Alpha upload context", "text/plain")},
        )
        assert created.status_code == 201
        upload = created.json()
        assert upload["original_filename"] == "notes.txt"
        assert upload["extension"] == ".txt"
        assert upload["conversion_status"] == "fresh"
        assert upload["conversion_converter"] == "direct_text"
        assert "storage_path" not in upload
        assert "extracted_path" not in upload
        assert "converted_path" not in upload
        con = sqlite3.connect(test_config.database.path)
        storage_path = con.execute("SELECT storage_path FROM uploads WHERE id = ?", (upload["id"],)).fetchone()[0]
        con.close()
        assert Path(storage_path).is_file()
        assert test_config.uploads.storage_path in Path(storage_path).parents

        listed = client.get("/api/uploads")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["uploads"]] == [upload["id"]]
        assert listed.json()["uploads"][0]["conversion_converter"] == "direct_text"

        preview = client.get(f"/api/uploads/{upload['id']}/preview?limit=8")
        assert preview.status_code == 200
        assert preview.json()["content"] == "Alpha up"
        assert preview.json()["truncated"] is True

        downloaded = client.get(f"/api/uploads/{upload['id']}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == b"Alpha upload context"

        deleted = client.delete(f"/api/uploads/{upload['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/uploads/{upload['id']}").status_code == 404


def test_upload_rejects_traversal_archives_and_oversize(test_config):
    small_config = dataclasses.replace(
        test_config,
        uploads=dataclasses.replace(test_config.uploads, max_size_bytes=4),
    )
    app = create_app(small_config)
    with TestClient(app) as client:
        traversal = client.post(
            "/api/uploads",
            files={"file": ("../notes.txt", b"ok", "text/plain")},
        )
        assert traversal.status_code == 400

        archive = client.post(
            "/api/uploads",
            files={"file": ("archive.zip", b"ok", "application/zip")},
        )
        assert archive.status_code == 415

        oversized = client.post(
            "/api/uploads",
            files={"file": ("notes.txt", b"12345", "text/plain")},
        )
        assert oversized.status_code == 413


def test_prompt_upload_attachment_is_persisted_and_added_to_model_context(test_config):
    model_client = CaptureModelClient()
    app = create_app(test_config, model_client=model_client)
    with TestClient(app) as client:
        upload = client.post(
            "/api/uploads",
            files={"file": ("notes.md", b"# Upload\n\nRun-specific context.", "text/markdown")},
        ).json()
        conversation_id = client.post("/api/conversations", json={"title": "Uploads"}).json()["id"]
        submitted = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "Use the upload.",
                "attachments": [{"upload_id": upload["id"]}],
            },
        )
        assert submitted.status_code == 202
        run = _wait_for_run(client, submitted.json()["run_id"])
        assert run["status"] == "completed"

    assert model_client.calls
    flattened = "\n\n".join(message["content"] for message in model_client.calls[0])
    assert "DELAMAIN upload attachment context" in flattened
    assert "Run-specific context." in flattened
    assert "notes.md" in flattened

    con = sqlite3.connect(test_config.database.path)
    rows = con.execute(
        """
        SELECT original_filename, included, representation, context_char_count
        FROM run_upload_attachments
        WHERE run_id = ?
        """,
        (run["id"],),
    ).fetchall()
    context_rows = con.execute(
        """
        SELECT mode, path, included
        FROM context_loads
        WHERE run_id = ? AND mode = 'upload_attachment'
        """,
        (run["id"],),
    ).fetchall()
    con.close()
    assert rows == [("notes.md", 1, "converted", len("# Upload\n\nRun-specific context."))]
    assert len(context_rows) == 1
    assert context_rows[0][0] == "upload_attachment"
    assert context_rows[0][1].startswith("upload:")
    assert context_rows[0][2] == 1


def test_rich_upload_attachment_reaches_model_as_native_file_part(test_config):
    model_client = CaptureModelClient()
    app = create_app(test_config, model_client=model_client)
    with TestClient(app) as client:
        upload = client.post(
            "/api/uploads",
            files={"file": ("paper.pdf", b"%PDF native bytes", "application/pdf")},
        ).json()
        conversation_id = client.post("/api/conversations", json={"title": "Rich"}).json()["id"]
        submitted = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "Use the rich upload.",
                "attachments": [
                    {
                        "upload_id": upload["id"],
                        "include": True,
                        "representation": "rich",
                    }
                ],
            },
        )
        assert submitted.status_code == 202
        run = _wait_for_run(client, submitted.json()["run_id"])
        assert run["status"] == "completed"

    assert model_client.calls
    native_messages = [
        message for message in model_client.calls[0] if isinstance(message.get("content"), list)
    ]
    assert native_messages
    file_parts = [
        part
        for message in native_messages
        for part in message["content"]
        if part.get("type") == "delamain_upload_file"
    ]
    assert len(file_parts) == 1
    assert file_parts[0]["file"]["filename"] == "paper.pdf"
    assert file_parts[0]["file"]["path"].endswith("/original/paper.pdf")

    con = sqlite3.connect(test_config.database.path)
    row = con.execute(
        """
        SELECT original_filename, representation, native_context, content_path
        FROM run_upload_attachments
        WHERE run_id = ?
        """,
        (run["id"],),
    ).fetchone()
    con.close()
    assert row == ("paper.pdf", "rich", 1, None)


def test_litellm_formatter_preserves_native_file_parts(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF native bytes")
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this."},
                {
                    "type": "delamain_upload_file",
                    "file": {
                        "filename": "paper.pdf",
                        "path": str(source),
                        "mime_type": "application/pdf",
                        "sha256": "",
                        "byte_count": source.stat().st_size,
                        "fallback_text": "fallback text",
                    },
                },
            ],
        }
    ]

    chat = format_messages_for_api_family(
        messages,
        "chat_completions",
        "github_copilot/gpt-5-mini",
    )
    assert chat[0]["content"][1]["type"] == "file"
    assert chat[0]["content"][1]["file"]["filename"] == "paper.pdf"
    assert chat[0]["content"][1]["file"]["file_data"] == (
        f"data:application/pdf;base64,{encoded}"
    )

    responses = format_messages_for_api_family(
        messages,
        "responses",
        "github_copilot/gpt-5.4-mini",
    )
    assert responses[0]["content"][1]["type"] == "input_file"
    assert responses[0]["content"][1]["filename"] == "paper.pdf"
    assert responses[0]["content"][1]["file_data"] == f"data:application/pdf;base64,{encoded}"


def test_litellm_formatter_falls_back_to_text_for_unsupported_native_route(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF native bytes")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this."},
                {
                    "type": "delamain_upload_file",
                    "file": {
                        "filename": "paper.pdf",
                        "path": str(source),
                        "mime_type": "application/pdf",
                        "sha256": "",
                        "byte_count": source.stat().st_size,
                        "fallback_text": "fallback text",
                    },
                },
            ],
        }
    ]

    formatted = format_messages_for_api_family(
        messages,
        "chat_completions",
        "openrouter/deepseek/deepseek-v3.2",
    )
    assert isinstance(formatted[0]["content"], str)
    assert "using extracted text fallback" in formatted[0]["content"]
    assert "fallback text" in formatted[0]["content"]


def test_promote_upload_copies_original_and_rebuilds_index(test_config, monkeypatch):
    from delamain_backend import uploads as upload_module

    calls = {}

    def fake_ensure_bundle(paths, target, *, category=None, dry_run=False, force=False):
        del paths, dry_run, force
        calls["target"] = Path(target)
        calls["category"] = category
        calls["target_exists_during_ensure"] = Path(target).exists()
        return {
            "ok": True,
            "status": "ok",
            "errors": [],
            "warnings": [],
            "changed_paths": [],
            "bundle": {"id": "promoted-doc"},
        }

    def fake_build_vault_index(paths, *, auto_ingest=False):
        del paths, auto_ingest
        calls["indexed"] = True
        return {
            "ok": True,
            "status": "ok",
            "warnings": [],
            "errors": [],
            "changed_paths": [],
            "summary": {"workspace_bundle_count": 1},
        }

    monkeypatch.setattr(upload_module, "ensure_bundle", fake_ensure_bundle)
    monkeypatch.setattr(upload_module, "build_vault_index", fake_build_vault_index)

    app = create_app(test_config)
    with TestClient(app) as client:
        upload = client.post(
            "/api/uploads",
            files={"file": ("paper.pdf", b"%PDF pretend", "application/pdf")},
        ).json()
        promoted = client.post(
            f"/api/uploads/{upload['id']}/promote",
            json={"category": "reference"},
        )
        assert promoted.status_code == 200
        body = promoted.json()
        assert body["upload"]["promoted_category"] == "reference"
        assert body["upload"]["promoted_bundle_id"] == "promoted-doc"

    assert calls["category"] == "reference"
    assert calls["target_exists_during_ensure"] is True
    assert calls["target"].parent == test_config.paths.llm_workspace / "reference"
    assert calls["indexed"] is True
    con = sqlite3.connect(test_config.database.path)
    storage_path = con.execute("SELECT storage_path FROM uploads WHERE id = ?", (upload["id"],)).fetchone()[0]
    con.close()
    assert Path(storage_path).is_file()


def test_promote_markdown_upload_creates_workspace_bundle(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        upload = client.post(
            "/api/uploads",
            files={"file": ("reference-note.md", b"# Reference Note\n\nBody", "text/markdown")},
        ).json()
        promoted = client.post(
            f"/api/uploads/{upload['id']}/promote",
            json={"category": "reference"},
        )
        assert promoted.status_code == 200
        body = promoted.json()

    bundle_id = body["upload"]["promoted_bundle_id"]
    document = test_config.paths.llm_workspace / "reference" / bundle_id / "document.md"
    source = (
        test_config.paths.llm_workspace
        / "reference"
        / bundle_id
        / "original"
        / "reference-note.md"
    )
    graph = test_config.paths.llm_workspace / "vault-index" / "graph.json"
    assert document.read_text(encoding="utf-8") == "# Reference Note\n\nBody"
    assert source.read_bytes() == b"# Reference Note\n\nBody"
    assert graph.exists()
    con = sqlite3.connect(test_config.database.path)
    storage_path = con.execute("SELECT storage_path FROM uploads WHERE id = ?", (upload["id"],)).fetchone()[0]
    con.close()
    assert Path(storage_path).is_file()


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
