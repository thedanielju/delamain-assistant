'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, BackendUnreachableError } from '@/lib/api'
import { MOCK_MODE } from '@/lib/config'
import {
  toUIContextFiles,
  toUIConversation,
  toUIDirectAction,
  toUIMessage,
  toUITool,
  toUIWorker,
} from '@/lib/mappers'
import { INITIAL_STATE } from '@/lib/sample-data'
import { useSSE } from '@/lib/sse'
import type {
  BackendContextMode,
  BackendMessage,
  BackendSSEEvent,
} from '@/lib/backend-types'
import type {
  AppState,
  ChatMessage,
  Conversation,
  ContextFile,
  RightPanelId,
  RunStatus,
  ThemeName,
  Worker,
} from '@/lib/types'

export type BackendConnection = 'probing' | 'connected' | 'offline' | 'mock'

export interface AuditEntry {
  id: string
  conversationId: string
  event: string
  detail?: string
  timestamp: string
}

interface BackendState extends AppState {
  connection: BackendConnection
  audit: AuditEntry[]
}

function makeId(): string {
  return Math.random().toString(36).slice(2, 10)
}

function toBackendContextModeFromState(s: Pick<AppState, 'contextMode' | 'blankSlate'>): BackendContextMode {
  if (s.blankSlate || s.contextMode === 'Blank-slate') return 'blank_slate'
  return 'normal'
}

