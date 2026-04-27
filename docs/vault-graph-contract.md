# Vault Graph Contract

Last updated: 2026-04-26

This document defines the contract for DELAMAIN's unified graph and context-capsule slice. V1 is intentionally conservative: structural index, workspace document ingestion, policy enforcement, and reversible exact maintenance actions first; AI enrichment and broader maintenance actions later.

## Non-Negotiables

- The model never receives the whole vault index, whole graph, or broad note corpus.
- The backend computes small context capsules from a persistent local unified index.
- Structural indexing is whole-vault but manual/scheduled, not performed on every model call.
- `llm-workspace/syllabi` and `llm-workspace/reference` documents are first-class graph nodes through converted `document.md` bundles.
- AI summaries, generated tags, and generated relation hints are incremental by note `sha256`.
- User-visible context selection lives in a tray above the input.
- V1 graph is a Cytoscape 2D work graph.
- 3D Atlas is a separate future stub and cannot become the V1 dependency.
- Vault maintenance uses a queue with apply/reject/edit/diff/revert.
- Safe auto-apply is gated and reversible.
- No hard delete in V1.
- Syncthing informs graph/maintenance through sanitized APIs; raw config is explicit need-to-know only.

## Data Ownership

Source notes stay in the Obsidian vault.

The local index may store structural metadata, generated metadata, and cached summaries, but source notes are not rewritten by default. Generated metadata should prefer sidecar/index storage until a maintenance item is accepted.

Sensitive vault content remains locked by default and excluded from graph, context capsules, AI summary generation, generated tags, and maintenance proposals.

Obsidian frontmatter `sensitivity` is a deterministic local privacy signal:
- `normal` or missing: normal indexing behavior.
- `sensitive`: excluded from graph, context, enrichment, and maintenance while Sensitive is locked. It may be considered only through the same explicit Sensitive-unlock model used elsewhere.
- `private`: never included in graph, context, enrichment, generated relations, maintenance, omissions, or dangling-link surfaces.

The index helper reads only bounded leading frontmatter bytes locally, parses YAML only when the file starts with `---`, and stops at the closing `---` or `...` within the scan cap. This frontmatter pre-scan is never sent to a model. Path policy, Sensitive vault paths, `.modelignore`, `.delamainignore`, and `vault_policy.md` remain authoritative and can only escalate privacy; frontmatter cannot downgrade those restrictions.

## Index Layers

Structural index:
- paths and stable note IDs
- source type: `vault_note`, `workspace_syllabus`, or `workspace_reference`
- sha256 and mtime
- frontmatter keys
- frontmatter `sensitivity` state after bounded local pre-scan
- tags
- headings
- wikilinks, markdown links, backlinks
- archive/active state
- ignore policy state

Generated metadata:
- short summary
- topic tags
- candidate links
- key decisions
- open questions
- stale/error state

Generated metadata is keyed by note ID plus `sha256`. A changed hash invalidates the generated record for that note without forcing full-vault model work.

Generated metadata is stored under:

```text
llm-workspace/vault-index/generated/metadata.json
```

Fresh records can add `generated_tags`, `note_type`, `generated_summary`, `summary_status`, `generated_metadata_state`, and `stale_labels` to graph nodes. Stale records are not used for retrieval scoring or oversized-note summary payloads.

Workspace documents use the existing `delamain_ref` parser and bundle manifests. Raw rich documents are never prompt payloads for vault context; context reads use converted `document.md`.

Upload intake is a separate temporary lane. Browser uploads are stored outside the vault, Sensitive vault, and Syncthing-backed `llm-workspace`; they do not become graph nodes and are not indexed until the user promotes them to `llm-workspace/reference` or `llm-workspace/syllabi`. Prompt attachments from intake are explicit per-run context and use bounded extracted/converted text while preserving the original rich file for download, promotion, or deletion.

## Planned API Surface

