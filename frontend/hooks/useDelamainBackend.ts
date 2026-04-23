'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, AuthRequiredError, BackendUnreachableError } from '@/lib/api'
import { MOCK_MODE } from '@/lib/config'
import {
  toHealthEntriesFromHealth,
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
  Folder,
  Permission,
  RightPanelId,
  RunStatus,
  SubscriptionProvider,
  SyncthingConflict,
  SyncthingDevice,
  ToolCall,
  ThemeName,
  UsageProviderSummary,
  Worker,
} from '@/lib/types'

export type BackendConnection = 'probing' | 'connected' | 'offline' | 'auth_required' | 'mock'

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
  if (workerTypeId === 'opencode') return 'opencode'
  if (workerTypeId === 'claude_code') return 'claude'
  if (workerTypeId === 'winpc_shell') return 'winpc_shell'
  if (workerTypeId === 'shell') return 'tmux'
  return 'generic'
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

export function useDelamainBackend() {
  const [state, setState] = useState<BackendState>({
    ...INITIAL_STATE,
    connection: MOCK_MODE ? 'mock' : 'probing',
    authRedirectUrl: null,
    audit: [],
    conversations: MOCK_MODE ? INITIAL_STATE.conversations : [],
    activeConversationId: MOCK_MODE ? INITIAL_STATE.activeConversationId : '',
  })

  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')

  const activeConversationId = state.activeConversationId
  const connected = state.connection === 'connected'

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
          model: firstConversation?.modelRoute ?? settingsResp.settings.model_default,
          incognito: firstConversation?.incognitoRoute ?? s.incognito,
          sensitiveUnlocked: firstConversation?.sensitiveUnlocked ?? s.sensitiveUnlocked,
          sensitive: firstConversation?.sensitiveUnlocked ?? s.sensitive,
          modelOptions: [
            modelsResp.default,
            modelsResp.fallback_high_volume,
            modelsResp.fallback_cheap,
            modelsResp.paid_fallback,
          ].filter((value, index, arr): value is string => Boolean(value) && arr.indexOf(value) === index),
          budgetUsed: budgetResp?.copilot_budget.used_premium_requests ?? s.budgetUsed,
          budgetTotal: budgetResp?.copilot_budget.monthly_premium_requests ?? s.budgetTotal,
          healthEntries: toHealthEntriesFromHealth(health),
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
  }, [handleBackendError])

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
              const targetIndex = [...c.messages]
                .map((m, idx) => ({ m, idx }))
                .reverse()
                .find(({ m }) => m.role === 'assistant')?.idx
              if (targetIndex === undefined) {
                const synthetic: ChatMessage = {
                  id: `assistant-${runIdFromPayload ?? toolCallId}`,
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

  // ── Lazy message fetch on conversation switch ───────────────────────────────
  const loadedConvosRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!connected || !activeConversationId) return
    if (loadedConvosRef.current.has(activeConversationId)) return
    loadedConvosRef.current.add(activeConversationId)
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
                  messages: msgs.map(toUIMessage),
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
  }, [connected, activeConversationId])

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
          model: selected?.modelRoute ?? s.model,
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
        model: uiConv.modelRoute ?? s.model,
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
    async (workerId: string, action: 'capture' | 'summarize' | 'stop' | 'kill') => {
      setState((s) => ({
        ...s,
        workers: s.workers.map((w) => {
          if (w.id !== workerId) return w
          if (action === 'stop' || action === 'kill') return { ...w, status: 'stopped' as const }
          if (action === 'capture') return { ...w, status: 'capturing' as const }
          return w
        }),
      }))
      if (!connected) return
      try {
        if (action === 'stop') await api.stopWorker(workerId)
        else if (action === 'kill') await api.killWorker(workerId)
        else if (action === 'capture') {
          const out = await api.getWorkerOutput(workerId, 200)
          setState((s) => ({
            ...s,
            workers: s.workers.map((w) =>
              w.id === workerId ? { ...w, output: out.output, status: 'idle' as const } : w
            ),
          }))
        }
      } catch (err) {
        handleBackendError(err)
        /* ignore */
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
        await api.retryRun(runId)
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
    handleRefreshHealth,
    handleChangeModel,
    handleChangeDefaultModel,
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
    setState,
  }
}
