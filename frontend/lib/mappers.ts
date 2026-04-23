import type {
  BackendCopilotBudget,
  BackendAction,
  BackendContextCurrent,
  BackendContextMode,
  BackendConversation,
  BackendFolder,
  BackendMessage,
  BackendPermission,
  BackendSubscriptionHost,
  BackendSubscriptionProvider,
  BackendSyncthingConflict,
  BackendSyncthingDevice,
  BackendTool,
  BackendUsageProvider,
  BackendWorker,
} from './backend-types'
import type {
  ChatMessage,
  ContextFile,
  ContextMode,
  Conversation,
  DirectAction,
  DirectActionGroup,
  Folder,
  Permission,
  SubscriptionHost,
  SubscriptionProvider,
  SyncthingConflict,
  SyncthingDevice,
  Tool,
  UsageProviderSummary,
  Worker,
  WorkerTypeOption,
} from './types'

export function toUIContextMode(mode: BackendContextMode | string): ContextMode {
  switch (mode) {
    case 'blank_slate':
      return 'Blank-slate'
    case 'normal':
    default:
      return 'Normal'
  }
}

export function toBackendContextModeFromUI(mode: ContextMode): BackendContextMode {
  return mode === 'Blank-slate' ? 'blank_slate' : 'normal'
}

export function toBackendContextMode(mode: ContextMode): BackendContextMode {
  return mode === 'Blank-slate' ? 'blank_slate' : 'normal'
}

