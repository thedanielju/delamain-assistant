'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { Menu, Settings, Activity, Cpu, Pencil, X, DollarSign, Network, UploadCloud } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Sidebar } from './Sidebar'
import { ChatPane } from './ChatPane'
import { ContextBanner } from './ContextBanner'
import { InputBar } from './InputBar'
import { SettingsPanel } from './SettingsPanel'
import { HealthPanel } from './HealthPanel'
import { WorkersPanel } from './WorkersPanel'
import { UsagePanel } from './UsagePanel'
import { SyncthingPanel } from './SyncthingPanel'
import { ContextEditor } from './ContextEditor'
import { ModelBadge } from './ModelBadge'
import { RunStatusPill } from './RunStatusPill'
import { RunControls } from './RunControls'
import { PermissionModal } from './PermissionModal'
import { BackendStatusBanner } from './BackendStatusBanner'
import { SensitiveLockBadge } from './SensitiveLockBadge'
import { AuditTrail } from './AuditTrail'
import { VaultPanel } from './VaultPanel'
import { ComposerContextTray } from './ComposerContextTray'
import { UploadsPanel } from './UploadsPanel'
import { useDelamainBackend } from '@/hooks/useDelamainBackend'
import { api } from '@/lib/api'
import type { ContextFile } from '@/lib/types'

type ContextFileId = 'system-context' | 'short-term-continuity' | null

