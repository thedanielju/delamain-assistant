from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            context_mode TEXT NOT NULL DEFAULT 'normal',
            model_route TEXT,
            incognito_route INTEGER NOT NULL DEFAULT 0,
            sensitive_unlocked INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            assistant_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            context_mode TEXT NOT NULL DEFAULT 'normal',
            model_route TEXT NOT NULL,
            incognito_route INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            started_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            tool TEXT NOT NULL,
            arguments TEXT NOT NULL,
            status TEXT NOT NULL,
            stdout TEXT,
            stderr TEXT,
            result_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS model_calls (
            id TEXT PRIMARY KEY,
            run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
            model_route TEXT NOT NULL,
            api_family TEXT NOT NULL,
            status TEXT NOT NULL,
            fallback_from TEXT,
            fallback_reason TEXT,
            usage_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS context_loads (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            mode TEXT NOT NULL,
            byte_count INTEGER,
            sha256 TEXT,
            included INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
            ON conversations(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_runs_conversation
            ON runs(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_conversation
            ON events(conversation_id, id);
        CREATE INDEX IF NOT EXISTS idx_events_run
            ON events(run_id, id);
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS action_runs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
            action_id TEXT NOT NULL,
            label TEXT NOT NULL,
            argv_json TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL,
            writes INTEGER NOT NULL DEFAULT 0,
            remote INTEGER NOT NULL DEFAULT 0,
            exit_code INTEGER,
            duration_ms INTEGER,
            stdout_path TEXT NOT NULL,
            stderr_path TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            stdout_preview TEXT,
            stderr_preview TEXT,
            stdout_bytes INTEGER,
            stderr_bytes INTEGER,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_action_runs_conversation
            ON action_runs(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_action_runs_action
            ON action_runs(action_id, created_at);
        """,
    ),
]

MIGRATIONS.append(
    (
        3,
        """
        ALTER TABLE workers ADD COLUMN name TEXT;
        ALTER TABLE workers ADD COLUMN worker_type TEXT;
        ALTER TABLE workers ADD COLUMN host TEXT NOT NULL DEFAULT 'serrano';
        ALTER TABLE workers ADD COLUMN tmux_session TEXT;
        ALTER TABLE workers ADD COLUMN tmux_socket TEXT;
        ALTER TABLE workers ADD COLUMN conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL;
        ALTER TABLE workers ADD COLUMN command TEXT;
        ALTER TABLE workers ADD COLUMN pid INTEGER;
        ALTER TABLE workers ADD COLUMN exit_code INTEGER;
        ALTER TABLE workers ADD COLUMN error_message TEXT;
        ALTER TABLE workers ADD COLUMN stopped_at TEXT;

        CREATE INDEX IF NOT EXISTS idx_workers_status
            ON workers(status);
        CREATE INDEX IF NOT EXISTS idx_workers_conversation
            ON workers(conversation_id);
        """,
    )
)

MIGRATIONS.append(
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        ALTER TABLE conversations ADD COLUMN folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_folders_parent
            ON folders(parent_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_folder
            ON conversations(folder_id);

        CREATE TABLE IF NOT EXISTS permissions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            decision TEXT,
            resolver TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_permissions_run
            ON permissions(run_id, status);
        """,
    )
)

MIGRATIONS.append(
    (
        5,
        """
        ALTER TABLE model_calls ADD COLUMN usage_source TEXT;
        ALTER TABLE model_calls ADD COLUMN usage_estimated INTEGER;
        ALTER TABLE model_calls ADD COLUMN input_tokens INTEGER;
        ALTER TABLE model_calls ADD COLUMN output_tokens INTEGER;
        ALTER TABLE model_calls ADD COLUMN premium_request_count INTEGER;
        ALTER TABLE model_calls ADD COLUMN estimated_cost_usd REAL;
        ALTER TABLE model_calls ADD COLUMN provider_usage_json TEXT;
        ALTER TABLE model_calls ADD COLUMN response_headers_json TEXT;

        CREATE INDEX IF NOT EXISTS idx_model_calls_budget
            ON model_calls(status, model_route, created_at);
        """,
    )
)

MIGRATIONS.append(
    (
        6,
        """
        CREATE TABLE IF NOT EXISTS context_pins (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            title TEXT,
            mode TEXT NOT NULL DEFAULT 'vault_note_pin',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE(conversation_id, path)
        );

        CREATE INDEX IF NOT EXISTS idx_context_pins_conversation
            ON context_pins(conversation_id, created_at);

        CREATE TABLE IF NOT EXISTS run_selected_context (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            title TEXT,
            mode TEXT NOT NULL,
            byte_count INTEGER,
            sha256 TEXT,
            included INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_run_selected_context_run
            ON run_selected_context(run_id, created_at);

        CREATE TABLE IF NOT EXISTS pending_run_context (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            title TEXT,
            mode TEXT NOT NULL DEFAULT 'vault_context_tray',
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_pending_run_context_run
            ON pending_run_context(run_id, created_at);

        CREATE TABLE IF NOT EXISTS vault_maintenance_proposals (
            id TEXT PRIMARY KEY,
            conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            paths_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'proposed',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_vault_maintenance_proposals_status
            ON vault_maintenance_proposals(status, created_at);
        """,
    )
)

MIGRATIONS.append(
    (
        7,
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id TEXT PRIMARY KEY,
            original_filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            mime_type TEXT,
            byte_count INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            extracted_path TEXT,
            converted_path TEXT,
            conversion_status TEXT NOT NULL DEFAULT 'pending',
            converter TEXT,
            conversion_error TEXT,
            promoted_category TEXT,
            promoted_bundle_id TEXT,
            promoted_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_uploads_created_at
            ON uploads(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_uploads_sha256
            ON uploads(sha256);

        CREATE TABLE IF NOT EXISTS run_upload_attachments (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            upload_id TEXT REFERENCES uploads(id) ON DELETE SET NULL,
            original_filename TEXT NOT NULL,
            representation TEXT NOT NULL,
            included INTEGER NOT NULL DEFAULT 1,
            byte_count INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            content_path TEXT,
            content_sha256 TEXT,
            context_char_count INTEGER,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_run_upload_attachments_run
            ON run_upload_attachments(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_run_upload_attachments_upload
            ON run_upload_attachments(upload_id);
        """,
    )
)

MIGRATIONS.append(
    (
        8,
        """
        ALTER TABLE run_upload_attachments ADD COLUMN original_path TEXT;
        ALTER TABLE run_upload_attachments ADD COLUMN mime_type TEXT;
        ALTER TABLE run_upload_attachments ADD COLUMN extension TEXT;
        ALTER TABLE run_upload_attachments ADD COLUMN native_context INTEGER NOT NULL DEFAULT 0;
        """,
    )
)
