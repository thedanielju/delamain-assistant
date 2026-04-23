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
  folder_id: string | null
  archived: boolean
  created_at: string
  updated_at: string
}

export interface BackendFolder {
  id: string
  name: string
  parent_id: string | null
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
  user_message_id: string | null
  assistant_message_id: string | null
  status: BackendRunStatus
  context_mode: BackendContextMode
  model_route: string | null
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

export interface BackendCopilotBudget {
  period: string
  used_premium_requests: number
  monthly_premium_requests: number
  percent_used: number
  soft_threshold_percent: number
  hard_threshold_percent: number
  status: string
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
  copilot_budget?: BackendCopilotBudget
}

export interface BackendSettings {
  context_mode: BackendContextMode
  title_generation_enabled: boolean
  model_default: string
  copilot_budget_hard_override_enabled?: boolean
}

export interface BackendModelRoutes {
  default: string
  fallback_high_volume?: string
  fallback_cheap?: string
  paid_fallback?: string
  [route: string]: string | undefined
}

export type BackendApprovalPolicy = 'auto' | 'confirm'

export interface BackendTool {
  name: string
  description?: string
  enabled: boolean
  risk?: 'low' | 'write' | 'shell' | string
  approval_policy_default?: BackendApprovalPolicy
  approval_policy?: BackendApprovalPolicy
  approval_policy_options?: BackendApprovalPolicy[]
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

// ── Usage ────────────────────────────────────────────────────────────────────

export type BackendUsageProviderId = 'copilot' | 'claude' | 'codex' | 'openrouter'

export interface BackendUsageProvider {
  provider: BackendUsageProviderId
  label: string
  period: string
  unit: 'premium_requests' | 'calls' | 'usd'
  used: number
  limit_or_credits: number | null
  percent_used: number | null
  status: string
  wired: boolean
  details: Record<string, unknown>
}

export interface BackendSubscriptionHost {
  host: string
  local_hostname: string | null
  local_platform: string | null
  command: string
  status: 'ok' | 'degraded' | 'unavailable'
  exit_code: number | null
  duration_ms: number
  checked_at: string
  authenticated: boolean | null
  auth_method: string | null
  subscription_type: string | null
  account: string | null
  version: string | null
  detail: string | null
}

export interface BackendSubscriptionProvider {
  provider: 'codex' | 'claude'
  label: string
  billing_kind: 'subscription_auth'
  aggregate_status: 'ok' | 'degraded' | 'unavailable'
  hosts: BackendSubscriptionHost[]
}

export interface BackendSubscriptionSummary {
  generated_at: string
  ttl_seconds: number
  providers: {
    codex: BackendSubscriptionProvider
    claude: BackendSubscriptionProvider
  }
}

export interface BackendUsageResponse {
  period: string
  generated_at: string
  providers: BackendUsageProvider[]
  subscriptions: BackendSubscriptionSummary
}

// ── Syncthing ────────────────────────────────────────────────────────────────

export interface BackendSyncthingFolder {
  folder_id: string
  state: string | null
  need_total_items: number | null
  need_bytes: number | null
  errors: number | null
  pull_errors: number | null
  global_total_items: number | null
  local_total_items: number | null
}

export interface BackendSyncthingConnection {
  device_id: string
  connected: boolean
  address: string | null
  client_version: string | null
  paused: boolean
  at: string | null
}

export interface BackendSyncthingDevice {
  host: string
  status: 'ok' | 'degraded' | 'unavailable' | 'unknown'
  timestamp: string | null
  syncthing_available: boolean
  conflict_count: number | null
  junk_count: number | null
  folders: BackendSyncthingFolder[]
  connections: BackendSyncthingConnection[]
  source: string
}

export interface BackendSyncthingSummary {
  generated_at: string
  source: string
  devices: BackendSyncthingDevice[]
}

export type BackendSyncthingFolderId = 'vault-combo' | '7lf7x-urjpx' | 'llm-workspace' | null

export interface BackendSyncthingConflict {
  path: string
  canonical_path: string | null
  folder_id: BackendSyncthingFolderId
  devices: string[]
  mtimes: Record<string, string>
  reason: string | null
  review_dir: string | null
}

export interface BackendSyncthingConflicts {
  generated_at: string
  source: string
  conflicts: BackendSyncthingConflict[]
}

export type BackendSyncthingResolveAction =
  | 'keep_canonical'
  | 'keep_conflict'
  | 'keep_both'
  | 'stage_review'

export interface BackendSyncthingResolveResponse {
  status: 'resolved' | 'staged'
  action: string
  path: string
  canonical_path: string | null
  result_path: string | null
  backup_dir: string
  backups: Array<{ label: string; source: string; backup: string }>
}

// ── Permissions ──────────────────────────────────────────────────────────────

export interface BackendPermission {
  id: string
  conversation_id: string
  run_id: string
  kind: string
  summary: string
  details_json: string
  status: 'pending' | 'resolved'
  decision: string | null
  resolver: string | null
  note: string | null
  created_at: string
  resolved_at: string | null
}

// ── SSE ───────────────────────────────────────────────────────────────────────

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

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthRequiredDetail {
  code: 'auth_required'
  message: string
  redirect_url?: string
}
