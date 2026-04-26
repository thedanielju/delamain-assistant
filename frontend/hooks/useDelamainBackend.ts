'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, AuthRequiredError, BackendError, BackendUnreachableError } from '@/lib/api'
import { MOCK_MODE } from '@/lib/config'
import {
  toHealthEntriesFromHealth,
  toUIHealthSystem,
  toUIContextMode,
  toUIContextFiles,
  toUIConversation,
  toUIDirectAction,
  toUIFolder,
  toUIMessage,
  toUIPermission,
  toUISubscriptionProvider,
  toUISyncthingConflict,
  toUISyncthingDevice,
  toUITool,
  toUIUsageProvider,
  toUIWorker,
  toUIWorkerTypeOption,
} from '@/lib/mappers'
import { INITIAL_STATE } from '@/lib/sample-data'
import { useSSE } from '@/lib/sse'
import type {
  BackendContextMode,
  BackendMessage,
  BackendSSEEvent,
  BackendSyncthingResolveAction,
} from '@/lib/backend-types'
import type {
  AppState,
  ChatMessage,
  Conversation,
  ContextFile,
  Permission,
  RightPanelId,
  RunStatus,
  SubscriptionProvider,
  SyncthingConflict,
  SyncthingDevice,
  ToolCall,
  ThemeName,
  UsageProviderSummary,
  VaultContextItem,
  VaultContextPreview,
  VaultNoteDetail,
  VaultPinsResponse,
  Worker,
} from '@/lib/types'

export type BackendConnection = 'probing' | 'connected' | 'offline' | 'auth_required' | 'mock'

const LEGACY_TASK_MODEL_KEY = 'delamain.taskModel'
const DEFAULT_TASK_MODEL = 'github_copilot/claude-haiku-4.5'

export interface AuditEntry {
  id: string
  conversationId: string
  event: string
  detail?: string
  timestamp: string
}

interface BackendState extends AppState {
  connection: BackendConnection
  authRedirectUrl: string | null
  audit: AuditEntry[]
}

function makeId(): string {
  return Math.random().toString(36).slice(2, 10)
}

function toBackendContextModeFromState(
  s: Pick<AppState, 'blankSlate'>,
  fallbackMode?: AppState['contextMode']
): BackendContextMode {
  const mode = fallbackMode ?? 'Normal'
  if (s.blankSlate || mode === 'Blank-slate') return 'blank_slate'
  return 'normal'
}

function toToolStatus(status: string | undefined): ToolCall['status'] {
  if (status === 'success') return 'success'
  if (status === 'running') return 'running'
  return 'error'
}

function toUIWorkerType(workerTypeId: string): Worker['type'] {
  switch (workerTypeId) {
    case 'opencode':
      return 'opencode'
    case 'claude_code':
      return 'claude'
    case 'codex_cli':
      return 'codex'
    case 'gemini_cli':
      return 'gemini'
    case 'winpc_shell':
      return 'winpc_shell'
    case 'winpc_opencode':
      return 'winpc_opencode'
    case 'winpc_claude_code':
      return 'winpc_claude'
    case 'winpc_codex_cli':
      return 'winpc_codex'
    case 'winpc_gemini_cli':
      return 'winpc_gemini'
    case 'shell':
      return 'tmux'
    default:
      return 'generic'
  }
}

function upsertToolCall(message: ChatMessage, incoming: ToolCall): ChatMessage {
  const calls = message.toolCallsBefore ?? []
  const index = calls.findIndex((tc) => tc.id === incoming.id)
  if (index < 0) {
    return { ...message, toolCallsBefore: [...calls, incoming], activeToolCallId: incoming.id }
  }
  const current = calls[index]
  const merged: ToolCall = {
    ...current,
    ...incoming,
    stdout: incoming.stdout ?? current.stdout,
    stderr: incoming.stderr ?? current.stderr,
  }
  const next = calls.slice()
  next[index] = merged
  return { ...message, toolCallsBefore: next, activeToolCallId: merged.id }
}

function mergeFetchedMessages(current: ChatMessage[], fetched: ChatMessage[]): ChatMessage[] {
  const currentById = new Map(current.map((message) => [message.id, message]))
  const fetchedIds = new Set(fetched.map((message) => message.id))
  const merged = fetched.map((message) => {
    const existing = currentById.get(message.id)
    if (!existing) return message
    return {
      ...message,
      streaming: existing.streaming && !message.content ? existing.streaming : message.streaming,
      toolCalls: existing.toolCalls ?? message.toolCalls,
      toolCallsBefore: existing.toolCallsBefore?.length ? existing.toolCallsBefore : message.toolCallsBefore,
      activeToolCallId: existing.activeToolCallId ?? message.activeToolCallId,
      runId: message.runId ?? existing.runId,
      runStatus: existing.runStatus ?? message.runStatus,
      error: existing.error ?? message.error,
    }
  })
  for (const message of current) {
    if (!fetchedIds.has(message.id)) merged.push(message)
  }
  return merged
}

function vaultItemFromPath(path: string, pinned = true): VaultContextItem {
  const parts = path.split('/')
  return {
    id: path,
    path,
    title: parts[parts.length - 1] || path,
    pinned,
  }
}

function normalizeVaultContextItems(
  response: VaultPinsResponse | VaultContextPreview | null | undefined,
  options: { defaultPinned?: boolean } = {}
): VaultContextItem[] {
  if (!response) return []
  const defaultPinned = options.defaultPinned ?? true
  const rawItems = response.items ?? ('pins' in response ? response.pins : undefined)
  if (rawItems?.length) {
    return rawItems.flatMap((item) => {
      if (typeof item === 'string') return [vaultItemFromPath(item, defaultPinned)]
      if (!item || typeof item !== 'object' || !item.path) return []
      return [{
        id: item.id ?? item.path,
        path: item.path,
        title: item.title ?? vaultItemFromPath(item.path).title,
        preview: item.preview,
        bytes: item.bytes,
        tokenEstimate: item.tokenEstimate ?? item.estimated_tokens,
        mode: item.mode,
        reason: item.reason,
        reasons: item.reasons,
        score: item.score,
        sha256: item.sha256,
        stale: item.stale,
        tags: item.tags,
        source_type: item.source_type,
        category: item.category,
        pinned: item.pinned ?? defaultPinned,
        excluded: item.excluded,
        exclusionReason: item.exclusionReason,
      }]
    })
  }
  return (response.paths ?? []).map((path) => vaultItemFromPath(path, defaultPinned))
}

function vaultContextItemFromNote(note: VaultNoteDetail): VaultContextItem {
  return {
    id: note.path,
    path: note.path,
    title: note.title || vaultItemFromPath(note.path).title,
    preview: note.content.slice(0, 320),
    bytes: note.bytes,
    tokenEstimate: note.bytes ? Math.round(note.bytes / 4) : null,
    tags: note.tags,
    source_type: note.source_type,
    pinned: true,
    excluded: note.excluded,
  }
}

