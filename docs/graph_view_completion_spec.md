# DELAMAIN Graph View Completion Spec

Last updated: 2026-04-25

This file is intentionally duplicated in two places:

- Repo copy: `/Users/danielju/Desktop/delamain-assistant.nosync/docs/graph_view_completion_spec.md`
- Vault copy: `/Users/danielju/Desktop/Obsidian.nosync/Vault/Projects/DELAMAIN/graph_view_completion_spec.md`

The copies should stay byte-identical when updated. The repo copy is for implementation agents. The vault copy is for human planning and Obsidian navigation.

## Executive Answer

The vault graph is not one step from complete. The core foundation is now in place: a unified local index, backend graph/note/context APIs, context pins, composer tray, Cytoscape work graph, workspace document nodes, policy exclusions, heartbeat, structured folder init, maintenance-proposal ingestion warnings, and reversible exact-replacement proposal actions.

The remaining work is not foundational indexing. It is product completion:

- path tracing UI polish
- stronger context preview and reranking
- richer maintenance proposal edit/open-source/snooze/apply-similar flows
- AI enrichment for summaries, tags, note types, duplicate/owner-note detection, and stale state
- staleness scoring and UI labels
- Syncthing conflict/status overlays
- browser QA and interaction polish
- later 3D Atlas work

The right next milestone is not to replace SQLite, not to add embeddings, and not to rebuild the graph stack. The right next milestone is to turn the current graph into a dependable work surface and add AI enrichment that produces source-linked summaries, tags, stale-state labels, and safe maintenance proposals.

## Product Definition

DELAMAIN's graph view is a local, inspectable context router over Daniel's Obsidian vault and high-priority `llm-workspace` documents.

It has three jobs:

1. Show the shape of the knowledge base.
2. Let Daniel deliberately attach, detach, pin, exclude, and inspect context before a model call.
3. Help maintain the vault without silently rewriting or exposing sensitive material.

It is not:

- a decorative Obsidian hairball
- a generic RAG-over-everything layer
- a vector database first design
- a persistent-brain marketing feature
- a route for silently sending the full vault index to a model

The model never receives the whole graph or whole index. The backend computes a small candidate set from local metadata and only selected context payloads enter a run.

## Current Implemented State

The current local working tree has the following graph-related pieces implemented or partially implemented.

Backend:

- `GET /api/vault/graph`
- `GET /api/vault/graph/neighborhood?path=...&hops=1&limit=80`
- `GET /api/vault/graph/path?from=...&to=...`
- `GET /api/vault/note?path=...`
- `POST /api/vault/context/preview`
- `POST /api/vault/context-capsules` compatibility alias
- conversation context pin list/add/remove endpoints
- policy exclusion list/add/remove endpoints
- maintenance proposal list/create/update/diff/apply/reject/revert endpoints
- `POST /api/vault/folders/init`
- backend-owned `VaultIndexHeartbeat`
- selected context path resolution during prompt submit
- run-scoped context audit rows
- workspace bundle context resolved from converted `document.md`, not raw PDFs/DOCX/etc.

Index/helper:

- unified `graph.json` over Obsidian vault notes plus `llm-workspace/syllabi` and `llm-workspace/reference`
- node `source_type` metadata for `vault_note`, `workspace_syllabus`, and `workspace_reference`
- structural metadata for titles, paths, tags, aliases, folder/category, headings, links, backlinks, status, placement, mtime, size, and hashes
- root `vault_policy.md`, `.modelignore`, `.delamainignore`, hard restrictions, and skip reasons before content reads
- `delamain-vault-index build --json`
- `delamain-vault-index build --auto-ingest --json`
- `delamain-vault-index heartbeat --json`
- `delamain-vault-index status --json`
- `delamain-vault-index init-folder --kind project|course|reference --name "..."`

Frontend:

