import { API_BASE, HEALTH_PROBE_TIMEOUT_MS } from './config'
import type {
  BackendAction,
  BackendActionRun,
  BackendContextCurrent,
  BackendContextFile,
  BackendContextMode,
  BackendConversation,
  BackendHealth,
  BackendMessage,
  BackendModelRoutes,
  BackendRun,
  BackendSettings,
  BackendTool,
  BackendWorker,
  BackendWorkerType,
  SubmitPromptResponse,
} from './backend-types'

export class BackendError extends Error {
  status: number
  body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

export class BackendUnreachableError extends Error {
  cause?: unknown
  constructor(message: string, cause?: unknown) {
    super(message)
    this.cause = cause
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {}
): Promise<T> {
  const { timeoutMs, ...rest } = init
  const controller = timeoutMs ? new AbortController() : undefined
  const timeoutId = controller && setTimeout(() => controller.abort(), timeoutMs)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: {
        'Content-Type': 'application/json',
        ...(rest.headers ?? {}),
      },
      signal: controller?.signal ?? rest.signal,
    })
  } catch (err) {
    throw new BackendUnreachableError(`Failed to reach ${API_BASE}${path}`, err)
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }

  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* no-op */
    }
    const detail =
      (body && typeof body === 'object' && 'detail' in body && (body as { detail: unknown }).detail) ||
      res.statusText
    throw new BackendError(String(detail), res.status, body)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  // ── Health ─────────────────────────────────────────────────────────────────
  health(): Promise<BackendHealth> {
    return request<BackendHealth>('/health', { timeoutMs: HEALTH_PROBE_TIMEOUT_MS })
  },

  // ── Conversations ──────────────────────────────────────────────────────────
  listConversations(): Promise<BackendConversation[]> {
    return request<BackendConversation[]>('/conversations')
  },
  createConversation(body: {
    title?: string | null
    context_mode?: BackendContextMode
    model_route?: string | null
    incognito_route?: boolean
  }): Promise<BackendConversation> {
    return request<BackendConversation>('/conversations', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  getConversation(id: string): Promise<BackendConversation> {
    return request<BackendConversation>(`/conversations/${id}`)
  },
  patchConversation(
    id: string,
    body: { title?: string | null; archived?: boolean | null }
  ): Promise<BackendConversation> {
    return request<BackendConversation>(`/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  deleteConversation(id: string): Promise<void> {
    return request<void>(`/conversations/${id}`, { method: 'DELETE' })
  },

  // ── Messages / runs ─────────────────────────────────────────────────────────
  listMessages(conversationId: string): Promise<BackendMessage[]> {
    return request<BackendMessage[]>(`/conversations/${conversationId}/messages`)
  },
  submitPrompt(
    conversationId: string,
    body: {
      content: string
      context_mode?: BackendContextMode | null
      model_route?: string | null
      incognito_route?: boolean | null
    }
  ): Promise<SubmitPromptResponse> {
    return request<SubmitPromptResponse>(
      `/conversations/${conversationId}/messages`,
      { method: 'POST', body: JSON.stringify(body) }
    )
  },
  listRuns(conversationId: string): Promise<BackendRun[]> {
    return request<BackendRun[]>(`/conversations/${conversationId}/runs`)
  },
  getRun(runId: string): Promise<BackendRun> {
    return request<BackendRun>(`/runs/${runId}`)
  },
  cancelRun(runId: string): Promise<BackendRun> {
    return request<BackendRun>(`/runs/${runId}/cancel`, { method: 'POST' })
  },
  retryRun(runId: string): Promise<BackendRun> {
    return request<BackendRun>(`/runs/${runId}/retry`, { method: 'POST' })
  },

  // ── Sensitive ──────────────────────────────────────────────────────────────
  unlockSensitive(conversationId: string): Promise<{ sensitive_unlocked: boolean }> {
    return request(`/conversations/${conversationId}/sensitive/unlock`, { method: 'POST' })
  },
  lockSensitive(conversationId: string): Promise<{ sensitive_unlocked: boolean }> {
    return request(`/conversations/${conversationId}/sensitive/lock`, { method: 'POST' })
  },

  // ── Settings ───────────────────────────────────────────────────────────────
  getSettings(): Promise<{ settings: BackendSettings }> {
    return request<{ settings: BackendSettings }>('/settings')
  },
  patchSettings(values: Partial<BackendSettings>, conversationId?: string) {
    return request<{ settings: BackendSettings }>('/settings', {
      method: 'PATCH',
      body: JSON.stringify({ values, conversation_id: conversationId ?? null }),
    })
  },
  getModels(): Promise<BackendModelRoutes> {
    return request<BackendModelRoutes>('/settings/models')
  },
  getTools(): Promise<{ tools: BackendTool[] }> {
    return request<{ tools: BackendTool[] }>('/settings/tools')
  },
  patchTool(name: string, enabled: boolean, conversationId?: string) {
    return request<{ tool: BackendTool }>(`/settings/tools/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, conversation_id: conversationId ?? null }),
    })
  },

  // ── Context ────────────────────────────────────────────────────────────────
  getContextCurrent(mode: BackendContextMode = 'normal'): Promise<BackendContextCurrent> {
    return request<BackendContextCurrent>(`/context/current?context_mode=${mode}`)
  },
  getContextFile(fileId: string): Promise<BackendContextFile> {
    return request<BackendContextFile>(`/context/files/${encodeURIComponent(fileId)}`)
  },
  patchContextFile(fileId: string, content: string, conversationId?: string) {
    return request<BackendContextFile>(
      `/context/files/${encodeURIComponent(fileId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ content, conversation_id: conversationId ?? null }),
      }
    )
  },

  // ── Actions ────────────────────────────────────────────────────────────────
  listActions(): Promise<{ actions: BackendAction[] }> {
    return request<{ actions: BackendAction[] }>('/actions')
  },
  runAction(actionId: string, conversationId?: string): Promise<BackendActionRun> {
    return request<BackendActionRun>(`/actions/${encodeURIComponent(actionId)}`, {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId ?? null }),
    })
  },
  getActionRun(actionRunId: string): Promise<BackendActionRun & { conversation_id: string | null }> {
    return request(`/action-runs/${encodeURIComponent(actionRunId)}`)
  },
  listConversationActionRuns(conversationId: string) {
    return request<BackendActionRun[]>(
      `/conversations/${conversationId}/action-runs`
    )
  },

  // ── Workers ────────────────────────────────────────────────────────────────
  listWorkerTypes(): Promise<{ types: BackendWorkerType[] }> {
    return request<{ types: BackendWorkerType[] }>('/workers/types')
  },
  listWorkers(params: { status?: string; conversation_id?: string } = {}) {
    const q = new URLSearchParams()
    if (params.status) q.set('status', params.status)
    if (params.conversation_id) q.set('conversation_id', params.conversation_id)
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request<{ workers: BackendWorker[] }>(`/workers${suffix}`)
  },
  createWorker(body: {
    worker_type: string
    name?: string | null
    conversation_id?: string | null
  }): Promise<BackendWorker> {
    return request<BackendWorker>('/workers', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  getWorker(id: string, refresh = false): Promise<BackendWorker> {
    return request<BackendWorker>(`/workers/${id}${refresh ? '?refresh=true' : ''}`)
  },
  stopWorker(id: string): Promise<BackendWorker> {
    return request<BackendWorker>(`/workers/${id}/stop`, { method: 'POST' })
  },
  killWorker(id: string): Promise<BackendWorker> {
    return request<BackendWorker>(`/workers/${id}`, { method: 'DELETE' })
  },
  getWorkerOutput(id: string, lines = 200) {
    return request<{
      worker_id: string
      name: string
      alive: boolean
      lines_requested: number
      output: string
    }>(`/workers/${id}/output?lines=${lines}`)
  },
}

export function sseUrl(path: string): string {
  return `${API_BASE}${path}`
}
