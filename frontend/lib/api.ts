import { API_BASE, HEALTH_PROBE_TIMEOUT_MS } from './config'
import type {
  AuthRequiredDetail,
  BackendAction,
  BackendActionRun,
  BackendContextCurrent,
  BackendContextFile,
  BackendContextMode,
  BackendConversation,
  BackendCopilotBudget,
  BackendFolder,
  BackendHealth,
  BackendMessage,
  BackendModelRoutes,
  BackendPermission,
  BackendRun,
  BackendSettings,
  BackendSubscriptionSummary,
  BackendSyncthingConflicts,
  BackendSyncthingResolveAction,
  BackendSyncthingResolveResponse,
  BackendSyncthingSummary,
  BackendTool,
  BackendUsageResponse,
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

export class AuthRequiredError extends BackendError {
  redirectUrl?: string
  constructor(detail: AuthRequiredDetail, status: number, body: unknown) {
    super(detail.message, status, body)
    this.redirectUrl = detail.redirect_url
  }
}

function asAuthRequired(body: unknown): AuthRequiredDetail | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  if (!detail || typeof detail !== 'object') return null
  const d = detail as Record<string, unknown>
  if (typeof d.code === 'string' && d.code.toLowerCase() === 'auth_required') {
    return {
      code: 'auth_required',
      message: typeof d.message === 'string' ? d.message : 'Auth required',
      redirect_url: typeof d.redirect_url === 'string' ? d.redirect_url : undefined,
    }
  }
  return null
}

interface RequestInitExt extends RequestInit {
  timeoutMs?: number
  asText?: boolean
}

async function request<T>(path: string, init: RequestInitExt = {}): Promise<T> {
  const { timeoutMs, asText, ...rest } = init
  const controller = timeoutMs ? new AbortController() : undefined
  const timeoutId = controller && setTimeout(() => controller.abort(), timeoutMs)

  let res: Response
  try {
    const headers = new Headers(rest.headers)
    if (rest.body != null && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      credentials: rest.credentials ?? 'same-origin',
      headers,
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
    const authDetail = asAuthRequired(body)
    if (authDetail || res.status === 401) {
      throw new AuthRequiredError(
        authDetail ?? { code: 'auth_required', message: res.statusText || 'Auth required' },
        res.status,
        body
      )
    }
    const detail =
      (body && typeof body === 'object' && 'detail' in body && (body as { detail: unknown }).detail) ||
      res.statusText
    throw new BackendError(String(detail), res.status, body)
  }

  if (res.status === 204) return undefined as T
  if (asText) return (await res.text()) as unknown as T
  return (await res.json()) as T
}

export const api = {
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
    folder_id?: string | null
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
    body: { title?: string | null; archived?: boolean | null; folder_id?: string | null }
  ): Promise<BackendConversation> {
    return request<BackendConversation>(`/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  deleteConversation(id: string): Promise<void> {
    return request<void>(`/conversations/${id}`, { method: 'DELETE' })
  },

  // ── Folders ────────────────────────────────────────────────────────────────
  listFolders(): Promise<BackendFolder[]> {
    return request<BackendFolder[]>('/folders')
  },
  createFolder(body: { name: string; parent_id?: string | null }): Promise<BackendFolder> {
    return request<BackendFolder>('/folders', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  patchFolder(
    id: string,
    body: { name?: string | null; parent_id?: string | null }
  ): Promise<BackendFolder> {
    return request<BackendFolder>(`/folders/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
  },
  deleteFolder(id: string): Promise<void> {
    return request<void>(`/folders/${id}`, { method: 'DELETE' })
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

  // ── Permissions ────────────────────────────────────────────────────────────
  listRunPermissions(runId: string): Promise<BackendPermission[]> {
    return request<BackendPermission[]>(`/runs/${runId}/permissions`)
  },
  resolvePermission(
    permissionId: string,
    body: { decision: 'approved' | 'denied'; note?: string | null; resolver?: string | null }
  ): Promise<BackendPermission> {
    return request<BackendPermission>(`/permissions/${permissionId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
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
  getBudget(): Promise<{ copilot_budget: BackendCopilotBudget }> {
    return request<{ copilot_budget: BackendCopilotBudget }>('/settings/budget')
  },
  getTools(): Promise<{ tools: BackendTool[] }> {
    return request<{ tools: BackendTool[] }>('/settings/tools')
  },
  patchTool(
    name: string,
    body: {
      enabled?: boolean
      approval_policy?: 'auto' | 'confirm'
      conversation_id?: string | null
    }
  ) {
    return request<BackendTool>(`/settings/tools/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
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
  getActionRunStdout(actionRunId: string): Promise<string> {
    return request<string>(`/action-runs/${encodeURIComponent(actionRunId)}/stdout`, { asText: true })
  },
  getActionRunStderr(actionRunId: string): Promise<string> {
    return request<string>(`/action-runs/${encodeURIComponent(actionRunId)}/stderr`, { asText: true })
  },
  listConversationActionRuns(conversationId: string) {
    return request<BackendActionRun[]>(`/conversations/${conversationId}/action-runs`)
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
  patchWorker(id: string, body: { name: string }): Promise<BackendWorker> {
    return request<BackendWorker>(`/workers/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
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

  // ── Usage ──────────────────────────────────────────────────────────────────
  getUsage(): Promise<BackendUsageResponse> {
    return request<BackendUsageResponse>('/usage')
  },
  getSubscriptions(refresh = false): Promise<BackendSubscriptionSummary> {
    return request<BackendSubscriptionSummary>(
      `/usage/subscriptions${refresh ? '?refresh=true' : ''}`
    )
  },

  // ── Vault index (Prompt D — may 404 until backend lands it) ───────────────
  getVaultGraph(params: { folder?: string; tag?: string; limit?: number } = {}) {
    const q = new URLSearchParams()
    if (params.folder) q.set('folder', params.folder)
    if (params.tag) q.set('tag', params.tag)
    if (params.limit != null) q.set('limit', String(params.limit))
    const suffix = q.toString() ? `?${q.toString()}` : ''
    return request<import('./types').VaultGraph>(`/vault/graph${suffix}`)
  },
  getVaultNote(path: string) {
    return request<import('./types').VaultNoteDetail>(
      `/vault/note?path=${encodeURIComponent(path)}`
    )
  },
  listConversationContextPins(conversationId: string) {
    return request<{ paths: string[] }>(
      `/conversations/${conversationId}/context/pins`
    )
  },
  pinContext(conversationId: string, paths: string[]) {
    return request(`/conversations/${conversationId}/context/pin`, {
      method: 'POST',
      body: JSON.stringify({ paths }),
    })
  },
  unpinContext(conversationId: string, path: string) {
    return request(
      `/conversations/${conversationId}/context/pin?path=${encodeURIComponent(path)}`,
      { method: 'DELETE' }
    )
  },

  // ── Syncthing ──────────────────────────────────────────────────────────────
  getSyncthingSummary(): Promise<BackendSyncthingSummary> {
    return request<BackendSyncthingSummary>('/syncthing/summary')
  },
  getSyncthingConflicts(): Promise<BackendSyncthingConflicts> {
    return request<BackendSyncthingConflicts>('/syncthing/conflicts')
  },
  resolveSyncthingConflict(body: {
    path: string
    action: BackendSyncthingResolveAction
    note?: string | null
  }): Promise<BackendSyncthingResolveResponse> {
    return request<BackendSyncthingResolveResponse>('/syncthing/conflicts/resolve', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
}

export function sseUrl(path: string): string {
  return `${API_BASE}${path}`
}