- Vault panel in the right side panel
- tabs for graph, list, preview, maintenance, and Atlas placeholder
- Cytoscape 2D work graph component
- search/filter over loaded graph nodes
- dynamic source filters from graph metadata
- dynamic folder/category/status/placement/archive filters from graph metadata
- note preview
- preview inlinks/outlinks from the loaded graph
- 1-hop and 2-hop neighborhood loading from preview
- neighbor pin-to-context affordances
- pin-to-context affordances
- policy exclusion toggle
- maintenance proposal list with diff/apply/reject/revert actions for safe exact replacements
- new structured folder control in the maintenance tab
- composer context tray above the input bar

Operational status from the current Mac corpus:

- indexed files: 306
- vault notes: 303
- workspace bundles: 3
- graph edges: 370
- skipped paths: 5
- status command runtime: about 0.16 seconds
- full structural build runtime: about 0.36 seconds

This performance is good enough that the next work should focus on correctness and UX, not database migration or premature indexing infrastructure.

## Core Invariants

These rules are not optional.

- Sensitive remains locked by default.
- Sensitive content is not included in graph, context capsules, summaries, generated tags, or maintenance proposals unless explicitly unlocked through conversation controls.
- Raw workspace source documents are not prompt payloads. Use converted `document.md`.
- Ignore rules are applied before content reads.
- The frontend is not a security boundary.
- The model does not decide what gets indexed.
- The model does not receive the entire graph/index.
- Indexing does not run on every prompt send.
- Context preview does not call a model in V1.
- Context preview returns candidates only; prompt submit resolves selected items.
- Full notes require explicit selection or a narrow visible reason.
- Maintenance writes must be reversible.
- V1 source-file writes are limited to one exact text replacement per proposal on indexed vault notes.
- No hard delete in V1.
- Generated metadata is labeled as generated and source-linked.
- Rejected generated edges or tags should be remembered.

## Architecture

The graph stack has five layers.

1. Source corpus

- Obsidian vault notes
- root `vault_policy.md`
- `.modelignore`
- `.delamainignore`
- `llm-workspace/syllabi`
- `llm-workspace/reference`
- converted workspace bundle files
- helper manifests and extraction metadata

2. Structural index

- built by `delamain-vault-index`
- stored under `llm-workspace/vault-index/`
- persistent across model calls
- rebuilt manually, by direct action, folder init, or heartbeat
- records policy/hash/staleness metadata

3. Backend graph/context router

- exposes bounded graph APIs
- enforces path policy and Sensitive gates
- computes deterministic context candidates
- resolves selected context into actual model messages
- records what was loaded and why

4. Frontend work surface

- right-side Vault panel
- composer tray above input
- graph/list/preview/maintenance/Atlas tabs
- pin, exclude, preview, remove, apply/reject controls

5. AI enrichment and maintenance

- later incremental summaries, tags, classifications, stale markers, duplicate proposals, archive proposals
- keyed by `sha256`
- never blocks prompt send
- creates maintenance proposals rather than silently rewriting source notes

## Data Model

Every graph node should normalize toward this shape:

```json
{
  "id": "stable-id",
  "path": "Projects/DELAMAIN/note.md",
  "title": "Note Title",
  "source_type": "vault_note",
  "source_root": "/absolute/root",
  "category": "Projects",
  "folder": "Projects/DELAMAIN",
  "bundle_id": null,
  "document_md": null,
  "source_path": null,
  "converter": null,
  "status": "fresh",
  "placement": "normal",
  "archive_state": "active",
  "pinned": false,
  "tags": ["project/delamain"],
  "aliases": ["Alias"],
  "headings": ["Heading"],
  "mtime": "2026-04-25T00:00:00Z",
  "size_bytes": 1234,
  "sha256": "sha256...",
  "incoming_link_count": 3,
  "outgoing_link_count": 5,
  "dangling_link_count": 0,
  "summary_state": "missing",
  "generated_metadata_state": "missing",
  "stale_score": 0.12,
  "warnings": []
}
```

Every edge should normalize toward this shape:

```json
{
  "from": "source-node-id",
  "to": "target-node-id",
  "kind": "wikilink",
  "explicit": true,
  "generated": false,
  "confidence": null,
  "source_path": "Projects/DELAMAIN/note.md",
  "source_heading": "Optional Heading",
  "status": "accepted"
}
```