function detectContextFileId(file: ContextFile): ContextFileId {
  const path = file.path.toLowerCase()
  if (path.includes('system-context')) return 'system-context'
  if (path.includes('short-term-continuity') || path.includes('short_term_continuity')) return 'short-term-continuity'
  return null
}

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
    handleRefreshUsage,
    handleRefreshSyncthing,
    handleResolveSyncthingConflict,
    handleChangeModel,
    handleChangeDefaultModel,
    handleChangeTaskModel,
    handleSetContextMode,
    handleToggleTitleGeneration,
    handleToggleCopilotHardOverride,
    handleChangeSystemContext,
    handleChangeShortTermContinuity,
    handleCreateFolder,
    handleRenameFolder,
    handleMoveFolder,
    handleDeleteFolder,
    handleMoveConversation,
    handleDeleteConversation,
    handleResolvePermission,
    handleRetryRun,
    handleCancelRun,
    handleSummarizeWorker,
    handleRenameWorker,
    retryConnection,
  } = useDelamainBackend()

  const handleRenameConversation = useCallback(
    (conversationId: string, title: string) => {
      setState((s) => ({
        ...s,
        conversations: s.conversations.map((c) =>
          c.id === conversationId ? { ...c, title } : c
        ),
      }))
      api.patchConversation(conversationId, { title }).catch(() => {
        /* ignore */
      })
    },
    [setState]
  )

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

  // Load system-context + short-term-continuity once the backend is connected
  const loadedCtxRef = useRef(false)
  useEffect(() => {
    if (state.connection !== 'connected') return
    if (loadedCtxRef.current) return
    loadedCtxRef.current = true
    let cancelled = false
    Promise.all([
      api.getContextFile('system-context').catch(() => null),
      api.getContextFile('short-term-continuity').catch(() => null),
    ]).then(([sys, cont]) => {
      if (cancelled) return
      if (sys) patchState('systemContext', sys.content)
      if (cont) patchState('shortTermContinuity', cont.content)
    })
    return () => {
      cancelled = true
    }
  }, [state.connection, patchState])

  const handleClickFile = useCallback((file: ContextFile) => {
    setContextEditFile(file)
    const detected = detectContextFileId(file)
    if (detected === 'system-context') {
      setContextContents((prev) => ({ ...prev, [file.id]: state.systemContext }))
      return
    }
    if (detected === 'short-term-continuity') {
      setContextContents((prev) => ({ ...prev, [file.id]: state.shortTermContinuity }))
      return
    }
    if (!contextContents[file.id]) {
      setContextContents((prev) => ({
        ...prev,
        [file.id]: `# ${file.name}\n\n_Backend editing is only available for system-context and short-term-continuity._\n\nPath: \`${file.path}\`\n`,
      }))
    }
  }, [contextContents, state.systemContext, state.shortTermContinuity])

  const handleSaveContextFile = useCallback(
    (fileId: string, content: string) => {
      setContextContents((prev) => ({ ...prev, [fileId]: content }))
      const file = contextEditFile
      if (file) {
        const detected = detectContextFileId(file)
        if (detected === 'system-context') {
          handleChangeSystemContext(content)
        } else if (detected === 'short-term-continuity') {
          handleChangeShortTermContinuity(content)
        }
      }
      setContextEditFile(null)
    },
    [contextEditFile, handleChangeSystemContext, handleChangeShortTermContinuity],
  )

  const toggleSensitive = useCallback(() => {
    if (state.sensitiveUnlocked) handleLockSensitive()
    else handleUnlockSensitive()
  }, [state.sensitiveUnlocked, handleLockSensitive, handleUnlockSensitive])

  const degradedCount = state.healthEntries.filter(
    (e) => e.status !== 'ok' && e.status !== 'unknown'
  ).length

  const workerRunningCount = state.workers.filter((w) => w.status === 'running').length

  const usageAlertCount =
    state.usageProviders.filter((p) => p.wired && (p.percent ?? 0) >= 90).length +
    state.subscriptions.filter((s) => s.aggregateStatus !== 'ok').length

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
          folders={state.folders}
          activeId={state.activeConversationId}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onClose={toggleLeft}
          onCreateFolder={handleCreateFolder}
          onRenameFolder={handleRenameFolder}
          onMoveFolder={handleMoveFolder}
          onDeleteFolder={handleDeleteFolder}
          onMoveConversation={handleMoveConversation}
          onDeleteConversation={handleDeleteConversation}
          onRenameConversation={handleRenameConversation}
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
          folders={state.folders}
          activeId={state.activeConversationId}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onClose={toggleLeft}
          onCreateFolder={handleCreateFolder}
          onRenameFolder={handleRenameFolder}
          onMoveFolder={handleMoveFolder}
          onDeleteFolder={handleDeleteFolder}
          onMoveConversation={handleMoveConversation}
          onDeleteConversation={handleDeleteConversation}
          onRenameConversation={handleRenameConversation}
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
            <ModelBadge
              model={state.model}
              options={state.modelOptions}
              onChange={handleChangeModel}
            />
            <RunStatusPill status={activeConversation?.runStatus} />
            <RunControls
              status={activeConversation?.runStatus}
              messages={activeConversation?.messages ?? []}
              onRetry={handleRetryRun}
              onCancel={handleCancelRun}
            />
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
              onClick={() => openPanel('usage')}
              className={cn('relative text-[#555555] hover:text-white transition-colors p-1.5 rounded')}
              style={state.rightPanel === 'usage' ? { color: 'var(--accent-blue)' } : {}}
              aria-label="Usage panel"
              aria-pressed={state.rightPanel === 'usage'}
              title="Usage"
            >
              <DollarSign size={14} />
              {usageAlertCount > 0 && (
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
              onClick={() => openPanel('vault')}
              className={cn('relative text-[#555555] hover:text-white transition-colors p-1.5 rounded')}
              style={state.rightPanel === 'vault' ? { color: 'var(--accent-blue)' } : {}}
              aria-label="Vault panel"
              aria-pressed={state.rightPanel === 'vault'}
              title="Vault graph"
            >
              <Network size={14} />
            </button>

            <button
              onClick={() => openPanel('uploads')}
              className={cn('relative text-[#555555] hover:text-white transition-colors p-1.5 rounded')}
              style={state.rightPanel === 'uploads' ? { color: 'var(--accent-green)' } : {}}
              aria-label="Uploads panel"
              aria-pressed={state.rightPanel === 'uploads'}
              title="Uploads"
            >
              <UploadCloud size={14} />
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

        <BackendStatusBanner
          connection={state.connection}
          authRedirectUrl={state.authRedirectUrl}
          onRetry={retryConnection}
        />

        <ContextBanner
          mode={state.contextMode}
          files={state.contextFiles}
          onDismissFile={handleDismissFile}
          onClickFile={handleClickFile}
        />

        <ChatPane messages={activeConversation?.messages ?? []} />

        <AuditTrail entries={state.audit} conversationId={state.activeConversationId} />

        <ComposerContextTray
          items={state.vaultContextItems ?? []}
          onRemove={handleRemoveVaultContext}
          onOpenVault={() => openPanel('vault')}
        />

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
          onDraftChange={handlePreviewVaultContext}
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
              <HealthPanel
                entries={state.healthEntries}
                system={state.healthSystem}
                syncthingDevices={state.syncthingDevices}
                syncthingConflictCount={state.syncthingConflicts.length}
                onRefresh={handleRefreshHealth}
                onOpenSyncthing={() => openPanel('syncthing')}
              />
            </div>
          </aside>
        </>
      )}

      {state.rightPanel === 'syncthing' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <PanelHeader title="Syncthing" onClose={closePanel} />
            <div className="flex-1 overflow-y-auto">
              <SyncthingPanel
                devices={state.syncthingDevices}
                conflicts={state.syncthingConflicts}
                directActions={state.directActions}
                onRefresh={handleRefreshSyncthing}
                onResolveConflict={handleResolveSyncthingConflict}
                onRunDirectAction={handleRunDirectAction}
              />
            </div>
          </aside>
        </>
      )}

      {state.rightPanel === 'usage' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <PanelHeader title="Usage" onClose={closePanel} />
            <div className="flex-1 overflow-y-auto">
              <UsagePanel
                usageProviders={state.usageProviders}
                subscriptions={state.subscriptions}
                onRefresh={handleRefreshUsage}
              />
            </div>
          </aside>
        </>
      )}

      {state.rightPanel === 'vault' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <PanelHeader title="Vault" onClose={closePanel} />
            <div className="flex-1 overflow-hidden">
              <VaultPanel
                conversationId={state.activeConversationId}
                pinnedItems={state.vaultContextItems ?? []}
                onPinToContext={handleAddVaultContext}
              />
            </div>
          </aside>
        </>
      )}

      {state.rightPanel === 'uploads' && (
        <>
          <div className="fixed inset-0 z-20 bg-black/60 xl:hidden" onClick={closePanel} aria-hidden="true" />
          <aside
            className="relative flex-shrink-0 flex flex-col h-full bg-[#080808] border-l border-white/[0.06] z-30"
            style={{ width: rightPanelResize.width }}
          >
            <DragHandle onMouseDown={rightPanelResize.onMouseDown} side="left" />
            <PanelHeader title="Uploads" onClose={closePanel} />
            <div className="flex-1 overflow-hidden">
              <UploadsPanel />
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
                workerTypeOptions={state.workerTypeOptions}
                onAction={handleWorkerAction}
                onSummarize={handleSummarizeWorker}
                onRename={handleRenameWorker}
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
              taskModel={state.taskModel}
              modelOptions={state.modelOptions}
              budgetUsed={state.budgetUsed}
              budgetTotal={state.budgetTotal}
              contextMode={state.contextMode}
              contextFiles={state.contextFiles}
              tools={state.tools}
              workers={state.workers}
              theme={state.theme}
              titleGeneration={state.titleGeneration}
              copilotBudgetHardOverride={state.copilotBudgetHardOverride}
              systemContext={state.systemContext}
              shortTermContinuity={state.shortTermContinuity}
              activeTab={state.settingsTab}
              onClose={closePanel}
              onToggleTool={handleToggleTool}
              onSetToolApprovalPolicy={handleSetToolApprovalPolicy}
              onChangeModel={handleChangeModel}
              onChangeDefaultModel={handleChangeDefaultModel}
              onChangeTaskModel={handleChangeTaskModel}
              onSetContextMode={handleSetContextMode}
              onChangeTheme={handleChangeTheme}
              onToggleTitleGeneration={handleToggleTitleGeneration}
              onToggleCopilotHardOverride={handleToggleCopilotHardOverride}
              onChangeSystemContext={handleChangeSystemContext}
              onChangeShortTermContinuity={handleChangeShortTermContinuity}
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
          readOnly={detectContextFileId(contextEditFile) === null}
        />
      )}

      <PermissionModal
        permissions={state.permissions}
        onResolve={handleResolvePermission}
        onRememberPolicy={handleSetToolApprovalPolicy}
      />
    </div>
  )
}