export function useDelamainBackend() {
  const [state, setState] = useState<BackendState>({
    ...INITIAL_STATE,
    connection: MOCK_MODE ? 'mock' : 'probing',
    authRedirectUrl: null,
    audit: [],
    vaultContextItems: [],
    conversations: MOCK_MODE ? INITIAL_STATE.conversations : [],
    activeConversationId: MOCK_MODE ? INITIAL_STATE.activeConversationId : '',
  })

  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [probeNonce, setProbeNonce] = useState(0)

  const activeConversationId = state.activeConversationId
  const connected = state.connection === 'connected'
  const activeConversationIdRef = useRef(activeConversationId)

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId
  }, [activeConversationId])

  const retryConnection = useCallback(() => {
    setState((s) =>
      s.connection === 'offline' || s.connection === 'auth_required'
        ? { ...s, connection: 'probing' }
        : s
    )
    setProbeNonce((n) => n + 1)
  }, [])

  // Auto-probe: while offline, quietly retry /health every 5s so the UI
  // recovers without a manual reload when the tunnel flaps or serrano
  // restarts. Stops as soon as a probe succeeds and connection flips.
  useEffect(() => {
    if (MOCK_MODE) return
    if (state.connection !== 'offline') return
    const handle = setInterval(() => {
      setProbeNonce((n) => n + 1)
    }, 5000)
    return () => clearInterval(handle)
  }, [state.connection])

  const handleBackendError = useCallback((err: unknown) => {
    if (!(err instanceof AuthRequiredError)) return false
    if (err.redirectUrl && typeof window !== 'undefined') {
      window.location.href = err.redirectUrl
      return true
    }
    setState((s) => ({
      ...s,
      connection: 'auth_required',
      authRedirectUrl: err.redirectUrl ?? null,
    }))
    return true
  }, [])

  // ── Initial load ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (MOCK_MODE) return
    let cancelled = false

    const load = async () => {
      try {
        await api.health()
      } catch (err) {
        if (handleBackendError(err)) {
          return
        }
        if (!cancelled) {
          setState((s) => ({
            ...s,
            connection: err instanceof BackendUnreachableError ? 'offline' : 'offline',
          }))
        }
        return
      }

      try {
        const [
          health,
          conversations,
          toolsResp,
          actionsResp,
          settingsResp,
          modelsResp,
        ] = await Promise.all([
          api.health(),
          api.listConversations(),
          api.getTools(),
          api.listActions(),
          api.getSettings(),
          api.getModels(),
        ])
        const [
          foldersResult,
          ctxResult,
          budgetResult,
          workersResult,
          workerTypesResult,
          usageResult,
          syncSummaryResult,
          syncConflictsResult,
        ] = await Promise.allSettled([
          api.listFolders(),
          api.getContextCurrent('normal'),
          api.getBudget(),
          api.listWorkers(),
          api.listWorkerTypes(),
          api.getUsage(),
          api.getSyncthingSummary(),
          api.getSyncthingConflicts(),
        ])

        if (cancelled) return

        const foldersResp = foldersResult.status === 'fulfilled' ? foldersResult.value : []
        const ctx = ctxResult.status === 'fulfilled' ? ctxResult.value : null
        const budgetResp = budgetResult.status === 'fulfilled' ? budgetResult.value : null
        const workersResp = workersResult.status === 'fulfilled' ? workersResult.value : { workers: [] }
        const workerTypesResp =
          workerTypesResult.status === 'fulfilled' ? workerTypesResult.value : { types: [] }
        const usageResp = usageResult.status === 'fulfilled' ? usageResult.value : null
        const syncSummary = syncSummaryResult.status === 'fulfilled' ? syncSummaryResult.value : null
        const syncConflicts =
          syncConflictsResult.status === 'fulfilled' ? syncConflictsResult.value : null

        const uiConvs: Conversation[] = conversations.map((c) => toUIConversation(c))
        const firstId = uiConvs[0]?.id ?? ''

        let firstMessages: BackendMessage[] = []
        if (firstId) {
          try {
            firstMessages = await api.listMessages(firstId)
          } catch {
            /* no-op */
          }
        }

        const convsWithMessages = uiConvs.map((c) =>
          c.id === firstId ? { ...c, messages: firstMessages.map(toUIMessage), active: true } : c
        )
        const firstConversation = convsWithMessages.find((c) => c.id === firstId)

        if (cancelled) return

        const usageProviders: UsageProviderSummary[] = usageResp
          ? usageResp.providers.map(toUIUsageProvider)
          : []
        const subscriptions: SubscriptionProvider[] = usageResp
          ? Object.values(usageResp.subscriptions.providers)
              .filter(Boolean)
              .map((provider) => toUISubscriptionProvider(provider))
          : []
        const syncthingDevices: SyncthingDevice[] = syncSummary
          ? syncSummary.devices.map(toUISyncthingDevice)
          : []
        const syncthingConflicts: SyncthingConflict[] = syncConflicts
          ? syncConflicts.conflicts.map(toUISyncthingConflict)
          : []

        const modelOptions = [
          modelsResp.default,
          modelsResp.fallback_high_volume,
          modelsResp.fallback_cheap,
          modelsResp.paid_fallback,
        ].filter((value, index, arr): value is string => Boolean(value) && arr.indexOf(value) === index)

        let taskModel = settingsResp.settings.task_model || DEFAULT_TASK_MODEL
        const legacyTaskModel =
          typeof window !== 'undefined'
            ? window.localStorage.getItem(LEGACY_TASK_MODEL_KEY)
            : null
        if (
          legacyTaskModel &&
          taskModel === DEFAULT_TASK_MODEL &&
          modelOptions.includes(legacyTaskModel)
        ) {
          taskModel = legacyTaskModel
          api.patchSettings({ task_model: legacyTaskModel })
            .then(() => {
              window.localStorage.removeItem(LEGACY_TASK_MODEL_KEY)
            })
            .catch(() => {
              /* ignore */
            })
        }

        setState((s) => ({
          ...s,
          connection: 'connected',
          authRedirectUrl: null,
          conversations: convsWithMessages,
          folders: foldersResp.map(toUIFolder),
          activeConversationId: firstId,
          contextMode: firstConversation?.contextMode ?? toUIContextMode(settingsResp.settings.context_mode),
          blankSlate: (firstConversation?.contextMode ?? toUIContextMode(settingsResp.settings.context_mode)) === 'Blank-slate',
          titleGeneration: settingsResp.settings.title_generation_enabled,
          copilotBudgetHardOverride: Boolean(settingsResp.settings.copilot_budget_hard_override_enabled),
          defaultModel: settingsResp.settings.model_default,
          taskModel,
          model: firstConversation?.modelRoute ?? settingsResp.settings.model_default,
          incognito: firstConversation?.incognitoRoute ?? s.incognito,
          sensitiveUnlocked: firstConversation?.sensitiveUnlocked ?? s.sensitiveUnlocked,
          sensitive: firstConversation?.sensitiveUnlocked ?? s.sensitive,
          modelOptions,
          budgetUsed: budgetResp?.copilot_budget.used_premium_requests ?? s.budgetUsed,
          budgetTotal: budgetResp?.copilot_budget.monthly_premium_requests ?? s.budgetTotal,
          healthEntries: toHealthEntriesFromHealth(health),
          healthSystem: toUIHealthSystem(health.system),
          tools: toolsResp.tools.map(toUITool),
          directActions: actionsResp.actions.map(toUIDirectAction),
          workers: workersResp.workers.map(toUIWorker),
          workerTypeOptions: workerTypesResp.types.map(toUIWorkerTypeOption),
          contextFiles: ctx ? toUIContextFiles(ctx) : s.contextFiles,
          usageProviders,
          subscriptions,
          syncthingDevices,
          syncthingConflicts,
        }))
      } catch (err) {
        if (handleBackendError(err)) return
        if (!cancelled) setState((s) => ({ ...s, connection: 'offline' }))
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [handleBackendError, probeNonce])

  // ── SSE subscription on active conversation ─────────────────────────────────
  const ssePath = useMemo(() => {
    if (!connected || !activeConversationId) return null
    return `/conversations/${activeConversationId}/stream`
  }, [connected, activeConversationId])

  const appendAudit = useCallback((entry: Omit<AuditEntry, 'id' | 'timestamp'>) => {
    setState((s) => ({
      ...s,
      audit: [
        ...s.audit,
        { ...entry, id: makeId(), timestamp: new Date().toISOString() },
      ].slice(-200),
    }))
  }, [])

  const handleSSE = useCallback(
    (ev: BackendSSEEvent) => {
      const payload = (ev.payload ?? {}) as Record<string, unknown>
      const convoId = (payload.conversation_id as string | undefined) ?? activeConversationId
      const runIdFromPayload = payload.run_id as string | undefined

      switch (ev.type) {
        case 'run.queued':
        case 'run.started': {
          const runStatus: RunStatus = ev.type === 'run.queued' ? 'queued' : 'running'
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) =>
              c.id === convoId ? { ...c, runStatus } : c
            ),
          }))
          break
        }
        case 'run.completed': {
          const status = ((payload.status as string) ?? 'completed') as RunStatus
          const errorMessage = payload.error_message as string | undefined
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) => {
              if (c.id !== convoId) return c
              const next: Conversation = { ...c, runStatus: status }
              if (errorMessage) {
                const lastIdx = [...next.messages].reverse().findIndex((m) => m.role === 'assistant')
                if (lastIdx >= 0) {
                  const realIdx = next.messages.length - 1 - lastIdx
                  next.messages = next.messages.map((m, i) =>
                    i === realIdx ? { ...m, error: errorMessage, streaming: false } : m
                  )
                }
              }
              return next
            }),
          }))
          break
        }
        case 'model.usage': {
          const provider = payload.provider as string | undefined
          const cumUsed = payload.cumulative_used as number | undefined
          const cumLimit = payload.cumulative_limit as number | undefined
          setState((s) => {
            const next: Partial<BackendState> = {}
            if (provider === 'copilot' && typeof cumUsed === 'number') {
              next.budgetUsed = cumUsed
              if (typeof cumLimit === 'number') next.budgetTotal = cumLimit
            }
            if (provider && s.usageProviders.length) {
              next.usageProviders = s.usageProviders.map((p) =>
                p.provider === provider && typeof cumUsed === 'number'
                  ? {
                      ...p,
                      used: cumUsed,
                      limit: typeof cumLimit === 'number' ? cumLimit : p.limit,
                      percent:
                        typeof cumLimit === 'number' && cumLimit > 0
                          ? Math.round((cumUsed / cumLimit) * 100)
                          : p.percent,
                    }
                  : p
              )
            }
            return { ...s, ...next }
          })
          break
        }
        case 'permission.requested': {
          const perm: Permission = {
            id: (payload.permission_id as string) ?? `perm-${Date.now()}`,
            conversationId: (payload.conversation_id as string) ?? convoId,
            runId: (payload.run_id as string) ?? '',
            kind: (payload.kind as string) ?? 'tool',
            summary: (payload.summary as string) ?? 'Permission requested',
            detailsJson: JSON.stringify(payload.details ?? {}),
            status: 'pending',
            decision: null,
            note: null,
            createdAt: new Date().toISOString(),
            resolvedAt: null,
          }
          setState((s) => ({
            ...s,
            permissions: [...s.permissions.filter((p) => p.id !== perm.id), perm],
            conversations: s.conversations.map((c) =>
              c.id === convoId ? { ...c, runStatus: 'waiting_approval' as RunStatus } : c
            ),
          }))
          break
        }
        case 'permission.resolved': {
          const permissionId = payload.permission_id as string | undefined
          const decision = (payload.decision as string) ?? null
          if (!permissionId) break
          setState((s) => ({
            ...s,
            permissions: s.permissions.map((p) =>
              p.id === permissionId
                ? { ...p, status: 'resolved', decision, resolvedAt: new Date().toISOString() }
                : p
            ),
          }))
          break
        }
        case 'message.delta': {
          const delta = ((payload.text as string) ?? (payload.delta as string) ?? '')
          const messageId = payload.message_id as string | undefined
          if (!messageId) break
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) => {
              if (c.id !== convoId) return c
              const existing = c.messages.find((m) => m.id === messageId)
              if (existing) {
                return {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === messageId ? { ...m, content: m.content + delta, streaming: true } : m
                  ),
                }
              }
              const newMsg: ChatMessage = {
                id: messageId,
                role: 'assistant',
                content: delta,
                streaming: true,
                toolCallsBefore: [],
              }
              return { ...c, messages: [...c.messages, newMsg] }
            }),
          }))
          break
        }
        case 'tool.started': {
          const toolCallId = payload.tool_call_id as string | undefined
          const toolName = payload.tool as string | undefined
          const assistantMessageId = payload.assistant_message_id as string | undefined
          if (!toolCallId || !toolName) break
          const toolCall: ToolCall = {
            id: toolCallId,
            name: toolName,
            summary: (payload.summary as string) ?? `Run ${toolName}`,
            status: 'running',
            args: (payload.arguments as Record<string, unknown>) ?? {},
            accentColor: 'blue',
            expanded: false,
          }
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) => {
              if (c.id !== convoId) return c
              const foundIndex = assistantMessageId
                ? c.messages.findIndex((m) => m.id === assistantMessageId)
                : [...c.messages]
                    .map((m, idx) => ({ m, idx }))
                    .reverse()
                    .find(({ m }) => m.role === 'assistant')?.idx
              const targetIndex =
                typeof foundIndex === 'number' && foundIndex >= 0 ? foundIndex : undefined
              if (targetIndex === undefined) {
                const synthetic: ChatMessage = {
                  id: assistantMessageId ?? `assistant-${runIdFromPayload ?? toolCallId}`,
                  role: 'assistant',
                  content: '',
                  streaming: true,
                  toolCallsBefore: [toolCall],
                  activeToolCallId: toolCallId,
                }
                return { ...c, messages: [...c.messages, synthetic] }
              }
              return {
                ...c,
                messages: c.messages.map((msg, idx) =>
                  idx === targetIndex ? upsertToolCall(msg, toolCall) : msg
                ),
              }
            }),
          }))
          break
        }
        case 'tool.output': {
          const toolCallId = payload.tool_call_id as string | undefined
          const stream = payload.stream as 'stdout' | 'stderr' | undefined
          const text = (payload.text as string) ?? ''
          if (!toolCallId || !stream || !text) break
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) => {
              if (c.id !== convoId) return c
              return {
                ...c,
                messages: c.messages.map((msg) => {
                  const calls = msg.toolCallsBefore ?? []
                  if (!calls.some((tc) => tc.id === toolCallId)) return msg
                  return {
                    ...msg,
                    toolCallsBefore: calls.map((tc) => {
                      if (tc.id !== toolCallId) return tc
                      const current = stream === 'stdout' ? tc.stdout ?? '' : tc.stderr ?? ''
                      const nextValue = `${current}${text}`
                      return stream === 'stdout'
                        ? { ...tc, stdout: nextValue }
                        : { ...tc, stderr: nextValue }
                    }),
                  }
                }),
              }
            }),
          }))
          break
        }
        case 'tool.finished': {
          const toolCallId = payload.tool_call_id as string | undefined
          if (!toolCallId) break
          const toolStatus = toToolStatus(payload.status as string | undefined)
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) => {
              if (c.id !== convoId) return c
              return {
                ...c,
                messages: c.messages.map((msg) => {
                  const calls = msg.toolCallsBefore ?? []
                  if (!calls.some((tc) => tc.id === toolCallId)) return msg
                  return {
                    ...msg,
                    toolCallsBefore: calls.map((tc) =>
                      tc.id === toolCallId
                        ? {
                            ...tc,
                            status: toolStatus,
                            durationMs: (payload.duration_ms as number | undefined) ?? tc.durationMs,
                            summary: (payload.result_summary as string | undefined) ?? tc.summary,
                            accentColor: toolStatus === 'success' ? 'green' : 'pink',
                          }
                        : tc
                    ),
                  }
                }),
              }
            }),
          }))
          break
        }
        case 'message.completed': {
          const messageId = payload.message_id as string | undefined
          const content = payload.content as string | undefined
          if (!messageId) break
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) =>
              c.id === convoId
                ? {
                    ...c,
                    messages: c.messages.map((m) =>
                      m.id === messageId
                        ? { ...m, content: content ?? m.content, streaming: false }
                        : m
                    ),
                  }
                : c
            ),
          }))
          break
        }
        case 'conversation.title': {
          const title = payload.title as string | undefined
          if (!title) break
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) =>
              c.id === convoId ? { ...c, title } : c
            ),
          }))
          break
        }
        case 'context.loaded': {
          const items = payload.items as
            | { path: string; included: boolean; missing: boolean; byte_count: number | null; sha256: string | null }[]
            | undefined
          if (!items) break
          const files: ContextFile[] = items
            .filter((it) => it.included && !it.missing)
            .map((it, i) => {
              const parts = it.path.split('/')
              return {
                id: `ctx-${i}`,
                name: parts[parts.length - 1] || it.path,
                path: it.path,
                bytes: it.byte_count ?? undefined,
                hash: it.sha256 ?? undefined,
                tokenEstimate: it.byte_count ? Math.round(it.byte_count / 4) : undefined,
              }
            })
          setState((s) => ({ ...s, contextFiles: files }))
          break
        }
        case 'audit': {
          appendAudit({
            conversationId: convoId,
            event: (payload.action as string) ?? (payload.event as string) ?? 'audit',
            detail: (payload.summary as string) ?? (payload.detail as string | undefined),
          })
          break
        }
        case 'error': {
          appendAudit({
            conversationId: convoId,
            event: 'error',
            detail: (payload.message as string) ?? 'Unknown error',
          })
          break
        }
        default:
          break
      }
    },
    [activeConversationId, appendAudit]
  )

  useSSE({
    path: ssePath,
    onEvent: handleSSE,
    enabled: connected,
    resumeKey: activeConversationId || null,
  })

  // ── Message fetch on conversation switch ───────────────────────────────────
  useEffect(() => {
    if (!connected || !activeConversationId) return
    let cancelled = false
    Promise.all([
      api.listMessages(activeConversationId),
      api.getConversation(activeConversationId),
    ])
      .then(([msgs, conversation]) => {
        if (cancelled) return
        setState((s) => ({
          ...s,
          conversations: s.conversations.map((c) =>
            c.id === activeConversationId
              ? {
                  ...c,
                  messages: mergeFetchedMessages(c.messages, msgs.map(toUIMessage)),
                  contextMode: toUIContextMode(conversation.context_mode),
                  modelRoute: conversation.model_route,
                  incognitoRoute: conversation.incognito_route,
                  sensitiveUnlocked: conversation.sensitive_unlocked,
                }
              : c
          ),
        }))
      })
      .catch((err) => {
        handleBackendError(err)
      })
    return () => {
      cancelled = true
    }
  }, [connected, activeConversationId, handleBackendError])

  useEffect(() => {
    if (!connected || !activeConversationId) return
    const active = state.conversations.find((c) => c.id === activeConversationId)
    if (!active) return
    const nextSensitive = active.sensitiveUnlocked ?? state.sensitiveUnlocked
    if (nextSensitive === state.sensitiveUnlocked && nextSensitive === state.sensitive) {
      return
    }
    setState((s) => ({
      ...s,
      sensitiveUnlocked: nextSensitive,
      sensitive: nextSensitive,
    }))
  }, [
    connected,
    activeConversationId,
    state.conversations,
    state.sensitive,
    state.sensitiveUnlocked,
  ])

  const refreshVaultContextItems = useCallback(
    async (conversationId: string, clearOnUnavailable = true) => {
      try {
        const pins = await api.listConversationContextPins(conversationId)
        if (activeConversationIdRef.current !== conversationId) return
        const pinItems = normalizeVaultContextItems(pins, { defaultPinned: true })
        if (!pinItems.length) {
          setState((s) => ({ ...s, vaultContextItems: [] }))
          return
        }
        try {
          const preview = await api.previewConversationContext(
            conversationId,
            pinItems.map((item) => item.path)
          )
          const previewItems = normalizeVaultContextItems(preview)
          if (activeConversationIdRef.current !== conversationId) return
          setState((s) => ({
            ...s,
            vaultContextItems: previewItems.length
              ? previewItems.map((item) => ({ ...item, pinned: true }))
              : pinItems,
          }))
        } catch {
          if (activeConversationIdRef.current !== conversationId) return
          setState((s) => ({ ...s, vaultContextItems: pinItems }))
        }
      } catch (err) {
        if (handleBackendError(err)) return
        if (
          clearOnUnavailable &&
          err instanceof BackendError &&
          (err.status === 404 || err.status === 405)
        ) {
          if (activeConversationIdRef.current !== conversationId) return
          setState((s) => ({ ...s, vaultContextItems: [] }))
        }
      }
    },
    [handleBackendError]
  )

  useEffect(() => {
    if (!connected || !activeConversationId) {
      setState((s) => (s.vaultContextItems?.length ? { ...s, vaultContextItems: [] } : s))
      return
    }
    setState((s) => (s.vaultContextItems?.length ? { ...s, vaultContextItems: [] } : s))
    refreshVaultContextItems(activeConversationId)
  }, [activeConversationId, connected, refreshVaultContextItems])

  // ── Handlers ────────────────────────────────────────────────────────────────

  const patchState = useCallback(<K extends keyof BackendState>(key: K, value: BackendState[K]) => {
    setState((s) => ({ ...s, [key]: value }))
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setState((s) => ({
      ...s,
      ...(() => {
        const selected = s.conversations.find((c) => c.id === id)
        const nextContext = selected?.contextMode ?? s.contextMode
        const nextSensitive = selected?.sensitiveUnlocked ?? s.sensitiveUnlocked
        return {
          contextMode: nextContext,
          blankSlate: nextContext === 'Blank-slate',
          model: selected?.modelRoute ?? s.defaultModel,
          incognito: selected?.incognitoRoute ?? s.incognito,
          sensitiveUnlocked: nextSensitive,
          sensitive: nextSensitive,
        }
      })(),
      activeConversationId: id,
      leftSidebarOpen: false,
      conversations: s.conversations.map((c) => ({ ...c, active: c.id === id })),
    }))
  }, [])

  const handleNewConversation = useCallback(async () => {
    if (!connected) {
      const id = makeId()
      const newConv: Conversation = {
        id,
        title: 'New conversation',
        timestamp: 'Just now',
        contextMode: state.contextMode,
        modelRoute: state.model,
        incognitoRoute: state.incognito,
        sensitiveUnlocked: false,
        messages: [],
      }
      setState((s) => ({
        ...s,
        conversations: [newConv, ...s.conversations],
        activeConversationId: id,
        leftSidebarOpen: false,
        sensitiveUnlocked: false,
        sensitive: false,
      }))
      return
    }
    try {
      const created = await api.createConversation({
        context_mode: toBackendContextModeFromState(state, state.contextMode),
        incognito_route: state.incognito,
      })
      const uiConv = toUIConversation(created)
      setState((s) => ({
        ...s,
        conversations: [uiConv, ...s.conversations],
        activeConversationId: uiConv.id,
        leftSidebarOpen: false,
        contextMode: uiConv.contextMode ?? s.contextMode,
        blankSlate: (uiConv.contextMode ?? s.contextMode) === 'Blank-slate',
        model: uiConv.modelRoute ?? s.defaultModel,
        incognito: uiConv.incognitoRoute ?? s.incognito,
        sensitiveUnlocked: uiConv.sensitiveUnlocked ?? false,
        sensitive: uiConv.sensitiveUnlocked ?? false,
      }))
    } catch (err) {
      handleBackendError(err)
      /* ignore */
    }
  }, [connected, handleBackendError, state])

  const handleSend = useCallback(
    async (content: string) => {
      const convoId = activeConversationId
      if (!convoId) return

      const userMsg: ChatMessage = {
        id: makeId(),
        role: 'user',
        content,
        toolCallsBefore: [],
      }

      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === convoId ? { ...c, messages: [...c.messages, userMsg] } : c
        ),
      }))

      if (!connected) return

      try {
        const resp = await api.submitPrompt(convoId, {
          content,
          context_mode: toBackendContextModeFromState(state, state.contextMode),
          model_route: state.model,
          incognito_route: state.incognito,
          selected_context_paths: (state.vaultContextItems ?? [])
            .filter((item) => item.pinned && !item.excluded)
            .map((item) => item.path),
        })
        setState((s) => ({
          ...s,
          conversations: s.conversations.map((c) =>
            c.id === convoId
              ? {
                  ...c,
                  runStatus: resp.status as RunStatus,
                  messages: c.messages.map((m) =>
                    m.id === userMsg.id ? { ...m, id: resp.message_id, runId: resp.run_id } : m
                  ),
                }
              : c
          ),
        }))
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({
          ...s,
          conversations: s.conversations.map((c) =>
            c.id === convoId
              ? { ...c, runStatus: 'failed' as RunStatus }
              : c
          ),
        }))
      }
    },
    [activeConversationId, connected, handleBackendError, state]
  )

  const handlePreviewVaultContext = useCallback(
    async (content: string) => {
      if (!connected || !activeConversationId) return
      const trimmed = content.trim()
      if (trimmed.length < 3) {
        setState((s) => ({
          ...s,
          vaultContextItems: (s.vaultContextItems ?? []).filter((item) => item.pinned),
        }))
        return
      }
      try {
        const preview = await api.previewVaultContext(trimmed)
        if (activeConversationIdRef.current !== activeConversationId) return
        const previewItems = normalizeVaultContextItems(preview, { defaultPinned: false })
        setState((s) => {
          const pinnedItems = (s.vaultContextItems ?? []).filter((item) => item.pinned)
          const byPath = new Map<string, VaultContextItem>()
          for (const item of pinnedItems) byPath.set(item.path, item)
          for (const item of previewItems) {
            if (!byPath.has(item.path)) byPath.set(item.path, item)
          }
          return { ...s, vaultContextItems: Array.from(byPath.values()) }
        })
      } catch (err) {
        handleBackendError(err)
      }
    },
    [activeConversationId, connected, handleBackendError]
  )

  const handleToggleTool = useCallback(
    async (toolId: string) => {
      const tool = state.tools.find((t) => t.id === toolId)
      if (!tool) return
      const nextEnabled = !tool.enabled

      setState((s) => ({
        ...s,
        tools: s.tools.map((t) => (t.id === toolId ? { ...t, enabled: nextEnabled } : t)),
      }))

      if (!connected) return
      try {
        await api.patchTool(tool.name, {
          enabled: nextEnabled,
          conversation_id: activeConversationId || undefined,
        })
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({
          ...s,
          tools: s.tools.map((t) => (t.id === toolId ? { ...t, enabled: !nextEnabled } : t)),
        }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.tools]
  )

  const handleSetToolApprovalPolicy = useCallback(
    async (toolName: string, policy: 'auto' | 'confirm') => {
      if (!connected) return
      try {
        await api.patchTool(toolName, {
          approval_policy: policy,
          conversation_id: activeConversationId || undefined,
        })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [activeConversationId, connected, handleBackendError]
  )

  const handleUnlockSensitive = useCallback(async () => {
    if (!activeConversationId) return
    if (!connected) {
      setState((s) => ({ ...s, sensitiveUnlocked: true, sensitive: true }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.unlocked',
        detail: 'Local mock unlock',
      })
      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === activeConversationId ? { ...c, sensitiveUnlocked: true } : c
        ),
      }))
      return
    }
    try {
      const resp = await api.unlockSensitive(activeConversationId)
      setState((s) => ({
        ...s,
        sensitiveUnlocked: resp.sensitive_unlocked,
        sensitive: resp.sensitive_unlocked,
        conversations: s.conversations.map((c) =>
          c.id === activeConversationId
            ? { ...c, sensitiveUnlocked: resp.sensitive_unlocked }
            : c
        ),
      }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.unlocked',
      })
    } catch (err) {
      handleBackendError(err)
      /* ignore */
    }
  }, [activeConversationId, connected, appendAudit, handleBackendError])

  const handleLockSensitive = useCallback(async () => {
    if (!activeConversationId) return
    if (!connected) {
      setState((s) => ({ ...s, sensitiveUnlocked: false, sensitive: false }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.locked',
        detail: 'Local mock lock',
      })
      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === activeConversationId ? { ...c, sensitiveUnlocked: false } : c
        ),
      }))
      return
    }
    try {
      const resp = await api.lockSensitive(activeConversationId)
      setState((s) => ({
        ...s,
        sensitiveUnlocked: resp.sensitive_unlocked,
        sensitive: resp.sensitive_unlocked,
        conversations: s.conversations.map((c) =>
          c.id === activeConversationId
            ? { ...c, sensitiveUnlocked: resp.sensitive_unlocked }
            : c
        ),
      }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.locked',
      })
    } catch (err) {
      handleBackendError(err)
      /* ignore */
    }
  }, [activeConversationId, connected, appendAudit, handleBackendError])

  const handleRunDirectAction = useCallback(
    async (actionId: string) => {
      const action = state.directActions.find((a) => a.id === actionId)
      if (!action) return
      setState((s) => ({
        ...s,
        directActions: s.directActions.map((a) =>
          a.id === actionId ? { ...a, status: 'running' } : a
        ),
      }))
      if (!connected) {
        setTimeout(() => {
          setState((s) => ({
            ...s,
            directActions: s.directActions.map((a) =>
              a.id === actionId
                ? { ...a, status: 'done', result: `Mock at ${new Date().toLocaleTimeString()}` }
                : a
            ),
          }))
        }, 1500)
        return
      }
      try {
        const run = await api.runAction(action.id, activeConversationId || undefined)
        setState((s) => ({
          ...s,
          directActions: s.directActions.map((a) =>
            a.id === actionId
              ? {
                  ...a,
                  status: run.status === 'success' ? 'done' : 'error',
                  result:
                    run.stdout_preview ??
                    run.error_message ??
                    `exit=${run.exit_code ?? '?'}`,
                }
              : a
          ),
        }))
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({
          ...s,
          directActions: s.directActions.map((a) =>
            a.id === actionId ? { ...a, status: 'error' } : a
          ),
        }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.directActions]
  )

  const handleWorkerAction = useCallback(
    async (workerId: string, action: 'capture' | 'stop' | 'kill') => {
      if (!connected) return
      // Optimistic: stop/kill flip to 'stopped'; capture doesn't flip so
      // we don't reset the live-polling UI on every refresh tick.
      if (action === 'stop' || action === 'kill') {
        setState((s) => ({
          ...s,
          workers: s.workers.map((w) =>
            w.id === workerId ? { ...w, status: 'stopped' as const } : w
          ),
        }))
      }
      try {
        if (action === 'stop') await api.stopWorker(workerId)
        else if (action === 'kill') await api.killWorker(workerId)
        else if (action === 'capture') {
          const out = await api.getWorkerOutput(workerId, 200)
          setState((s) => ({
            ...s,
            workers: s.workers.map((w) => {
              if (w.id !== workerId) return w
              // Preserve running/stopped status; don't force 'idle'.
              return { ...w, output: out.output }
            }),
          }))
        }
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  // Summarize: capture pane, then spawn a new conversation titled
  // "Worker summary: <name>" and submit a prompt against the persisted
  // task model setting.
  const handleSummarizeWorker = useCallback(
    async (workerId: string) => {
      if (!connected) return
      const worker = state.workers.find((w) => w.id === workerId)
      if (!worker) return
      try {
        const cap = await api.getWorkerOutput(workerId, 500)
        const taskModel = state.taskModel
        const created = await api.createConversation({
          title: `Worker summary: ${worker.name}`,
          context_mode: 'blank_slate',
          model_route: taskModel,
        })
        const uiConv = toUIConversation(created)
        setState((s) => ({
          ...s,
          conversations: [uiConv, ...s.conversations],
          activeConversationId: uiConv.id,
          rightPanel: null,
          blankSlate: true,
        }))
        const prompt =
          `Summarize the current state of the tmux session for worker ` +
          `"${worker.name}" (type ${worker.type}, host ${worker.host}). ` +
          `Report: what it is doing right now, recent actions, any visible ` +
          `errors or prompts waiting on input, and whether it looks idle or active. ` +
          `Be concise — 5 bullet points or fewer.\n\n` +
          `--- pane capture (last 500 lines) ---\n` +
          (cap.output || '(empty)')
        await api.submitPrompt(uiConv.id, {
          content: prompt,
          context_mode: 'blank_slate',
          model_route: taskModel,
        })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError, state.taskModel, state.workers]
  )

  const handleRenameWorker = useCallback(
    async (workerId: string, name: string) => {
      const trimmed = name.trim()
      if (!trimmed) return
      if (!connected) {
        setState((s) => ({
          ...s,
          workers: s.workers.map((w) => (w.id === workerId ? { ...w, name: trimmed } : w)),
        }))
        return
      }
      try {
        const updated = await api.patchWorker(workerId, { name: trimmed })
        setState((s) => ({
          ...s,
          workers: s.workers.map((w) =>
            w.id === workerId ? { ...toUIWorker(updated), output: w.output } : w
          ),
        }))
      } catch (err) {
        handleBackendError(err)
      }
    },
    [connected, handleBackendError]
  )

  const handleStartWorker = useCallback(
    async (workerTypeId: string) => {
      const uiType = toUIWorkerType(workerTypeId)
      if (!connected) {
        const newWorker: Worker = {
          id: makeId(),
          name: `${workerTypeId} session`,
          type: uiType,
          host: workerTypeId === 'winpc_shell' ? 'winpc' : 'local',
          status: 'running',
          startedAt: 'Just now',
          lastActivity: 'Just now',
        }
        setState((s) => ({ ...s, workers: [newWorker, ...s.workers] }))
        return
      }
      try {
        const created = await api.createWorker({
          worker_type: workerTypeId,
          conversation_id: activeConversationId || null,
        })
        setState((s) => ({ ...s, workers: [toUIWorker(created), ...s.workers] }))
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [activeConversationId, connected, handleBackendError]
  )

  const startEditTitle = useCallback(() => {
    const active = state.conversations.find((c) => c.id === state.activeConversationId)
    setTitleDraft(active?.title ?? '')
    setEditingTitle(true)
  }, [state.conversations, state.activeConversationId])

  const commitTitle = useCallback(async () => {
    const trimmed = titleDraft.trim()
    setEditingTitle(false)
    if (!trimmed) return
    const convoId = state.activeConversationId
    setState((s) => ({
      ...s,
      conversations: s.conversations.map((c) =>
        c.id === convoId ? { ...c, title: trimmed } : c
      ),
    }))
    if (!convoId) return
    if (connected) {
      try {
        await api.patchConversation(convoId, { title: trimmed })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    }
  }, [titleDraft, state.activeConversationId, connected, handleBackendError])

  const handleChangeTheme = useCallback((theme: ThemeName) => {
    patchState('theme', theme)
  }, [patchState])

  const handleRefreshHealth = useCallback(async () => {
    if (!connected) return
    try {
      const health = await api.health()
      setState((s) => ({
        ...s,
        healthEntries: toHealthEntriesFromHealth(health),
        healthSystem: toUIHealthSystem(health.system),
      }))
    } catch (err) {
      if (!handleBackendError(err)) {
        setState((s) => ({ ...s, connection: 'offline' }))
      }
    }
  }, [connected, handleBackendError])

  const handleChangeModel = useCallback((model: string) => {
    setState((s) => ({ ...s, model }))
  }, [])

  const handleChangeDefaultModel = useCallback(
    async (model: string) => {
      const prev = state.defaultModel
      setState((s) => ({ ...s, defaultModel: model }))
      if (!connected) return
      try {
        await api.patchSettings({ model_default: model }, activeConversationId || undefined)
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({ ...s, defaultModel: prev }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.defaultModel]
  )

  const handleChangeTaskModel = useCallback(
    async (model: string) => {
      const prev = state.taskModel
      setState((s) => ({ ...s, taskModel: model }))
      if (!connected) return
      try {
        await api.patchSettings({ task_model: model }, activeConversationId || undefined)
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({ ...s, taskModel: prev }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.taskModel]
  )

  const handleSetContextMode = useCallback(
    async (mode: AppState['contextMode']) => {
      const prevMode = state.contextMode
      const prevBlankSlate = state.blankSlate
      setState((s) => ({ ...s, contextMode: mode, blankSlate: mode === 'Blank-slate' }))
      if (!connected) return
      try {
        await api.patchSettings(
          { context_mode: mode === 'Blank-slate' ? 'blank_slate' : 'normal' },
          activeConversationId || undefined
        )
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({ ...s, contextMode: prevMode, blankSlate: prevBlankSlate }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.blankSlate, state.contextMode]
  )

  const handleToggleTitleGeneration = useCallback(async () => {
    const next = !state.titleGeneration
    setState((s) => ({ ...s, titleGeneration: next }))
    if (!connected) return
    try {
      await api.patchSettings({ title_generation_enabled: next }, activeConversationId || undefined)
    } catch (err) {
      handleBackendError(err)
      setState((s) => ({ ...s, titleGeneration: !next }))
    }
  }, [activeConversationId, connected, handleBackendError, state.titleGeneration])

  const handleChangeSystemContext = useCallback(
    async (value: string) => {
      const prev = state.systemContext
      setState((s) => ({ ...s, systemContext: value }))
      if (!connected) return
      try {
        await api.patchContextFile('system-context', value, activeConversationId || undefined)
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({ ...s, systemContext: prev }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.systemContext]
  )

  const handleChangeShortTermContinuity = useCallback(
    async (value: string) => {
      const prev = state.shortTermContinuity
      setState((s) => ({ ...s, shortTermContinuity: value }))
      if (!connected) return
      try {
        await api.patchContextFile('short-term-continuity', value, activeConversationId || undefined)
      } catch (err) {
        handleBackendError(err)
        setState((s) => ({ ...s, shortTermContinuity: prev }))
      }
    },
    [activeConversationId, connected, handleBackendError, state.shortTermContinuity]
  )

  const openPanel = useCallback(
    (id: RightPanelId) => {
      setState((s) => ({ ...s, rightPanel: s.rightPanel === id ? null : id }))
    },
    []
  )
  const closePanel = useCallback(() => patchState('rightPanel', null), [patchState])
  const toggleLeft = useCallback(() => {
    setState((s) => ({ ...s, leftSidebarOpen: !s.leftSidebarOpen }))
  }, [])

  const handleDismissFile = useCallback(
    (fileId: string) => {
      setState((s) => ({ ...s, contextFiles: s.contextFiles.filter((f) => f.id !== fileId) }))
    },
    []
  )

  const handleAddVaultContext = useCallback(
    async (itemsOrPaths: Array<string | VaultContextItem | VaultNoteDetail>) => {
      if (!activeConversationId || !itemsOrPaths.length) return
      const optimisticItems = itemsOrPaths.map((item) => {
        if (typeof item === 'string') return vaultItemFromPath(item)
        if ('content' in item) return vaultContextItemFromNote(item)
        return { ...item, id: item.id || item.path, pinned: item.pinned ?? true }
      })
      const paths = Array.from(new Set(optimisticItems.map((item) => item.path)))

      setState((s) => {
        const byPath = new Map((s.vaultContextItems ?? []).map((item) => [item.path, item]))
        for (const item of optimisticItems) byPath.set(item.path, { ...byPath.get(item.path), ...item })
        return { ...s, vaultContextItems: Array.from(byPath.values()) }
      })

      if (!connected) return
      try {
        await api.pinContext(activeConversationId, paths)
        await refreshVaultContextItems(activeConversationId, false)
      } catch (err) {
        if (handleBackendError(err)) return
        /* keep optimistic chips when the optional backend endpoint is absent */
      }
    },
    [activeConversationId, connected, handleBackendError, refreshVaultContextItems]
  )

  const handleRemoveVaultContext = useCallback(
    async (path: string) => {
      setState((s) => ({
        ...s,
        vaultContextItems: (s.vaultContextItems ?? []).filter((item) => item.path !== path),
      }))
      if (!connected || !activeConversationId) return
      try {
        await api.unpinContext(activeConversationId, path)
        await refreshVaultContextItems(activeConversationId)
      } catch (err) {
        handleBackendError(err)
        /* keep local removal if the optional backend endpoint is absent */
      }
    },
    [activeConversationId, connected, handleBackendError, refreshVaultContextItems]
  )

  // ── Folders ────────────────────────────────────────────────────────────────
  const handleCreateFolder = useCallback(
    async (name: string, parentId: string | null = null) => {
      if (!connected) return
      try {
        const created = await api.createFolder({ name, parent_id: parentId })
        setState((s) => ({ ...s, folders: [...s.folders, toUIFolder(created)] }))
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleRenameFolder = useCallback(
    async (id: string, name: string) => {
      setState((s) => ({
        ...s,
        folders: s.folders.map((f) => (f.id === id ? { ...f, name } : f)),
      }))
      if (!connected) return
      try {
        await api.patchFolder(id, { name })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleMoveFolder = useCallback(
    async (id: string, parentId: string | null) => {
      setState((s) => ({
        ...s,
        folders: s.folders.map((f) => (f.id === id ? { ...f, parentId } : f)),
      }))
      if (!connected) return
      try {
        await api.patchFolder(id, { parent_id: parentId })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleDeleteFolder = useCallback(
    async (id: string) => {
      setState((s) => ({
        ...s,
        folders: s.folders.filter((f) => f.id !== id),
        conversations: s.conversations.map((c) =>
          c.folderId === id ? { ...c, folderId: null } : c
        ),
      }))
      if (!connected) return
      try {
        await api.deleteFolder(id)
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleMoveConversation = useCallback(
    async (convoId: string, folderId: string | null) => {
      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === convoId ? { ...c, folderId } : c
        ),
      }))
      if (!connected) return
      try {
        await api.patchConversation(convoId, { folder_id: folderId })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleDeleteConversation = useCallback(
    async (convoId: string) => {
      setState((s) => {
        const filtered = s.conversations.filter((c) => c.id !== convoId)
        const nextActive = s.activeConversationId === convoId ? filtered[0]?.id ?? '' : s.activeConversationId
        return { ...s, conversations: filtered, activeConversationId: nextActive }
      })
      if (!connected) return
      try {
        await api.deleteConversation(convoId)
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleArchiveConversation = useCallback(
    async (convoId: string, archived: boolean) => {
      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === convoId ? { ...c, archived } : c
        ),
      }))
      if (!connected) return
      try {
        await api.patchConversation(convoId, { archived })
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  // ── Permissions ────────────────────────────────────────────────────────────
  const handleResolvePermission = useCallback(
    async (permissionId: string, decision: 'approved' | 'denied', note?: string) => {
      if (!connected) return
      try {
        const resolved = await api.resolvePermission(permissionId, { decision, note: note ?? null })
        setState((s) => ({
          ...s,
          permissions: s.permissions.map((p) =>
            p.id === permissionId ? toUIPermission(resolved) : p
          ),
        }))
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  // ── Runs (retry/cancel) ────────────────────────────────────────────────────
  const handleRetryRun = useCallback(
    async (runId: string) => {
      if (!connected) return
      try {
        const run = await api.retryRun(runId)
        // Retry returns a new run; keep the UI runId aligned so the next
        // cancel/retry acts on the right run.
        setState((s) => ({
          ...s,
          conversations: s.conversations.map((c) => {
            if (c.id !== run.conversation_id) return c
            return {
              ...c,
              runStatus: run.status as RunStatus,
              messages: c.messages.map((m) =>
                m.runId === runId ? { ...m, runId: run.id } : m
              ),
            }
          }),
        }))
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  const handleCancelRun = useCallback(
    async (runId: string) => {
      if (!connected) return
      try {
        await api.cancelRun(runId)
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  // ── Usage ──────────────────────────────────────────────────────────────────
  const handleRefreshUsage = useCallback(
    async (opts: { refreshSubscriptions?: boolean } = {}) => {
      if (!connected) return
      try {
        const [usage, subs] = await Promise.all([
          api.getUsage(),
          opts.refreshSubscriptions ? api.getSubscriptions(true) : Promise.resolve(null),
        ])
        setState((s) => ({
          ...s,
          usageProviders: usage.providers.map(toUIUsageProvider),
          subscriptions: Object.values((subs ?? usage.subscriptions).providers)
            .filter(Boolean)
            .map((provider) => toUISubscriptionProvider(provider)),
        }))
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  // ── Syncthing ──────────────────────────────────────────────────────────────
  const handleRefreshSyncthing = useCallback(async () => {
    if (!connected) return
    try {
      const [summary, conflicts] = await Promise.all([
        api.getSyncthingSummary(),
        api.getSyncthingConflicts(),
      ])
      setState((s) => ({
        ...s,
        syncthingDevices: summary.devices.map(toUISyncthingDevice),
        syncthingConflicts: conflicts.conflicts.map(toUISyncthingConflict),
      }))
    } catch (err) {
      handleBackendError(err)
      /* ignore */
    }
  }, [connected, handleBackendError])

  const handleResolveSyncthingConflict = useCallback(
    async (path: string, action: BackendSyncthingResolveAction, note?: string) => {
      if (!connected) return
      try {
        await api.resolveSyncthingConflict({ path, action, note: note ?? null })
        setState((s) => ({
          ...s,
          syncthingConflicts: s.syncthingConflicts.filter((c) => c.path !== path),
        }))
      } catch (err) {
        handleBackendError(err)
        /* ignore */
      }
    },
    [connected, handleBackendError]
  )

  // ── Copilot hard-override ──────────────────────────────────────────────────
  const handleToggleCopilotHardOverride = useCallback(async () => {
    const next = !state.copilotBudgetHardOverride
    setState((s) => ({ ...s, copilotBudgetHardOverride: next }))
    if (!connected) return
    try {
      await api.patchSettings(
        { copilot_budget_hard_override_enabled: next },
        activeConversationId || undefined
      )
    } catch (err) {
      handleBackendError(err)
      setState((s) => ({ ...s, copilotBudgetHardOverride: !next }))
    }
  }, [activeConversationId, connected, handleBackendError, state.copilotBudgetHardOverride])

  return {
    state,
    editingTitle,
    titleDraft,
    setTitleDraft,
    setEditingTitle,
    startEditTitle,
    commitTitle,
    patchState,
    openPanel,
    closePanel,
    toggleLeft,
    handleSelectConversation,
    handleNewConversation,
    handleSend,
    handleToggleTool,
    handleSetToolApprovalPolicy,
    handleUnlockSensitive,
    handleLockSensitive,
    handleRunDirectAction,
    handleWorkerAction,
    handleStartWorker,
    handleChangeTheme,
    handleDismissFile,
    handleAddVaultContext,
    handleRemoveVaultContext,
    handlePreviewVaultContext,
    handleRefreshHealth,
    handleChangeModel,
    handleChangeDefaultModel,
    handleChangeTaskModel,
    handleSetContextMode,
    handleToggleTitleGeneration,
    handleChangeSystemContext,
    handleChangeShortTermContinuity,
    handleCreateFolder,
    handleRenameFolder,
    handleMoveFolder,
    handleDeleteFolder,
    handleMoveConversation,
    handleDeleteConversation,
    handleArchiveConversation,
    handleResolvePermission,
    handleRetryRun,
    handleCancelRun,
    handleRefreshUsage,
    handleRefreshSyncthing,
    handleResolveSyncthingConflict,
    handleToggleCopilotHardOverride,
    handleSummarizeWorker,
    handleRenameWorker,
    retryConnection,
    setState,
  }
}