Important edge kinds:

- `wikilink`
- `markdown_link`
- `embed`
- `backlink`
- `tag`
- `folder`
- `property`
- `workspace_bundle`
- `generated_candidate`
- `accepted_generated`
- `rejected_generated`

Generated edges are advisory until accepted. Rejected generated edges should be persisted so DELAMAIN does not keep suggesting the same bad relationship.

## Index Lifecycle

Indexing should be whole-corpus structural indexing, but not on every prompt.

Triggers:

- manual helper command
- backend direct action
- structured folder init
- heartbeat after source changes and inactivity
- explicit user refresh from the UI

Heartbeat defaults:

- cadence: 5 minutes
- inactivity window: 90 seconds
- at most one active helper run
- status file: `llm-workspace/vault-index/_heartbeat.json`

Heartbeat should do:

- stat source roots
- detect source/policy/manifest/index changes
- run helper when stable
- safe auto-ingest for supported loose docs in expected workspace roots
- write status
- create maintenance proposals for warnings/errors

Heartbeat should not do yet:

- model summaries
- generated tags
- generated relationship inference
- broad source-note rewrites
- deletion

## Ignore And Exclusion Policy

Ignore rules must be deterministic and content-safe.

Order:

1. backend hard restrictions
2. Sensitive lock
3. root `vault_policy.md`
4. `.modelignore`
5. `.delamainignore`
6. path/name fallback conventions

The important rule is that exclusions are applied before reading note content. A file can be excluded by path or glob without needing to inspect its frontmatter or body.

User-facing exclusion paths:

- graph node Exclude action
- note preview Exclude action
- maintenance queue Exclude similar action, future
- policy exclusions editor, future
- direct action, future

Do not rely on frontmatter as the only exclusion mechanism. It requires reading the note body, which defeats the point for content that should not be read.

## Context Preview Flow

Preview is a dry run, not a model call.

Flow:

1. User types prompt.
2. Frontend sends the draft prompt to preview endpoint.
3. Backend tokenizes/parses prompt locally.
4. Backend checks unified graph metadata.
5. Backend scores deterministic candidates.
6. Backend returns candidate capsules with reasons.
7. Frontend renders them in the composer tray.
8. User removes, keeps, pins, or previews items.
9. User submits.
10. Frontend sends selected capsule paths/IDs.
11. Backend resolves only selected items into model messages.
12. Backend records selected context with `sha256`, bytes, mode, truncation, and reason codes.

The preview endpoint may inspect metadata, headings, tags, aliases, folders, and generated sidecar metadata. It should not send anything to a model.

Candidate reasons should stay structured:

- `exact_title_match`
- `alias_match`
- `path_match`
- `folder_match`
- `subfolder_match`
- `heading_match`
- `tag_match`
- `wikilink_neighbor`
- `backlink_neighbor`
- `pinned_context`
- `recent_context_loaded`
- `workspace_doc_priority`
- `syllabus_priority`
- `reference_priority`
- `synonym_match`
- `generated_tag_match`
- `active_project_boost`
- `archive_penalty`

## Context Ranking

V1 ranking should remain deterministic.

Suggested ranking order:

1. explicit current selection or pin
2. exact path/title/alias match
3. active project/course match
4. heading match
5. tag match
6. folder/subfolder match
7. direct wikilink/backlink neighbor
8. workspace syllabus/reference boost
9. synonym map match
10. lexical fuzzy match over titles/headings/aliases/tags
11. recent context-load boost
12. archive/stale/conflict penalty

Workspace documents should outrank ordinary vault notes when the prompt clearly asks about a syllabus, class, API docs, reference docs, assignment requirements, or external document content. Vault project notes should outrank workspace docs when the prompt clearly targets a DELAMAIN project, human planning note, or Obsidian path.

## Semantic Give Without Embeddings

Before embeddings, add controlled semantic flexibility.

Sources:

- root `vault_policy.md` synonym map
- folder taxonomy hints
- generated tags once AI enrichment exists
- note type classification
- alias fields
- headings
- prior context-load history

Example:

```yaml
synonyms:
  schedule:
    - calendar
    - timeline
    - due dates
    - classes
    - syllabus
    - daily notes
  graph:
    - atlas
    - network
    - vault view
    - context router
```

This should be implemented as metadata expansion, not model guessing over the full corpus.

Optional later model reranking is allowed only on a bounded metadata shortlist. The model must not receive all note bodies, the full graph, or the full index for reranking.

## Payload Modes

Context payloads should use these modes:

- `metadata`: title/path/tags/headings only
- `snippet`: selected source excerpt
- `summary`: cached generated summary
- `full_note`: complete body within byte/token limits
- `workspace_document`: converted `document.md` snippet or full small doc
- `stale_summary`: cached summary flagged stale

Default behavior:

- short explicitly selected notes may use `full_note`
- large notes use summary/snippet
- stale summaries use fallback headings/snippets
- workspace documents use converted `document.md`
- failed or needs-OCR bundles appear in graph/maintenance but are excluded from default context

The old 8 KB full-note threshold is a pragmatic default, not a permanent law. It is small enough for predictable prompt cost and large enough for most concise notes. Make it configurable.

## Composer Tray

The tray is a security and correctness boundary.

Location:

- directly above the input bar
- compact by default
- expandable into cards/details

Each item should show:

- title
- path
- source type
- payload mode
- estimated tokens/bytes
- freshness/stale state
- privacy tier
- reason selected
- remove button
- preview button
- pin/unpin state
- warning state

The tray should distinguish:

- preview candidates
- pinned context
- manually selected context
- stale context
- excluded context
- Sensitive-locked blocked context

If the tray is unavailable, DELAMAIN should not silently attach vault content.

## Graph Panel Layout

Placement:

- existing right side panel
- opened by the Network/Vault icon
- no new top-level route needed for V1

Tabs:

- Graph
- List
- Preview
- Maintenance
- Atlas

Graph tab:

- Cytoscape 2D graph
- search field
- dynamic filters
- node click to preview
- node action menu for pin/exclude/open/backlinks/outlinks

List tab:

- dense sortable list of filtered nodes
- source type, path, status, link counts
- quick pin/exclude

Preview tab:

- bounded note preview
- source metadata
- backlinks/outlinks
- pin and exclude controls
- source-open action, future

Maintenance tab:

- structured folder init
- policy exclusions
- maintenance proposals
- heartbeat status, future
- index status, future

Atlas tab:

- placeholder in V1
- later 3D map
- no independent context injection path

## Dynamic Filters

Filters must be derived from graph metadata, not hardcoded.

Baseline filters:

- All
- Vault Notes
- Syllabi
- Reference
- Pinned
- Stale / Needs Review
- Archive / Long-term

Generated filter groups:

- source types
- folders
- subfolders
- categories
- tags
- statuses
- placements
- archive states
- bundle statuses
- generated metadata states

If Daniel creates a new templated folder or category, it should appear automatically after indexing. No frontend code change should be required for each new folder.

## N-Hop Navigation

N-hop linked-note loading is implemented for V1.

Implementation target:

Current behavior:

- select a node
- inspect inlinks/outlinks from the currently loaded graph
- load 1-hop explicit neighbors from the backend neighborhood endpoint
- load 2-hop explicit neighbors from the backend neighborhood endpoint
- show omitted node/link/policy counts when present
- pin individual neighbors to the composer tray explicitly
- never convert expanded graph neighborhoods into model context automatically

Remaining polish:

- add a dedicated shortest-path UI between two selected nodes
- show edge reasons directly beside each neighbor
- add an "add visible neighbors to tray" action with explicit confirmation

Implemented API:

```text
GET /api/vault/graph/neighborhood?path=...&hops=1&limit=80
GET /api/vault/graph/path?from=...&to=...
```

Neighborhood response should contain:

- center node
- nodes
- edges
- omitted counts
- reason metadata
- policy omissions

Context preview may use 1-hop expansion, but only as a scoring signal unless the user explicitly selects neighbors.

## Maintenance Queue Completion

Current state: queue exists, heartbeat can create proposals, and V1 supports diff/apply/reject/revert for allowlisted exact text replacements on indexed vault notes. Unsupported proposal actions remain status-only or staged for later review-first implementations.

Completion target:

- apply
- reject
- edit
- preview diff
- open source
- snooze
- apply similar
- revert

Implemented V1 exact replacement behavior:

- proposal payload uses `action: exact_replace` with `path`, `old_text`, `new_text`, and optional `expected_sha256`
- aliases `replace_text` and `patch_text_file` are accepted by the backend
- exactly one replacement per proposal
- target must be an indexed `vault_note`
- Sensitive stays locked during maintenance writes
- path policy is checked before diff, apply, and revert
- `old_text` must match exactly once
- stale `expected_sha256` blocks diff/apply
- apply creates a timestamped backup under DELAMAIN maintenance backups
- revert checks the current file hash against the applied new hash before restoring
- revert only restores backups from DELAMAIN's maintenance backup root
- apply, reject, and revert are audited

Proposal schema should include:

- action type
- target paths
- title
- reason
- confidence
- evidence
- exact diff or move plan
- risk
- backup plan
- rollback metadata
- status
- created by
- source hash
- policy gates

Safe auto-apply candidates:

- generated tags
- link normalization
- stale markers
- minor exact-match cleanup
- low-risk archive moves

Always stage for review:

- broad moves
- merges/splits
- taxonomy changes
- large rewrites
- conflicted files
- ambiguous archive actions
- anything touching Sensitive

No hard delete in V1.

Remaining maintenance UX:

- edit proposal before apply
- open source note from a proposal
- snooze proposal
- apply similar
- preview move plans
- revert move/archive actions after those actions are implemented

## AI Enrichment

AI enrichment is not required for the graph foundation, but it is required for the graph to feel intelligent.

Use backend `task_model`.

Tasks:

- note summary
- generated tags
- note type classification
- owner-note detection
- duplicate detection
- stale-state candidate
- archive candidate
- generated relationship candidate
- unresolved question extraction
- decision extraction

Rules:

- run incrementally
- key by `sha256`
- never block prompt send
- never enrich ignored/Sensitive-locked paths
- store generated metadata under `llm-workspace/vault-index/`
- do not write generated tags to source notes by default
- source-link every generated claim
- put writes through maintenance proposals

Recommended generated metadata path:

```text
llm-workspace/vault-index/generated/metadata.json
```

Current G4 slice:

- `GET /api/vault/enrichment/status`
- `POST /api/vault/enrichment/run`
- `GET /api/vault/enrichment/batch`
- `POST /api/vault/enrichment/batch`
- `GET /api/vault/enrichment/relations`
- `POST /api/vault/enrichment/relations/feedback`
- generated metadata sidecar keyed by graph path and source `sha256`
- task-model JSON enrichment for summary, generated tags, note type, and stale labels
- owner-note, duplicate, relation, decision, and open-question fields in generated metadata
- graph nodes expose `generated_metadata_state`, `summary_status`, `generated_summary`, `generated_tags`, `note_type`, and `stale_labels`
- graph nodes expose `owner_notes`, `duplicate_candidates`, `relation_candidate_count`, `decisions`, and `open_questions`
- generated relationship candidates can be accepted or rejected
- accepted generated relations appear as `accepted_generated` graph edges
- rejected generated relations are remembered and suppressed
- deterministic context preview scores fresh generated tags and note types
- oversized selected notes can use fresh generated summaries instead of truncated source bodies
- generated tag suggestions can create exact-replacement maintenance proposals for review
- prompt send is not blocked by enrichment
- background enrichment batches can process missing/stale generated metadata without blocking prompt sends

Still future in G4:

- richer UI for reviewing generated relationship/duplicate/owner suggestions

