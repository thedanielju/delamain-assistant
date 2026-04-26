export type ContextMode = 'Normal' | 'Blank-slate' | 'Incognito'

export type ToolCallStatus = 'running' | 'success' | 'error'

export interface ToolCall {
  id: string
  name: string
  summary: string
  durationMs?: number
  status: ToolCallStatus
  args?: Record<string, unknown>
  stdout?: string
  stderr?: string
  expanded?: boolean
  accentColor?: 'blue' | 'green' | 'pink'
}

export type MessageRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  streaming?: boolean
  toolCalls?: ToolCall[]
  /** tool calls rendered BEFORE this message chunk */
  toolCallsBefore?: ToolCall[]
  activeToolCallId?: string
  /** run metadata */
  runId?: string
  runStatus?: RunStatus
  error?: string
}

export type RunStatus =
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'cancelled'

export interface Conversation {
  id: string
  title: string
  timestamp: string
  contextMode?: ContextMode
  modelRoute?: string | null
  incognitoRoute?: boolean
  sensitiveUnlocked?: boolean
  folderId?: string | null
  archived?: boolean
  messages: ChatMessage[]
  active?: boolean
  runStatus?: RunStatus
}

export interface Folder {
  id: string
  name: string
  parentId: string | null
}

export interface ContextFile {
  id: string
  name: string
  path: string
  bytes?: number
  hash?: string
  tokenEstimate?: number
  mode?: ContextMode
  /** attached by user for this message */
  attached?: boolean
}

export interface Tool {
  id: string
  name: string
  description: string
  enabled: boolean
  category?: 'read' | 'write' | 'ssh' | 'web' | 'other'
  approvalPolicy?: 'auto' | 'confirm'
}

// ── Health ──────────────────────────────────────────────────────────────────

export type HealthStatus = 'ok' | 'degraded' | 'error' | 'unknown'

export interface HealthEntry {
  id: string
  label: string
  status: HealthStatus
  detail?: string
  lastChecked?: string
}

export interface HealthDisk {
  mountpoint: string
  device: string
  fstype: string
  totalMb: number
  usedMb: number
  freeMb: number
  percentUsed: number
}

export interface HealthSystemMetrics {
  delamainBackend: {
    uptimeSeconds: number
    rssMb: number
    cpuPercent1Min: number
    numThreads: number
    pid: number
  }
  host: {
    hostname: string
    kernel: string
    loadAvg: {
      one: number | null
      five: number | null
      fifteen: number | null
    }
    memoryTotalMb: number
    memoryAvailableMb: number
    disks: HealthDisk[]
  }
  tmuxWorkers: {
    count: number
    rssMbTotal: number
  }
}

// ── Direct actions ───────────────────────────────────────────────────────────

export type DirectActionGroup =
  | 'health'
  | 'ref'
  | 'vault_index'
  | 'sync_guard'
  | 'winpc'
  | 'subscription'

export interface DirectAction {
  id: string
  label: string
  group: DirectActionGroup
  description?: string
  status?: 'idle' | 'running' | 'done' | 'error'
  result?: string
}

// ── Workers ──────────────────────────────────────────────────────────────────

export type WorkerStatus = 'running' | 'stopped' | 'idle' | 'capturing'

export interface Worker {
  id: string
  name: string
  type:
    | 'opencode'
    | 'claude'
    | 'codex'
    | 'gemini'
    | 'tmux'
    | 'winpc_shell'
    | 'winpc_opencode'
    | 'winpc_claude'
    | 'winpc_codex'
    | 'winpc_gemini'
    | 'generic'
  host: 'local' | 'serrano' | 'winpc'
  status: WorkerStatus
  startedAt?: string
  lastActivity?: string
  output?: string
}

export interface WorkerTypeOption {
  id: string
  label: string
  host: 'serrano' | 'winpc' | 'local'
}

// ── Theme ────────────────────────────────────────────────────────────────────

export type ThemeName =
  | 'default'
  | 'rose'
  | 'mint'
  | 'lavender'
  | 'peach'
  | 'sky'
  | 'mauve'