function relativeTimeLabel(iso: string): string {
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = Math.max(0, now - then)
  const mins = Math.round(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function toUIConversation(
  conv: BackendConversation,
  messages: BackendMessage[] = []
): Conversation {
  return {
    id: conv.id,
    title: conv.title ?? 'Untitled',
    timestamp: relativeTimeLabel(conv.updated_at),
    contextMode: toUIContextMode(conv.context_mode),
    modelRoute: conv.model_route,
    incognitoRoute: conv.incognito_route,
    sensitiveUnlocked: conv.sensitive_unlocked,
    folderId: conv.folder_id,
    archived: conv.archived,
    messages: messages.map(toUIMessage),
  }
}

export function toUIFolder(f: BackendFolder): Folder {
  return {
    id: f.id,
    name: f.name,
    parentId: f.parent_id,
  }
}

export function toUIMessage(msg: BackendMessage): ChatMessage {
  return {
    id: msg.id,
    role: msg.role === 'tool' ? 'system' : (msg.role as ChatMessage['role']),
    content: msg.content,
    runId: msg.run_id ?? undefined,
    toolCallsBefore: [],
  }
}

export function toUIContextFiles(ctx: BackendContextCurrent): ContextFile[] {
  return ctx.items
    .filter((item) => !item.missing && item.included)
    .map((item, i) => {
      const parts = item.path.split('/')
      const name = parts[parts.length - 1] || item.path
      return {
        id: `ctx-${i}`,
        name,
        path: item.path,
        bytes: item.byte_count ?? undefined,
        hash: item.sha256 ?? undefined,
        tokenEstimate: item.byte_count ? Math.round(item.byte_count / 4) : undefined,
      }
    })
}

export function toUITool(t: BackendTool): Tool {
  return {
    id: t.name,
    name: t.name,
    description: toolDescription(t.name),
    enabled: t.enabled,
    category: guessToolCategory(t.name),
    approvalPolicy: t.approval_policy ?? t.approval_policy_default,
  }
}

function guessToolCategory(name: string): Tool['category'] {
  if (name.startsWith('ssh_')) return 'ssh'
  if (name.includes('write') || name.includes('patch')) return 'write'
  if (name.includes('search') || name === 'read_text_file' || name === 'list_directory')
    return 'read'
  if (name === 'web_search') return 'web'
  return 'other'
}

function toolDescription(name: string): string {
  switch (name) {
    case 'get_now':
      return 'Return live wall-clock time.'
    case 'delamain_ref':
      return 'Check deterministic reference bundle status.'
    case 'delamain_vault_index':
      return 'Query or build deterministic vault index.'
    case 'read_text_file':
      return 'Read text files under allowed roots.'
    case 'list_directory':
      return 'List files and directories under allowed roots.'
    case 'search_vault':
      return 'Search vault/index for matching notes.'
    case 'patch_text_file':
      return 'Exact-match patch with runtime backup (guarded).'
    case 'run_shell':
      return 'Bounded argv command under allowed cwd roots (guarded).'
    case 'get_health_status':
      return 'Return deterministic backend/helper health status.'
    default:
      return name
  }
}

const ACTION_GROUPS: Record<string, DirectActionGroup> = {
  health: 'health',
  helpers: 'health',
  ref: 'ref',
  vault_index: 'vault_index',
  sync_guard: 'sync_guard',
  winpc: 'winpc',
  subscription: 'subscription',
}

export function toUIDirectAction(a: BackendAction): DirectAction {
  const group = (a.id.split('.')[0] as string) ?? 'health'
  return {
    id: a.id,
    label: a.label ?? a.id,
    group: ACTION_GROUPS[group] ?? 'health',
    description: a.description,
    status: 'idle',
  }
}

const WORKER_TYPE_MAP: Record<string, Worker['type']> = {
  shell: 'tmux',
  opencode: 'opencode',
  claude_code: 'claude',
  winpc_shell: 'winpc_shell',
}

export function toUIWorker(w: BackendWorker): Worker {
  return {
    id: w.id,
    name: w.name,
    type: WORKER_TYPE_MAP[w.worker_type] ?? 'generic',
    host: (w.host as Worker['host']) ?? 'local',
    status:
      w.status === 'starting' || w.status === 'running'
        ? 'running'
        : w.status === 'stopped' || w.status === 'failed'
        ? 'stopped'
        : 'idle',
    startedAt: relativeTimeLabel(w.created_at),
    lastActivity: relativeTimeLabel(w.updated_at),
  }
}

export function toUIWorkerTypeOption(type: { id: string; label: string; host: string }): WorkerTypeOption {
  const host: WorkerTypeOption['host'] =
    type.host === 'winpc' ? 'winpc' : type.host === 'serrano' ? 'serrano' : 'local'
  return {
    id: type.id,
    label: type.label,
    host,
  }
}

export function toHealthEntriesFromHealth(health: {
  status: string
  sqlite: { ok: boolean; path: string }
  litellm: { known_bad_blocked: boolean; version: string | null; error: string | null }
  helpers: Record<string, { exists: boolean; executable: boolean }>
  budget?: BackendCopilotBudget
}) {
  const entries: import('./types').HealthEntry[] = []
  entries.push({
    id: 'backend',
    label: 'Backend',
    status: health.status === 'ok' ? 'ok' : 'degraded',
    detail: health.status === 'ok' ? 'API healthy' : 'Backend reports degraded status',
    lastChecked: 'just now',
  })
  entries.push({
    id: 'sqlite',
    label: 'SQLite',
    status: health.sqlite.ok ? 'ok' : 'error',
    detail: health.sqlite.ok ? 'Database healthy' : 'Database healthcheck failed',
    lastChecked: 'just now',
  })
  entries.push({
    id: 'litellm',
    label: 'LiteLLM',
    status: health.litellm.known_bad_blocked ? 'ok' : 'degraded',
    detail: health.litellm.error ?? `Version ${health.litellm.version ?? 'unknown'}`,
    lastChecked: 'just now',
  })
  for (const [name, helper] of Object.entries(health.helpers)) {
    const helperOk = helper.exists && helper.executable
    entries.push({
      id: `helper-${name}`,
      label: `Helper: ${name}`,
      status: helperOk ? 'ok' : 'degraded',
      detail: helperOk ? 'Ready' : 'Missing or not executable',
      lastChecked: 'just now',
    })
  }
  if (health.budget) {
    entries.push({
      id: 'copilot-budget',
      label: 'Copilot Budget',
      status: health.budget.status === 'hard' ? 'error' : health.budget.status === 'soft' ? 'degraded' : 'ok',
      detail: `${health.budget.used_premium_requests} / ${health.budget.monthly_premium_requests} (${health.budget.percent_used}%)`,
      lastChecked: 'just now',
    })
  }
  return entries
}

// ── Permissions ──────────────────────────────────────────────────────────────

export function toUIPermission(p: BackendPermission): Permission {
  return {
    id: p.id,
    conversationId: p.conversation_id,
    runId: p.run_id,
    kind: p.kind,
    summary: p.summary,
    detailsJson: p.details_json,
    status: p.status,
    decision: p.decision,
    note: p.note,
    createdAt: p.created_at,
    resolvedAt: p.resolved_at,
  }
}

// ── Usage ────────────────────────────────────────────────────────────────────

export function toUIUsageProvider(p: BackendUsageProvider): UsageProviderSummary {
  return {
    provider: p.provider,
    label: p.label,
    unit: p.unit,
    used: p.used,
    limit: p.limit_or_credits,
    percent: p.percent_used,
    status: p.status,
    wired: p.wired,
    period: p.period,
    details: p.details,
  }
}

function toUISubscriptionHost(h: BackendSubscriptionHost): SubscriptionHost {
  return {
    host: h.host,
    status: h.status,
    authenticated: h.authenticated,
    account: h.account,
    subscriptionType: h.subscription_type,
    authMethod: h.auth_method,
    version: h.version,
    detail: h.detail,
    checkedAt: h.checked_at,
  }
}

export function toUISubscriptionProvider(p: BackendSubscriptionProvider): SubscriptionProvider {
  return {
    provider: p.provider,
    label: p.label,
    aggregateStatus: p.aggregate_status,
    hosts: p.hosts.map(toUISubscriptionHost),
  }
}

// ── Syncthing ────────────────────────────────────────────────────────────────

export function toUISyncthingDevice(d: BackendSyncthingDevice): SyncthingDevice {
  return {
    host: d.host,
    status: d.status,
    available: d.syncthing_available,
    conflictCount: d.conflict_count,
    junkCount: d.junk_count,
    timestamp: d.timestamp,
    folders: d.folders.map((f) => ({
      folderId: f.folder_id,
      state: f.state,
      needItems: f.need_total_items,
      needBytes: f.need_bytes,
      errors: f.errors,
      pullErrors: f.pull_errors,
      globalItems: f.global_total_items,
      localItems: f.local_total_items,
    })),
    connections: d.connections.map((c) => ({
      deviceId: c.device_id,
      connected: c.connected,
      address: c.address,
      version: c.client_version,
      paused: c.paused,
      at: c.at,
    })),
  }
}

export function toUISyncthingConflict(c: BackendSyncthingConflict): SyncthingConflict {
  return {
    path: c.path,
    canonicalPath: c.canonical_path,
    folderId: c.folder_id,
    devices: c.devices,
    mtimes: c.mtimes,
    reason: c.reason,
    reviewDir: c.review_dir,
  }
}