```text
GET    /api/vault/graph
GET    /api/vault/graph/neighborhood?path=...&hops=1&limit=80
GET    /api/vault/graph/path?from=...&to=...
GET    /api/vault/note
POST   /api/vault/context/preview
POST   /api/vault/context-capsules       # compatibility alias
GET    /api/vault/enrichment/status
POST   /api/vault/enrichment/run
GET    /api/vault/enrichment/batch
POST   /api/vault/enrichment/batch
GET    /api/vault/enrichment/relations
POST   /api/vault/enrichment/relations/feedback
GET    /api/conversations/{conversation_id}/context/pins
POST   /api/conversations/{conversation_id}/context/pin
POST   /api/conversations/{conversation_id}/context/pins
DELETE /api/conversations/{conversation_id}/context/pin?path=...
DELETE /api/conversations/{conversation_id}/context/pins?path=...
GET    /api/vault/policy/exclusions
POST   /api/vault/policy/exclusions
DELETE /api/vault/policy/exclusions?path=...
POST   /api/vault/folders/init
GET    /api/vault/maintenance/proposals
POST   /api/vault/maintenance/proposals
PATCH  /api/vault/maintenance/proposals/{proposal_id}
GET    /api/vault/maintenance/proposals/{proposal_id}/diff
POST   /api/vault/maintenance/proposals/{proposal_id}/apply
POST   /api/vault/maintenance/proposals/{proposal_id}/reject
POST   /api/vault/maintenance/proposals/{proposal_id}/revert
```

Helper commands:

```text
delamain-vault-index build --json
delamain-vault-index build --auto-ingest --json
delamain-vault-index heartbeat --json
delamain-vault-index init-folder --kind project --name "..." --json
delamain-vault-index init-folder --kind course --name "..." --json
delamain-vault-index init-folder --kind reference --name "..." --json
```

The helper implementation is repo-owned under `delamain_ref/`. Runtime files under `llm-workspace/bin` should be thin wrappers copied from `scripts/helper_wrappers/` and should import the deployed repo package, not carry independent helper implementation code.

`GET /api/vault/graph` returns bounded nodes and edges from the local index. It never returns full note bodies.

`GET /api/vault/graph/neighborhood` returns a bounded N-hop expansion around one indexed graph node. It uses only the existing graph index, treats explicit graph edges as navigation links in either direction, and returns `center`, `nodes`, `edges`, `omitted`, and `policy_omissions`. It never reads note bodies.

`GET /api/vault/graph/path` returns the shortest explicit graph path between two indexed, policy-allowed nodes when available. If both endpoints are allowed but disconnected, it returns `found: false` with empty `nodes` and `edges`. Policy-blocked endpoints return policy errors instead of leaking graph content.

`GET /api/vault/note` returns a bounded preview for an index-known, policy-allowed path or note ID.

`POST /api/vault/context/preview` returns bounded advisory context items the backend recommends for a prompt or selected paths. It does not submit the prompt. `/api/vault/context-capsules` is a compatibility alias for clients that use the earlier contract name.

Context pin endpoints persist explicit user choices for a conversation.

`GET /api/vault/enrichment/status` returns generated metadata cache health and fresh/stale/missing counts.

`POST /api/vault/enrichment/run` runs a bounded task-model enrichment pass. It accepts optional `paths`, `limit`, `force`, and `create_proposals`. It reads only policy-allowed indexed notes/documents, writes generated metadata sidecars, and may create review-first `generated_tag_suggestion` proposals using the exact-replacement maintenance path. Prompt sends never wait for this endpoint.

`GET /api/vault/enrichment/batch` returns the current background enrichment batch status.

`POST /api/vault/enrichment/batch` starts one backend-owned background enrichment batch over missing/stale generated metadata. Only one batch may run at a time. It accepts `limit`, `force`, and `create_proposals`; prompt sends do not wait for it.

`GET /api/vault/enrichment/relations` returns generated relationship candidates plus any accepted/rejected user feedback.

`POST /api/vault/enrichment/relations/feedback` records a user decision for a generated relationship candidate. Accepted generated relations appear as `accepted_generated` graph edges. Rejected generated relations are remembered and suppressed. Relation candidates are visible only when both endpoints are in the current policy-allowed graph and the source generated metadata still matches the indexed node `sha256`.

Maintenance endpoints expose queued proposals and a V1 reversible exact-replacement flow. Unsupported proposals can still be applied as status-only audit records, but source-file writes are limited to allowlisted exact text replacements on indexed Obsidian vault notes. Diff, apply, reject, and revert are available for that allowlist. They do not hard-delete files in V1.

## Graph Response Rules

The current graph endpoint supports bounded `folder`, `tag`, and `limit` filters. Product-level active/working/long-term/archive scope filtering is frontend-side in V1 and must still exclude ignored and Sensitive-locked paths.

Graph responses should include:
- index status and generated timestamp
- policy version/hash when available
- nodes with ID, path, title, source type, tags, folder, archive state, summary availability, stale state, and `sensitivity` when present
- edges with `from`, `to`, `kind`, generated, and accepted state
- generated ownership, duplicate, decision, question, and relation metadata when fresh
- staleness score/reasons/status and sanitized sync status
- result limits and truncation state
- dynamic filters for source types, folders, categories, statuses, placements, and archive states

