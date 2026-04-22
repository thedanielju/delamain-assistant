export type BackendContextMode = 'normal' | 'blank_slate'

export type BackendRunStatus =
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'cancelled'

export type BackendMessageRole = 'user' | 'assistant' | 'tool' | 'system'

export interface BackendConversation {
  id: string
  title: string | null
  context_mode: BackendContextMode
  model_route: string | null
  incognito_route: boolean
  sensitive_unlocked: boolean
  archived: boolean
  created_at: string
  updated_at: string
}

export interface BackendMessage {
  id: string
  conversation_id: string
  run_id: string | null
  role: BackendMessageRole
  content: string
  status: string
  created_at: string
  updated_at: string
}

export interface BackendRun {
  id: string
  conversation_id: string
  user_message_id: string
  assistant_message_id: string | null
  status: BackendRunStatus
  context_mode: BackendContextMode
  model_route: string
  incognito_route: boolean
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface SubmitPromptResponse {
  message_id: string
  run_id: string
  status: BackendRunStatus
}

export interface BackendHealth {
  status: string
  sqlite: { path: string; ok: boolean }
  litellm: { version: string | null; known_bad_blocked: boolean; error: string | null }
  config: {
    host: string
    port: number
    model_default: string
    model_calls_enabled: boolean
  }
  helpers: Record<string, { path: string; exists: boolean; executable: boolean }>
}

export interface BackendSettings {
  context_mode: BackendContextMode
  title_generation_enabled: boolean
  model_default: string
}

export interface BackendModelRoutes {
  default: string
  fallback_high_volume?: string
  fallback_cheap?: string
  paid_fallback?: string
  [route: string]: string | undefined
}

export interface BackendTool {
  name: string
  enabled: boolean
}

export interface BackendContextItem {
  path: string
  mode: string
  included: boolean
  missing: boolean
  byte_count: number | null
  sha256: string | null
}

export interface BackendContextCurrent {
  context_mode: BackendContextMode
  items: BackendContextItem[]
}

export interface BackendContextFile {
  id: string
  mode: string
  path: string
  exists: boolean
  content: string
  byte_count: number
  sha256: string
}

export interface BackendAction {
  id: string
  label: string
  description?: string
  argv: string[]
  cwd?: string
  timeout_seconds?: number
  writes?: boolean
  remote?: boolean
}

export interface BackendActionRun {
  id: string
  action_id: string
  label: string
  status: 'success' | 'failed' | 'timeout' | 'denied' | 'running'
  error_code: string | null
  error_message: string | null
  exit_code: number | null
  duration_ms: number | null
  argv?: string[]
  cwd?: string
  writes?: boolean
  remote?: boolean
  stdout_path?: string
  stderr_path?: string
  stdout_bytes?: number
  stderr_bytes?: number
  stdout_preview?: string
  stderr_preview?: string
  stdout_preview_truncated?: boolean
  stderr_preview_truncated?: boolean
}

export interface BackendWorkerType {
  id: string
  label: string
  description?: string
  command_template: string[]
  host: string
}

export type BackendWorkerStatus =
  | 'starting'
  | 'running'
  | 'stopping'
  | 'stopped'
  | 'failed'

export interface BackendWorker {
  id: string
  status: BackendWorkerStatus
  name: string
  worker_type: string
  host: string
  tmux_session: string
  tmux_socket: string
  conversation_id: string | null
  command: string
  pid: number | null
  exit_code: number | null
  error_message: string | null
  stopped_at: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type BackendSSEEventType =
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

export interface BackendSSEEvent<T = Record<string, unknown>> {
  id?: string
  type: BackendSSEEventType | string
  payload: T
}
