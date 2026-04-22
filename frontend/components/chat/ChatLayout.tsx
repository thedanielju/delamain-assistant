'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { Menu, Settings, Activity, Cpu, Pencil, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Sidebar } from './Sidebar'
import { ChatPane } from './ChatPane'
import { ContextBanner } from './ContextBanner'
import { InputBar } from './InputBar'
import { SettingsPanel } from './SettingsPanel'
import { HealthPanel } from './HealthPanel'
import { WorkersPanel } from './WorkersPanel'
import { ContextEditor } from './ContextEditor'
import { ModelBadge } from './ModelBadge'
import { RunStatusPill } from './RunStatusPill'
import { INITIAL_STATE } from '@/lib/sample-data'
import type { AppState, ChatMessage, Conversation, Worker, ThemeName, RightPanelId, ContextFile } from '@/lib/types'

function generateId() {
  return Math.random().toString(36).slice(2, 10)
}

function useDragResize(initial: number, min: number, max: number, edge: 'right-edge' | 'left-edge') {
  const [width, setWidth] = useState(initial)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(initial)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = width
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [width])

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const delta = edge === 'right-edge'
        ? e.clientX - startX.current
        : startX.current - e.clientX
      setWidth(Math.min(max, Math.max(min, startWidth.current + delta)))
    }
    const onUp = () => {
      if (!dragging.current) return
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [edge, max, min])

  return { width, onMouseDown }
}

function DragHandle({ onMouseDown, side }: { onMouseDown: (e: React.MouseEvent) => void; side: 'right' | 'left' }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className={cn(
        'absolute top-0 bottom-0 w-1.5 z-20 cursor-col-resize group',
        side === 'right' ? '-right-0.5' : '-left-0.5'
      )}
      aria-hidden="true"
    >
      <div className="w-full h-full bg-transparent group-hover:bg-white/[0.1] transition-colors rounded-full" />
    </div>
  )
}

export function PanelHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06] flex-shrink-0">
      <span className="text-[10px] font-mono font-semibold text-[#555555] uppercase tracking-wider">
        {title}
      </span>
      <button
        onClick={onClose}
        className="text-[#555555] hover:text-white transition-colors p-1 rounded"
        aria-label={`Close ${title}`}
      >
        <X size={14} />
      </button>
    </div>
  )
}