Graph responses should not include:
- full note bodies
- raw workspace source documents such as PDFs/DOCX
- raw Syncthing config
- Sensitive content while locked
- `sensitivity: private` notes, including their paths, titles, tags, aliases, backlinks, dangling-link targets, and policy omission entries
- links from allowed notes to `private` or locked `sensitive` notes
- ignored paths
- secret-like filenames from policy globs

## Context Capsule Rules

Explicit selected context is the only normal path from vault graph to model context.

Context item fields:
- `id`
- `path`
- `title`
- `mode`: `summary`, `snippet`, `heading`, `full_note`, or `metadata`
- `preview`
- `reason`
- `score`
- `estimated_tokens`
- `sha256`
- `stale`
- `pinned`
- `policy`

Context items must be bounded by count and token/byte budget. Full-note payloads require explicit selection or a visible backend reason.

The frontend must show pinned/selected context in the context tray above the input before submission. Draft preview suggestions are advisory and are not sent unless the user pins/selects them.

Workspace bundle context resolves from converted `document.md` only. Failed, `needs_ocr`, and `needs_reprocess` bundles may appear in graph/maintenance but are excluded from default context preview.

Fresh generated tags and note types participate in deterministic context preview scoring. Fresh generated summaries can be used as the payload for oversized selected notes; stale summaries fall back to source snippets/headings instead of being trusted.

Context preview, selected context resolution, enrichment, generated relation exposure, and maintenance proposals must treat `policy_state: private`, `sensitivity: private`, and locked `sensitivity: sensitive` as blocked even if a stale or hand-edited `graph.json` contains such nodes.

## Heartbeat And Folder Init

The backend owns a light vault-index heartbeat:
- default cadence: 5 minutes
- inactivity delay: 90 seconds after detected source changes
- one active helper run at a time
- status file: `llm-workspace/vault-index/_heartbeat.json`

Heartbeat may run safe document ingestion for supported loose files under `llm-workspace/syllabi` and `llm-workspace/reference`. Unsupported, conflicted, or failed documents become warnings or maintenance proposals.

Folder initialization is deterministic and creates templated Obsidian folders plus matching workspace bundle-ready folders before rebuilding the unified graph.

`POST /api/vault/folders/init` accepts `{ "kind": "project" | "course" | "reference", "name": "..." }`, runs the helper `init-folder` command, audits the action, and returns the helper JSON. The model does not participate in naming, templating, or indexing.

## Maintenance Queue

Queue item actions:
- apply
- reject
- edit
- diff
- revert

Queue item categories:
- summary refresh
- generated tag suggestion
- generated link suggestion
- archive suggestion
- taxonomy suggestion
- conflict-resolution suggestion
- stale metadata cleanup
- workspace ingest warning/error

Safe auto-apply requires allowlist, healthy policy checks, matching `sha256`, reversibility, and no Sensitive/ignored/conflicted/actively edited target.

Implemented V1 file-writing action:

```json
{
  "action": "exact_replace",
  "path": "Projects/DELAMAIN/note.md",
  "old_text": "old exact text",
  "new_text": "new exact text",
  "expected_sha256": "optional-current-source-sha"
}
```

Aliases accepted by the backend are `exact_replace`, `replace_text`, and `patch_text_file`.

V1 exact replacement rules:

- exactly one change per proposal
- target must be an indexed `vault_note`
- target must pass write path policy with Sensitive locked
- target must not be in sanitized Syncthing conflict reports
- `old_text` must occur exactly once
- `expected_sha256`, when present, must match current bytes
- apply writes a timestamped backup under DELAMAIN maintenance backups
- revert re-checks write policy, verifies the current file still matches the applied `new_sha256`, and restores only backups under the DELAMAIN maintenance backup root
- every apply, reject, and revert is audited

Still future in V1: edit UI, open-source actions, snooze, apply-similar, moves, merges, splits, large rewrites, taxonomy rewrites, and archive workflows beyond exact replacements.

## Syncthing Boundary

Graph and maintenance APIs may consume sanitized Syncthing summary/conflict APIs to show:
- sync health
- stale index warning
- conflict warning
- maintenance blocked/deferred state

Raw Syncthing config, API keys, raw logs, and full device configuration are explicit need-to-know only.

Staleness scoring is advisory. Scores and labels drive UI priority and maintenance review; they do not delete, archive, or rewrite source notes by themselves.
