import type {
  BackendAction,
  BackendContextCurrent,
  BackendContextMode,
  BackendConversation,
  BackendMessage,
  BackendTool,
  BackendWorker,
} from './backend-types'
import type {
  ChatMessage,
  ContextFile,
  ContextMode,
  Conversation,
  DirectAction,
  DirectActionGroup,
  Tool,
  Worker,
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
    messages: messages.map(toUIMessage),
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
    description: t.name,
    enabled: t.enabled,
    category: guessToolCategory(t.name),
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

const ACTION_GROUPS: Record<string, DirectActionGroup> = {
  health: 'health',
  helpers: 'health',
  ref: 'ref',
  vault_index: 'vault_index',
  sync_guard: 'sync_guard',
  winpc: 'winpc',
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
  codex: 'codex',
  goose: 'goose',
  gemini: 'gemini',
  gh_cli: 'gh_cli',
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