export interface ThemeConfig {
  name: ThemeName
  label: string
  accentBlue: string
  accentGreen: string
  accentPink: string
  accentPurple: string
  primary: string
}

// ── Right panel ───────────────────────────────────────────────────────────────

export type RightPanelId = 'settings' | 'health' | 'workers' | 'usage' | 'syncthing' | 'vault' | null

// ── Vault index ───────────────────────────────────────────────────────────────
// Shape matches the active vault graph and context endpoints.

export interface VaultNode {
  id: string
  path: string
  title: string
  tags: string[]
  aliases: string[]
  mtime: string
  bytes: number | null
  source_type?: 'vault_note' | 'workspace_syllabus' | 'workspace_reference' | string
  category?: string | null
  bundle_id?: string | null
  document_md?: string | null
  source_path?: string | null
  converter?: string | null
  status?: string | null
  placement?: string | null
  pinned?: boolean
  folder?: string | null
  incoming_link_count?: number
  dangling_link_count?: number
  archive_state?: string | null
  warnings?: string[]
  generated_metadata_state?: 'fresh' | 'stale' | 'missing' | string
  summary_status?: 'fresh' | 'stale' | 'missing' | string
  generated_summary?: string | null
  generated_tags?: string[]
  note_type?: string | null
  stale_labels?: string[]
  owner_notes?: string[]
  duplicate_candidates?: Array<Record<string, unknown>>
  relation_candidate_count?: number
  decisions?: string[]
  open_questions?: string[]
  stale_score?: number
  stale_reasons?: string[]
  staleness_status?: 'fresh' | 'needs_review' | 'stale' | 'conflicted' | string
  sync_status?: 'ok' | 'conflicted' | string
}

export interface VaultEdge {
  from: string
  to: string
  kind: 'wikilink' | 'tag' | 'backlink' | 'embed' | 'folder' | string
  generated?: boolean
  accepted?: boolean
  relation_type?: string | null
  reason?: string | null
  confidence?: number | null
}

export interface VaultGraph {
  nodes: VaultNode[]
  edges: VaultEdge[]
  generated_at?: string
  index?: {
    status?: string
    stale?: boolean
    generated_at?: string | null
    indexed_count?: number
    vault_note_count?: number
    workspace_bundle_count?: number
    skipped_count?: number
    warnings?: string[]
  }
  filters?: {
    source_types?: string[]
    folders?: string[]
    categories?: string[]
    statuses?: string[]
    placements?: string[]
    archive_states?: string[]
  }
}

export interface VaultGraphParams {
  folder?: string
  tag?: string
  query?: string
  limit?: number
}

export interface VaultGraphNeighborhood {
  center?: VaultNode | null
  nodes: VaultNode[]
  edges: VaultEdge[]
  hops?: number
  omitted?: {
    nodes?: number
    edges?: number
    policy?: number
  }
  policy_omissions?: Array<{ path?: string; reason?: string }>
}

export interface VaultGraphPathResult {
  found: boolean
  nodes: VaultNode[]
  edges: VaultEdge[]
  omitted?: {
    nodes?: number
    edges?: number
    policy?: number
  }
}

export interface VaultContextItem {
  id: string
  path: string
  title: string
  mode?: 'full_note' | 'summary' | 'snippet' | 'metadata' | string
  reason?: string
  reasons?: string[]
  preview?: string
  bytes?: number | null
  tokenEstimate?: number | null
  estimated_tokens?: number | null
  score?: number | null
  sha256?: string | null
  stale?: boolean
  tags?: string[]
  source_type?: string
  category?: string | null
  pinned?: boolean
  excluded?: boolean
  exclusionReason?: string | null
}

export interface VaultNoteDetail {
  path: string
  title: string
  content: string
  bytes?: number | null
  sha256?: string | null
  tags: string[]
  backlinks: string[]
  source_type?: string
  aliases?: string[]
  mtime?: string | null
  pinned?: boolean
  excluded?: boolean
}

export interface VaultPolicyExclusion {
  id: string
  path: string
  reason?: string | null
  createdAt?: string | null
}

