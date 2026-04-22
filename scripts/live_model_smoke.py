#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient

from delamain_backend.main import create_app


ROUTES = [
    ("github_copilot/gpt-5-mini", "chat_completions", "Reply with exactly OK_CHAT."),
    ("github_copilot/gpt-5.4-mini", "responses", "Reply with exactly OK_RESPONSES."),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a tiny authorized LiteLLM live smoke.")
    parser.add_argument(
        "--tool-probe",
        action="store_true",
        help="Use one get_now tool-call probe on the Responses route.",
    )
    parser.add_argument(
        "--allow-device-flow",
        action="store_true",
        help="Allow LiteLLM to start GitHub device-flow auth if Copilot auth is missing.",
    )
    args = parser.parse_args()

    if os.environ.get("DELAMAIN_ENABLE_MODEL_CALLS") != "1":
        raise SystemExit("Refusing live smoke: set DELAMAIN_ENABLE_MODEL_CALLS=1 explicitly.")
    auth_file = Path.home() / ".config" / "litellm" / "github_copilot" / "api-key.json"
    if not auth_file.exists() and not args.allow_device_flow:
        raise SystemExit(
            "Refusing live smoke: GitHub Copilot LiteLLM auth file is missing. "
            "Authenticate first or pass --allow-device-flow intentionally."
        )

    os.environ.setdefault("DELAMAIN_DISABLE_MODEL_FALLBACKS", "1")
    db_path = Path(tempfile.mkdtemp(prefix="delamain-live-smoke-")) / "conversations.sqlite"
    os.environ["DELAMAIN_DB_PATH"] = str(db_path)

    app = create_app()
    with TestClient(app) as client:
        for index, (route, expected_family, prompt) in enumerate(ROUTES):
            if args.tool_probe and route == "github_copilot/gpt-5.4-mini":
                prompt = "Call get_now once, then reply with one short sentence."
            print(f"starting_route={route} expected_api_family={expected_family}", flush=True)
            conversation = client.post(
                "/api/conversations",
                json={"title": f"live smoke {index}", "model_route": route},
            ).json()
            submitted = client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": prompt, "model_route": route},
            ).json()
            run = _wait_for_run(client, submitted["run_id"])
            print(f"route={route}")
            print(f"expected_api_family={expected_family}")
            print(f"run_id={submitted['run_id']}")
            print(f"run_status={run['status']}")
            if run.get("error_code"):
                print(f"error_code={run['error_code']}")
                print(f"error_message={run.get('error_message')}")
            _print_model_calls(db_path, submitted["run_id"])
            _print_tool_calls(db_path, submitted["run_id"])
            print()
    print(f"sqlite_path={db_path}")
    return 0


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.25)
    raise TimeoutError(f"Run did not finish: {run_id}")


def _print_model_calls(db_path: Path, run_id: str) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in con.execute(
            """
            SELECT model_route, api_family, status, fallback_from, fallback_reason, error_message
            FROM model_calls
            WHERE run_id = ?
            ORDER BY created_at
            """,
            (run_id,),
        )
    ]
    print("model_calls=" + json.dumps(rows, sort_keys=True))


def _print_tool_calls(db_path: Path, run_id: str) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in con.execute(
            """
            SELECT tool, status, error_message
            FROM tool_calls
            WHERE run_id = ?
            ORDER BY created_at
            """,
            (run_id,),
        )
    ]
    print("tool_calls=" + json.dumps(rows, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
