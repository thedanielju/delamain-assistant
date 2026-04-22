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
  messages: ChatMessage[]
  active?: boolean
  runStatus?: RunStatus
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
  type: 'codex' | 'opencode' | 'claude' | 'goose' | 'gemini' | 'gh_cli' | 'tmux' | 'generic'
  host: 'local' | 'serrano' | 'winpc'
  status: WorkerStatus
  startedAt?: string
  lastActivity?: string
  output?: string
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

export type RightPanelId = 'settings' | 'health' | 'workers' | null

// ── Workers ──────────────────────────────────────────────────────────────────

export interface WorkerTerminalLine {
  text: string
  timestamp: string
}

// ── App state ─────────────────────────────────────────────────────────────────

export interface AppState {
  conversations: Conversation[]
  activeConversationId: string
  contextMode: ContextMode
  contextFiles: ContextFile[]
  model: string
  defaultModel: string
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
  systemContext: string
  shortTermContinuity: string
  healthEntries: HealthEntry[]
  directActions: DirectAction[]
  workers: Worker[]
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