export interface VaultMaintenanceProposal {
  id: string
  title: string
  summary?: string
  description?: string | null
  kind?: string
  path?: string | null
  paths?: string[]
  payload?: Record<string, unknown>
  risk?: 'low' | 'medium' | 'high' | string
  status?: 'proposed' | 'running' | 'applied' | 'rejected' | 'reverted' | 'dismissed' | 'error' | string
  command?: string | null
}

export interface VaultPinsResponse {
  paths?: string[]
  pins?: Array<string | Partial<VaultContextItem>>
  items?: Array<string | Partial<VaultContextItem>>
  generated_at?: string
}

export interface VaultContextPreview {
  items?: Array<string | Partial<VaultContextItem>>
  paths?: string[]
  token_estimate?: number | null
  generated_at?: string
}

export interface VaultPinMutationResponse {
  paths?: string[]
  pins?: Array<string | Partial<VaultContextItem>>
  items?: Array<string | Partial<VaultContextItem>>
  status?: string
}

export interface VaultPolicyExclusionsResponse {
  exclusions?: Array<string | Partial<VaultPolicyExclusion>>
  items?: Array<string | Partial<VaultPolicyExclusion>>
  paths?: string[]
  generated_at?: string
}

export interface VaultPolicyExclusionMutationResponse {
  exclusion?: Partial<VaultPolicyExclusion>
  exclusions?: Array<string | Partial<VaultPolicyExclusion>>
  status?: string
}

export interface VaultMaintenanceProposalResponse {
  proposals?: Array<Partial<VaultMaintenanceProposal>>
  items?: Array<Partial<VaultMaintenanceProposal>>
  generated_at?: string
}

export interface VaultMaintenanceProposalMutationResponse {
  proposal?: Partial<VaultMaintenanceProposal>
  id?: string
  status?: string
  payload?: Record<string, unknown>
}

export interface VaultMaintenanceProposalDiffResponse {
  proposal?: Partial<VaultMaintenanceProposal>
  applicable: boolean
  reason?: string | null
  action?: string | null
  diff: string
  changes?: Array<{
    path?: string
    applicable?: boolean
    reason?: string | null
    occurrences?: number
    old_sha256?: string | null
    new_sha256?: string | null
    old_byte_count?: number | null
    new_byte_count?: number | null
    diff?: string
  }>
  status?: string
}

export type VaultFolderKind = 'project' | 'course' | 'reference'

export interface VaultFolderInitResponse {
  ok?: boolean
  status?: string
  message?: string
  changed_paths?: string[]
  warnings?: string[]
  errors?: string[]
  summary?: Record<string, unknown>
}

export interface VaultEnrichmentStatus {
  generated_path: string
  exists: boolean
  counts: Record<string, number>
  node_count: number
  index_generated_at?: string | null
  next_candidates?: Array<{
    path: string
    title: string
    state: string
    source_type: string
    staleness_status: string
  }>
}

export interface VaultEnrichmentRunResponse {
  ok: boolean
  model_route: string
  processed: Array<{
    path: string
    sha256?: string
    tags?: string[]
    note_type?: string
  }>
  skipped: Array<{ path: string; reason: string }>
  errors: Array<{ path: string; reason: string }>
  proposals_created: string[]
  generated_path: string
}

export interface VaultGeneratedRelation {
  from_path: string
  to_path: string
  relation_type: string
  reason?: string | null
  confidence?: number | null
  decision: 'candidate' | 'accepted' | 'rejected' | string
  key: string
}

export interface VaultGeneratedRelationsResponse {
  relations: VaultGeneratedRelation[]
}

export interface VaultEnrichmentBatchStatus {
  status: 'idle' | 'queued' | 'running' | 'completed' | 'completed_with_errors' | 'failed' | string
  running: boolean
  started_at?: string | null
  finished_at?: string | null
  request?: Record<string, unknown> | null
  result?: VaultEnrichmentRunResponse | null
  error?: string | null
}

// ── Permissions ───────────────────────────────────────────────────────────────

export interface Permission {
  id: string
  conversationId: string
  runId: string
  kind: string
  summary: string
  detailsJson: string
  status: 'pending' | 'resolved'
  decision: string | null
  note: string | null
  createdAt: string
  resolvedAt: string | null
}