## Staleness

Staleness is a review-priority signal, not a deletion command.

Hard flags:

- source `sha256` changed since summary
- sync conflict
- restricted path
- Sensitive locked
- ignored path
- failed workspace bundle
- needs OCR

Weighted signals:

- modified time
- summary age
- archive folder
- stale frontmatter/status
- backlinks count
- pinned state
- recent context-load history
- dangling links
- duplicate ownership candidates
- contradiction candidates
- source bundle converter status

Suggested output labels:

- fresh
- changed
- stale summary
- needs review
- conflicted
- blocked
- archived

Scores should drive UI priority and maintenance queue ordering. They should not trigger deletion.

## Syncthing Integration

Syncthing should inform graph state through sanitized backend APIs.

Show:

- sync health
- conflict count
- path-level conflict warning
- stale index warning
- maintenance blocked/deferred state

Do not auto-preload:

- raw Syncthing config
- device IDs
- API keys
- raw logs
- full folder configuration

Syncthing config/status can be exposed through an explicit admin view later, but it should not become default model context.

## Structured Folder Init

The UI now has a structured folder control. The completion target is to make this ergonomic enough that filename conventions become optional rather than required.

Kinds:

- project
- course
- reference

Expected behavior:

- user enters a natural name
- backend helper creates normalized folder/files
- helper creates matching workspace-ready folder when relevant
- helper rebuilds graph
- frontend reloads graph and filters

Expected Obsidian project layout:

```text
Projects/<Name>/
  INDEX.md
  state.md
  decisions.md
  tasks.md
  archive/
```

Expected course layout:

```text
Projects/Courses/<Name>/
  INDEX.md
  state.md
  decisions.md
  tasks.md
  archive/
```

Expected workspace layout for syllabi/reference:

```text
llm-workspace/syllabi/<bundle-or-category>/
llm-workspace/reference/<bundle-or-category>/
```

Later improvement:

- allow picking parent folder/category from existing graph metadata
- show preview of files to be created
- allow open-after-create
- add "process documents now" option

## 3D Atlas

The 3D Atlas should stay separate from the V1 work graph.

Honest recommendation:

- keep Cytoscape as the default operational graph
- use Atlas for exploration and spatial memory only
- do not use Atlas as the primary context selection UI until the 2D graph is mature

Atlas V1 goals:

- full-bleed Three.js or `3d-force-graph`
- spherical or orbital layout
- clusters by project/course/topic/source type
- time layer toggle
- click node to focus
- side preview uses the same backend note API
- pin action uses the same composer tray
- no separate context path

Atlas risks:

- 3D graphs are visually impressive but slower for exact work
- text labels become hard to read
- selection precision is worse than 2D
- mobile ergonomics are harder
- performance degrades as node count grows

Acceptance rule: Atlas is allowed when it adds orientation without replacing the precise 2D work graph.

## SQLite Decision

SQLite remains the right database for this stage.

Reasons:

- DELAMAIN is single-user
- local-first state is desired
- WAL is already enabled
- the current graph index is mostly file-backed JSON plus lightweight relational state
- operational complexity stays low
- backups and inspection are simple
- security surface is smaller than a network database

Do not migrate just for graph functionality.

Consider Postgres later if:

- multiple users become real
- concurrent writes become heavy
- remote analytics are needed
- graph/query state moves fully into SQL
- event volume grows beyond SQLite comfort
- vector search becomes a first-class server feature

Migration would be manageable but not free. The backend already centralizes database access through `Database` and migrations, which helps. The harder work would be SQL dialect differences, async driver changes, deployment, backups, local dev setup, and retesting SSE/event semantics.

Near-term SQLite improvements:

- add targeted indexes when queries show pressure
- consider FTS5 for local lexical search
- keep write batches transactional
- keep graph structural files in JSON until a SQL graph store is clearly useful
- avoid storing full note bodies in SQLite

## Performance Plan

Current structural indexing is fast. The bottlenecks will not be basic Markdown scanning at current scale.

Likely future bottlenecks:

- rich document conversion
- OCR
- repeated hashing of large documents
- graph rendering with too many visible nodes
- AI enrichment calls
- maintenance diff generation

Optimizations to add in order:

1. changed-file manifest keyed by path, mtime, size, and sha256
2. skip rewriting unchanged index artifacts
3. queue rich document conversion separately from graph rebuild
4. cap graph API node/edge responses by scope
5. add neighborhood endpoint for focused expansion
6. cache generated summaries/tags by sha256
7. add FTS5 if lexical search becomes slow
8. add model rerank only on bounded metadata shortlists
9. consider local embeddings only after deterministic retrieval misses important cases

Do not optimize by sending more data to the model.

## Completion Phases

### Phase G1: Graph Work Surface Completion

Owner scope:

- frontend Vault panel
- backend graph API filters
- tests

Tasks:

- refine active/archive/project/course filters as real dynamic filter chips
- refine folder/subfolder filter groups
- refine status/placement/archive-state filters
- add graph node action menu
- refine backlinks/outlinks sections in preview
- add graph empty/error/stale states
- add browser QA for graph, list, preview, pin, exclude, folder init

Acceptance:

- adding a new structured folder and rebuilding graph makes the folder appear as a filter
- clicking a node reliably previews it
- pinning affects composer tray
- excluding affects policy and subsequent preview

### Phase G2: N-Hop Neighborhoods

Owner scope:

- backend graph neighborhood/path endpoints
- frontend graph expansion UI
- tests

Tasks:

- harden 1-hop and 2-hop neighborhood UI
- refine omitted counts and policy omissions display
- keep neighbor expansion separate from selected context
- add path tracing between nodes
- add "add neighbors to tray" as explicit action only

Acceptance:

- graph exploration is useful without loading the whole graph
- expanded nodes never silently become model context

### Phase G3: Maintenance Queue Real Actions

Owner scope:

- maintenance APIs
- file patch/move safety
- frontend queue UI
- tests

Tasks:

- ~~add proposal preview diff~~
- ~~add reject endpoint if needed~~
- add edit flow
- ~~add safe apply for allowlisted exact changes~~
- ~~add backup/rollback metadata~~
- ~~add revert endpoint~~
- ~~add audit events~~
- broaden conflict/Syncthing-aware blocking beyond current Sensitive/ignored/changed-hash gates
- add open source, snooze, apply similar, and move/archive previews

Acceptance:

- exact replacement proposals can be previewed, applied, audited, and reverted
- unsafe actions stay staged
- no hard delete exists

### Phase G4: AI Enrichment

Owner scope:

- task model enrichment worker
- generated metadata cache
- invalidation
- maintenance proposal generation
- tests

Tasks:

- ~~create generated metadata schema~~
- ~~generate summaries/tags/note types incrementally~~
- ~~invalidate by sha256~~
- ~~expose summary/tag state in graph~~
- ~~use generated tags in deterministic preview~~
- ~~create proposals for high-confidence frontmatter writes~~
- ~~add owner-note and duplicate detection~~
- ~~add generated relation candidates with accept/reject memory~~
- ~~add unresolved question and decision extraction~~
- ~~add background enrichment queue~~
- add richer UI for generated relationship/duplicate/owner review

Acceptance:

- ~~prompt send is never blocked by enrichment~~
- ~~stale summaries are labeled~~
- ~~generated metadata is source-linked~~
- ~~accepted/rejected generated relationships are remembered~~
- generated maintenance proposals remain review-first

### Phase G5: Staleness And Syncthing Overlay

Owner scope:

- backend staleness scoring
- sanitized Syncthing integration
- UI labels
- tests

Tasks:

- ~~compute hard flags and weighted stale scores~~
- ~~expose stale/conflict status in graph nodes~~
- show heartbeat status in Maintenance tab
- ~~show sync-conflict warnings~~
- ~~block unsafe maintenance actions~~ for exact replacement writes with known Syncthing conflicts

Acceptance:

- ~~stale/conflicted nodes are visible~~
- scores affect review priority, not deletion
- raw Syncthing config is not leaked

### Phase G6: Atlas Prototype

Owner scope:

- Atlas tab only
- Three.js or `3d-force-graph`
- browser checks

Tasks:

- render graph subset in 3D
- cluster by metadata
- click node to focus
- reuse preview/pin APIs
- add performance cap
- verify desktop and mobile screenshots

Acceptance:

- Atlas is visually useful and nonblocking
- 2D graph remains default
- Atlas has no independent context injection route

## Suggested Subagent Batches

Use separate agents only when write scopes are disjoint.

Batch 1: Backend graph filters and neighborhoods

- files: backend vault API/security graph modules and backend tests
- output: dynamic filters, neighborhood endpoint, path endpoint, tests

Batch 2: Frontend Vault panel graph/list/preview polish

- files: `VaultPanel`, `VaultGraphCanvas`, frontend API/types
- output: richer filters, node actions, backlinks/outlinks UI, browser QA

Batch 3: Maintenance real actions

- files: maintenance API, DB migrations, file safety helpers, queue UI, tests
- output: diff/apply/reject/revert for allowlisted actions

Batch 4: AI enrichment

- files: enrichment worker/cache, helper metadata schema, tests
- output: summaries/tags/note types keyed by sha256

Batch 5: Docs and contracts

- files: repo docs, frontend contract, vault docs
- output: keep specs aligned with implemented API

Do not run two writing agents on `VaultPanel.tsx`, `vault.py`, or DB migrations at the same time.

## Verification Matrix

Backend:

- `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_vault_api.py`
- `PYTHONPATH=. .venv/bin/python -m pytest -q`
- Sensitive locked tests
- ignored path tests
- workspace bundle context tests
- context preview does not rebuild index
- selected tray items are the only context sent

Helper:

- `delamain-vault-index status --json`
- `delamain-vault-index build --json`
- `delamain-vault-index heartbeat --json`
- helper tests under `llm-workspace/bin/tests`

Frontend:

- `cd frontend && pnpm lint`
- `cd frontend && pnpm exec tsc --noEmit`
- `cd frontend && pnpm build`
- browser smoke for graph/list/preview/maintenance/tray
- screenshots for desktop/mobile once Atlas exists

Safety:

- Sensitive remains locked
- ignored paths are skipped before content reads
- raw workspace source docs are not model context
- full index is not sent to model
- maintenance writes are reversible

## Definition Of Done

The graph view is complete for V1 when:

- the right panel can browse, filter, preview, pin, exclude, and inspect graph nodes
- composer tray reliably shows all selected context before submit
- backend context preview is deterministic, bounded, and source-reasoned
- selected context is the only vault/workspace context sent to the model
- workspace syllabi/reference docs are first-class nodes
- new structured folders can be created from the UI and appear in graph filters after indexing
- maintenance proposals can be previewed, applied when safe, rejected, and reverted
- staleness/conflict states are visible
- Sensitive and ignore policies are enforced before content reads
- full backend and frontend checks pass, excluding unrelated worker-script work

V1 does not require embeddings, local vector search, or 3D Atlas.

## Recommended Next Task

The highest-value next task is the dedicated UI/UX session: review UI for generated relation/duplicate/owner suggestions, enrichment batch controls, and staleness/sync filters.

Reason:

- generated ownership, duplicate, relation, decision, open-question, and staleness metadata now exist in the backend
- accepted/rejected relation memory exists, but the UI does not yet make relation review ergonomic
- staleness/sync status exists on nodes, background enrichment status exists, and dedicated UI controls are now the missing layer

Second priority is broader maintenance planning: edit/snooze/apply-similar, open-source actions, and move/archive plan previews.

Third priority is Phase G1/G2 graph navigation polish: node action menus, shortest-path UI, and browser QA for the new filters, inlinks/outlinks, and N-hop neighborhoods.

Fourth priority is the remaining maintenance UX: edit proposal, open source, snooze, apply similar, and move/archive plan previews.
