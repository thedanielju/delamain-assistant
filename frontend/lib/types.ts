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
  type: 'opencode' | 'claude' | 'tmux' | 'winpc_shell' | 'generic'
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

export type RightPanelId = 'settings' | 'health' | 'workers' | 'usage' | 'syncthing' | null

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
  model: string
  defaultModel: string
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