// ── Usage ─────────────────────────────────────────────────────────────────────

export type UsageProviderId = 'copilot' | 'claude' | 'codex' | 'gemini' | 'openrouter'

export interface UsageProviderSummary {
  provider: UsageProviderId
  label: string
  unit: 'premium_requests' | 'calls' | 'usd'
  used: number
  limit: number | null
  percent: number | null
  status: string
  wired: boolean
  period: string
  details: Record<string, unknown>
}

export interface SubscriptionHost {
  host: string
  status: 'ok' | 'degraded' | 'unavailable'
  authenticated: boolean | null
  account: string | null
  subscriptionType: string | null
  authMethod: string | null
  version: string | null
  detail: string | null
  checkedAt: string
}

export interface SubscriptionProvider {
  provider: 'codex' | 'claude' | 'gemini'
  label: string
  aggregateStatus: 'ok' | 'degraded' | 'unavailable'
  hosts: SubscriptionHost[]
}

// ── Syncthing ─────────────────────────────────────────────────────────────────

export type SyncthingHost = 'local' | 'serrano' | 'winpc' | 'iphone' | string

export interface SyncthingFolderStatus {
  folderId: string
  state: string | null
  needItems: number | null
  needBytes: number | null
  errors: number | null
  pullErrors: number | null
  globalItems: number | null
  localItems: number | null
}

export interface SyncthingConnection {
  deviceId: string
  connected: boolean
  address: string | null
  version: string | null
  paused: boolean
  at: string | null
}

export interface SyncthingDevice {
  host: SyncthingHost
  status: 'ok' | 'degraded' | 'unavailable' | 'unknown' | 'probe_only'
  available: boolean | null
  conflictCount: number | null
  junkCount: number | null
  timestamp: string | null
  folders: SyncthingFolderStatus[]
  connections: SyncthingConnection[]
}

export interface SyncthingConflict {
  path: string
  canonicalPath: string | null
  folderId: string | null
  devices: string[]
  mtimes: Record<string, string>
  reason: string | null
  reviewDir: string | null
}

// ── Workers ──────────────────────────────────────────────────────────────────

export interface WorkerTerminalLine {
  text: string
  timestamp: string
}

// ── App state ─────────────────────────────────────────────────────────────────

export interface AppState {
  conversations: Conversation[]
  folders: Folder[]
  activeConversationId: string
  contextMode: ContextMode
  contextFiles: ContextFile[]
  vaultContextItems?: VaultContextItem[]
  model: string
  defaultModel: string
  taskModel: string
  modelOptions: string[]
  budgetUsed: number
  budgetTotal: number
  tools: Tool[]
  leftSidebarOpen: boolean
  /** which right panel is open, null = none */
  rightPanel: RightPanelId
  blankSlate: boolean
  incognito: boolean
  sensitive: boolean
  sensitiveUnlocked: boolean
  theme: ThemeName
  titleGeneration: boolean
  copilotBudgetHardOverride: boolean
  systemContext: string
  shortTermContinuity: string
  healthEntries: HealthEntry[]
  healthSystem: HealthSystemMetrics | null
  directActions: DirectAction[]
  workers: Worker[]
  workerTypeOptions: WorkerTypeOption[]
  permissions: Permission[]
  usageProviders: UsageProviderSummary[]
  subscriptions: SubscriptionProvider[]
  syncthingDevices: SyncthingDevice[]
  syncthingConflicts: SyncthingConflict[]
  settingsTab: 'settings' | 'theme'
}

// ── SSE event types ───────────────────────────────────────────────────────────

export type SSEEventType =
  | 'run.queued'
  | 'run.started'
  | 'context.loaded'
  | 'message.delta'
  | 'message.completed'
  | 'tool.started'
  | 'tool.output'
  | 'tool.finished'
  | 'model.usage'
  | 'audit'
  | 'error'
  | 'run.completed'
  | 'permission.requested'
  | 'permission.resolved'
  | 'conversation.title'

export interface SSEEvent {
  id?: string
  type: SSEEventType
  data: Record<string, unknown>
}