export function useDelamainBackend() {
  const [state, setState] = useState<BackendState>({
    ...INITIAL_STATE,
    connection: MOCK_MODE ? 'mock' : 'probing',
    audit: [],
    conversations: MOCK_MODE ? INITIAL_STATE.conversations : [],
    activeConversationId: MOCK_MODE ? INITIAL_STATE.activeConversationId : '',
  })

  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')

  const activeConversationId = state.activeConversationId
  const connected = state.connection === 'connected'

  // ── Initial load ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (MOCK_MODE) return
    let cancelled = false

    const load = async () => {
      try {
        await api.health()
      } catch (err) {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            connection: err instanceof BackendUnreachableError ? 'offline' : 'offline',
          }))
        }
        return
      }

      try {
        const [conversations, toolsResp, actionsResp, ctx] = await Promise.all([
          api.listConversations(),
          api.getTools(),
          api.listActions(),
          api.getContextCurrent('normal').catch(() => null),
        ])

        if (cancelled) return

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

        if (cancelled) return

        setState((s) => ({
          ...s,
          connection: 'connected',
          conversations: convsWithMessages,
          activeConversationId: firstId,
          tools: toolsResp.tools.map(toUITool),
          directActions: actionsResp.actions.map(toUIDirectAction),
          contextFiles: ctx ? toUIContextFiles(ctx) : s.contextFiles,
        }))
      } catch {
        if (!cancelled) setState((s) => ({ ...s, connection: 'offline' }))
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

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
      const payload = ev.payload ?? {}
      const convoId = (payload.conversation_id as string | undefined) ?? activeConversationId

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
          setState((s) => ({
            ...s,
            conversations: s.conversations.map((c) =>
              c.id === convoId ? { ...c, runStatus: status } : c
            ),
          }))
          break
        }
        case 'message.delta': {
          const delta = (payload.delta as string) ?? ''
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
            event: (payload.event as string) ?? 'audit',
            detail: payload.detail as string | undefined,
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

  useSSE({ path: ssePath, onEvent: handleSSE, enabled: connected })

  // ── Lazy message fetch on conversation switch ───────────────────────────────
  const loadedConvosRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!connected || !activeConversationId) return
    if (loadedConvosRef.current.has(activeConversationId)) return
    loadedConvosRef.current.add(activeConversationId)
    let cancelled = false
    api
      .listMessages(activeConversationId)
      .then((msgs) => {
        if (cancelled) return
        setState((s) => ({
          ...s,
          conversations: s.conversations.map((c) =>
            c.id === activeConversationId ? { ...c, messages: msgs.map(toUIMessage) } : c
          ),
        }))
      })
      .catch(() => {
        /* no-op */
      })
    return () => {
      cancelled = true
    }
  }, [connected, activeConversationId])

  // ── Handlers ────────────────────────────────────────────────────────────────

  const patchState = useCallback(<K extends keyof BackendState>(key: K, value: BackendState[K]) => {
    setState((s) => ({ ...s, [key]: value }))
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setState((s) => ({
      ...s,
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
        messages: [],
      }
      setState((s) => ({
        ...s,
        conversations: [newConv, ...s.conversations],
        activeConversationId: id,
        leftSidebarOpen: false,
      }))
      return
    }
    try {
      const created = await api.createConversation({
        context_mode: toBackendContextModeFromState(state),
        incognito_route: state.incognito,
      })
      const uiConv = toUIConversation(created)
      setState((s) => ({
        ...s,
        conversations: [uiConv, ...s.conversations],
        activeConversationId: uiConv.id,
        leftSidebarOpen: false,
      }))
    } catch {
      /* ignore */
    }
  }, [connected, state])

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
        await api.submitPrompt(convoId, {
          content,
          context_mode: toBackendContextModeFromState(state),
          incognito_route: state.incognito,
        })
      } catch {
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
    [activeConversationId, connected, state]
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
        await api.patchTool(tool.name, nextEnabled, activeConversationId || undefined)
      } catch {
        setState((s) => ({
          ...s,
          tools: s.tools.map((t) => (t.id === toolId ? { ...t, enabled: !nextEnabled } : t)),
        }))
      }
    },
    [activeConversationId, connected, state.tools]
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
      return
    }
    try {
      const resp = await api.unlockSensitive(activeConversationId)
      setState((s) => ({
        ...s,
        sensitiveUnlocked: resp.sensitive_unlocked,
        sensitive: resp.sensitive_unlocked,
      }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.unlocked',
      })
    } catch {
      /* ignore */
    }
  }, [activeConversationId, connected, appendAudit])

  const handleLockSensitive = useCallback(async () => {
    if (!activeConversationId) return
    if (!connected) {
      setState((s) => ({ ...s, sensitiveUnlocked: false, sensitive: false }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.locked',
        detail: 'Local mock lock',
      })
      return
    }
    try {
      const resp = await api.lockSensitive(activeConversationId)
      setState((s) => ({
        ...s,
        sensitiveUnlocked: resp.sensitive_unlocked,
        sensitive: resp.sensitive_unlocked,
      }))
      appendAudit({
        conversationId: activeConversationId,
        event: 'sensitive.locked',
      })
    } catch {
      /* ignore */
    }
  }, [activeConversationId, connected, appendAudit])

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
      } catch {
        setState((s) => ({
          ...s,
          directActions: s.directActions.map((a) =>
            a.id === actionId ? { ...a, status: 'error' } : a
          ),
        }))
      }
    },
    [activeConversationId, connected, state.directActions]
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
      } catch {
        /* ignore */
      }
    },
    [connected]
  )

  const handleStartWorker = useCallback(
    async (type: Worker['type']) => {
      if (!connected) {
        const newWorker: Worker = {
          id: makeId(),
          name: `${type} session`,
          type,
          host: 'local',
          status: 'running',
          startedAt: 'Just now',
          lastActivity: 'Just now',
        }
        setState((s) => ({ ...s, workers: [newWorker, ...s.workers] }))
        return
      }
      try {
        const created = await api.createWorker({
          worker_type: type,
          conversation_id: activeConversationId || null,
        })
        setState((s) => ({ ...s, workers: [toUIWorker(created), ...s.workers] }))
      } catch {
        /* ignore */
      }
    },
    [activeConversationId, connected]
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
    if (connected) {
      try {
        await api.patchConversation(convoId, { title: trimmed })
      } catch {
        /* ignore */
      }
    }
  }, [titleDraft, state.activeConversationId, connected])

  const handleChangeTheme = useCallback((theme: ThemeName) => {
    patchState('theme', theme)
  }, [patchState])

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
    handleUnlockSensitive,
    handleLockSensitive,
    handleRunDirectAction,
    handleWorkerAction,
    handleStartWorker,
    handleChangeTheme,
    handleDismissFile,
    setState,
  }
}