export function ChatLayout() {
  const [state, setState] = useState<AppState>(INITIAL_STATE)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [contextEditFile, setContextEditFile] = useState<ContextFile | null>(null)
  const [contextContents, setContextContents] = useState<Record<string, string>>({})

  const activeConversation = state.conversations.find((c) => c.id === state.activeConversationId)

  const sidebarResize = useDragResize(220, 160, 340, 'right-edge')
  const rightPanelResize = useDragResize(300, 260, 520, 'left-edge')

  useEffect(() => {
    const html = document.documentElement
    if (state.theme === 'default') {
      html.removeAttribute('data-theme')
    } else {
      html.setAttribute('data-theme', state.theme)
    }
  }, [state.theme])

  const openPanel = useCallback((id: RightPanelId) => {
    setState((s) => ({ ...s, rightPanel: s.rightPanel === id ? null : id }))
  }, [])

  const closePanel = useCallback(() => {
    setState((s) => ({ ...s, rightPanel: null }))
  }, [])

  const toggleLeft = useCallback(() => {
    setState((s) => ({ ...s, leftSidebarOpen: !s.leftSidebarOpen }))
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setState((s) => ({ ...s, activeConversationId: id, leftSidebarOpen: false }))
  }, [])

  const handleNewConversation = useCallback(() => {
    const id = generateId()
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
  }, [])

  const handleSend = useCallback((content: string) => {
    const newMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      toolCallsBefore: [],
    }
    setState((s) => ({
      ...s,
      conversations: s.conversations.map((c) =>
        c.id === s.activeConversationId
          ? { ...c, messages: [...c.messages, newMsg] }
          : c
      ),
    }))
  }, [])

  const handleToggleTool = useCallback((toolId: string) => {
    setState((s) => ({
      ...s,
      tools: s.tools.map((t) => (t.id === toolId ? { ...t, enabled: !t.enabled } : t)),
    }))
  }, [])

  const handleDismissFile = useCallback((fileId: string) => {
    setState((s) => ({ ...s, contextFiles: s.contextFiles.filter((f) => f.id !== fileId) }))
  }, [])

  const handleClickFile = useCallback((file: ContextFile) => {
    setContextEditFile(file)
    if (!contextContents[file.id]) {
      setContextContents((prev) => ({
        ...prev,
        [file.id]: `# ${file.name}\n\n_Loaded as context. Edit and save to update._\n\nPath: \`${file.path}\`\n`,
      }))
    }
  }, [contextContents])

  const handleSaveContextFile = useCallback((fileId: string, content: string) => {
    setContextContents((prev) => ({ ...prev, [fileId]: content }))
    setContextEditFile(null)
  }, [])

  const startEditTitle = useCallback(() => {
    setTitleDraft(activeConversation?.title ?? '')
    setEditingTitle(true)
  }, [activeConversation])

  const commitTitle = useCallback(() => {
    const trimmed = titleDraft.trim()
    if (trimmed) {
      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === s.activeConversationId ? { ...c, title: trimmed } : c
        ),
      }))
    }
    setEditingTitle(false)
  }, [titleDraft])

  const handleChangeTheme = useCallback((theme: ThemeName) => {
    setState((s) => ({ ...s, theme }))
  }, [])

  const handleRunDirectAction = useCallback((actionId: string) => {
    setState((s) => ({
      ...s,
      directActions: s.directActions.map((a) =>
        a.id === actionId ? { ...a, status: 'running' } : a
      ),
    }))
    setTimeout(() => {
      setState((s) => ({
        ...s,
        directActions: s.directActions.map((a) =>
          a.id === actionId
            ? { ...a, status: 'done', result: `Completed at ${new Date().toLocaleTimeString()}` }
            : a
        ),
      }))
    }, 1500)
  }, [])

  const handleWorkerAction = useCallback(
    (workerId: string, action: 'capture' | 'summarize' | 'stop' | 'kill') => {
      setState((s) => ({
        ...s,
        workers: s.workers.map((w) => {
          if (w.id !== workerId) return w
          if (action === 'stop' || action === 'kill') return { ...w, status: 'stopped' as const }
          if (action === 'capture') return { ...w, status: 'capturing' as const }
          return w
        }),
      }))
    }, []
  )

  const handleStartWorker = useCallback((type: Worker['type']) => {
    const newWorker: Worker = {
      id: generateId(),
      name: `${type} session`,
      type,
      host: 'local',
      status: 'running',
      startedAt: 'Just now',
      lastActivity: 'Just now',
    }
    setState((s) => ({ ...s, workers: [newWorker, ...s.workers] }))
  }, [])

  const degradedCount = state.healthEntries.filter(
    (e) => e.status !== 'ok' && e.status !== 'unknown'
  ).length

  const workerRunningCount = state.workers.filter((w) => w.status === 'running').length

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-black">
      {state.leftSidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 lg:hidden"
          onClick={toggleLeft}
          aria-hidden="true"
        />
      )}

      <div
        className="relative flex-shrink-0 hidden lg:flex h-full"
        style={{ width: sidebarResize.width }}
      >
        <Sidebar
          conversations={state.conversations}
          activeId={state.activeConversationId}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onClose={toggleLeft}
        />
        <DragHandle onMouseDown={sidebarResize.onMouseDown} side="right" />
      </div>

      <div
        className={cn(
          'fixed lg:hidden z-30 top-0 left-0 h-full w-64 transition-transform duration-200',
          state.leftSidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <Sidebar
          conversations={state.conversations}
          activeId={state.activeConversationId}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onClose={toggleLeft}
        />
      </div>

      <main className="flex flex-col flex-1 min-w-0 h-full">
        <header className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.05] bg-[#000000] flex-shrink-0">
          <button
            onClick={toggleLeft}
            className="lg:hidden text-[#555555] hover:text-white transition-colors p-1.5 rounded"
            aria-label="Toggle sidebar"
          >
            <Menu size={16} />
          </button>

          <div className="flex-1 min-w-0 flex items-center gap-2">
            {editingTitle ? (
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={commitTitle}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitTitle()
                  if (e.key === 'Escape') setEditingTitle(false)
                }}
                className="bg-transparent border-b text-white text-sm font-sans outline-none px-0 py-0.5 max-w-[280px]"
                style={{ borderColor: 'var(--accent-blue)' }}
              />
            ) : (
              <button
                onClick={startEditTitle}
                className="flex items-center gap-1.5 text-sm font-sans text-white truncate hover:opacity-80 transition-opacity group"
                aria-label="Edit conversation title"
              >
                <span className="truncate">{activeConversation?.title ?? 'Untitled'}</span>
                <Pencil size={11} className="text-[#555555] opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
              </button>
            )}
            <ModelBadge model={state.model} />
            <RunStatusPill status={activeConversation?.runStatus} />
          </div>

          <div className="flex items-center gap-0.5">
            <button
              onClick={() => openPanel('health')}
              className={cn('relative text-[#555555] hover:text-white transition-colors p-1.5 rounded')}
              style={state.rightPanel === 'health' ? { color: 'var(--accent-green)' } : {}}
              aria-label="Health panel"
              aria-pressed={state.rightPanel === 'health'}
              title="Health"
            >
              <Activity size={14} />
              {degradedCount > 0 && (
                <span
                  className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: 'var(--accent-pink)' }}
                />
              )}
            </button>

            <button
              onClick={() => openPanel('workers')}
              className={cn('relative text-[#555555] hover:text-white transition-colors p-1.5 rounded')}
              style={state.rightPanel === 'workers' ? { color: 'var(--accent-blue)' } : {}}
              aria-label="Workers panel"
              aria-pressed={state.rightPanel === 'workers'}
              title="Workers"
            >
              <Cpu size={14} />
              {workerRunningCount > 0 && (
                <span
                  className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full dot-pulse"
                  style={{ backgroundColor: 'var(--accent-green)' }}
                />
              )}
            </button>

            <button
              onClick={() => openPanel('settings')}
              className={cn('text-[#555555] hover:text-white transition-colors p-1.5 rounded')}
              style={state.rightPanel === 'settings' ? { color: 'var(--accent-blue)' } : {}}
              aria-label="Settings panel"
              aria-pressed={state.rightPanel === 'settings'}
              title="Settings"
            >
              <Settings size={14} />
            </button>
          </div>
        </header>

        <ContextBanner
          mode={state.contextMode}
          files={state.contextFiles}
          onDismissFile={handleDismissFile}
          onClickFile={handleClickFile}
        />

        <ChatPane messages={activeConversation?.messages ?? []} />

        <InputBar
          onSend={handleSend}
          blankSlate={state.blankSlate}
          incognito={state.incognito}
          sensitive={state.sensitive}
          directActions={state.directActions}
          onToggleBlankSlate={() => setState((s) => ({ ...s, blankSlate: !s.blankSlate }))}
          onToggleIncognito={() => setState((s) => ({ ...s, incognito: !s.incognito }))}
          onToggleSensitive={() => setState((s) => ({ ...s, sensitive: !s.sensitive }))}
          onRunDirectAction={handleRunDirectAction}
          conversationId={state.activeConversationId}
        />
      </main>

      {state.rightPanel === 'health' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <PanelHeader title="Health" onClose={closePanel} />
            <div className="flex-1 overflow-y-auto">
              <HealthPanel entries={state.healthEntries} />
            </div>
          </aside>
        </>
      )}

      {state.rightPanel === 'workers' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <PanelHeader title="Workers" onClose={closePanel} />
            <div className="flex-1 overflow-y-auto">
              <WorkersPanel
                workers={state.workers}
                onAction={handleWorkerAction}
                onStartWorker={handleStartWorker}
              />
            </div>
          </aside>
        </>
      )}

      {state.rightPanel === 'settings' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <SettingsPanel
              model={state.model}
              defaultModel={state.defaultModel}
              budgetUsed={state.budgetUsed}
              budgetTotal={state.budgetTotal}
              contextMode={state.contextMode}
              contextFiles={state.contextFiles}
              tools={state.tools}
              workers={state.workers}
              theme={state.theme}
              titleGeneration={state.titleGeneration}
              systemContext={state.systemContext}
              shortTermContinuity={state.shortTermContinuity}
              activeTab={state.settingsTab}
              onClose={closePanel}
              onToggleTool={handleToggleTool}
              onChangeModel={(m) => setState((s) => ({ ...s, model: m }))}
              onChangeDefaultModel={(m) => setState((s) => ({ ...s, defaultModel: m }))}
              onChangeTheme={handleChangeTheme}
              onToggleTitleGeneration={() => setState((s) => ({ ...s, titleGeneration: !s.titleGeneration }))}
              onChangeSystemContext={(v) => setState((s) => ({ ...s, systemContext: v }))}
              onChangeShortTermContinuity={(v) => setState((s) => ({ ...s, shortTermContinuity: v }))}
              onSetTab={(tab) => setState((s) => ({ ...s, settingsTab: tab }))}
            />
          </aside>
        </>
      )}

      {contextEditFile && (
        <ContextEditor
          file={contextEditFile}
          initialContent={contextContents[contextEditFile.id] ?? ''}
          onSave={handleSaveContextFile}
          onClose={() => setContextEditFile(null)}
        />
      )}
    </div>
  )
}
