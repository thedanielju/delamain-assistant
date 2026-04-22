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
import { BackendStatusBanner } from './BackendStatusBanner'
import { SensitiveLockBadge } from './SensitiveLockBadge'
import { AuditTrail } from './AuditTrail'
import { useDelamainBackend } from '@/hooks/useDelamainBackend'
import type { RightPanelId, ContextFile } from '@/lib/types'

// ── Drag-resize hook ──────────────────────────────────────────────────────────

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
  const {
    state,
    editingTitle,
    titleDraft,
    setTitleDraft,
    setEditingTitle,
    startEditTitle,
    commitTitle,
    setState,
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
  } = useDelamainBackend()

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

  const toggleSensitive = useCallback(() => {
    if (state.sensitiveUnlocked) handleLockSensitive()
    else handleUnlockSensitive()
  }, [state.sensitiveUnlocked, handleLockSensitive, handleUnlockSensitive])

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
            <SensitiveLockBadge unlocked={state.sensitiveUnlocked} onToggle={toggleSensitive} />
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

        <BackendStatusBanner connection={state.connection} />

        <ContextBanner
          mode={state.contextMode}
          files={state.contextFiles}
          onDismissFile={handleDismissFile}
          onClickFile={handleClickFile}
        />

        <ChatPane messages={activeConversation?.messages ?? []} />

        <AuditTrail entries={state.audit} conversationId={state.activeConversationId} />

        <InputBar
          onSend={handleSend}
          blankSlate={state.blankSlate}
          incognito={state.incognito}
          sensitive={state.sensitiveUnlocked}
          directActions={state.directActions}
          onToggleBlankSlate={() => setState((s) => ({ ...s, blankSlate: !s.blankSlate }))}
          onToggleIncognito={() => setState((s) => ({ ...s, incognito: !s.incognito }))}
          onToggleSensitive={toggleSensitive}
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
