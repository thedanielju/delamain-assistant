'use client'

import { useCallback, useState } from 'react'
import {
  RefreshCw,
  ChevronDown,
  ChevronRight,
  FolderSync,
  AlertTriangle,
  CheckCircle,
  Archive,
  Trash2,
  Copy,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { ConfirmModal } from './ConfirmModal'
import type {
  SyncthingConflict,
  SyncthingDevice,
  SyncthingFolderStatus,
  SyncthingConnection,
} from '@/lib/types'

type ResolveAction = 'keep_canonical' | 'keep_conflict' | 'keep_both' | 'stage_review'

const STATUS_DOT: Record<SyncthingDevice['status'], string> = {
  ok: 'bg-[var(--accent-green)]',
  degraded: 'bg-[var(--accent-blue)]',
  unavailable: 'bg-[var(--accent-pink)]',
  unknown: 'bg-[#444444]',
}

const STATUS_TEXT: Record<SyncthingDevice['status'], string> = {
  ok: 'text-[var(--accent-green)]',
  degraded: 'text-[var(--accent-blue)]',
  unavailable: 'text-[var(--accent-pink)]',
  unknown: 'text-[#555555]',
}

function shortId(id: string): string {
  if (!id) return '—'
  const head = id.split('-')[0] ?? id
  return head.length > 7 ? head.slice(0, 7) : head
}

function FolderRow({ folder }: { folder: SyncthingFolderStatus }) {
  const hasError = (folder.errors ?? 0) > 0 || (folder.pullErrors ?? 0) > 0
  const hasNeed = (folder.needItems ?? 0) > 0
  return (
    <li className="flex items-start gap-2 px-2.5 py-1.5 rounded-md bg-[#0a0a0a] border border-white/[0.04]">
      <FolderSync size={11} className="text-[#555555] flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-mono text-[#cccccc] truncate">{folder.folderId}</span>
          <span
            className={cn(
              'text-[9px] font-mono flex-shrink-0',
              hasError
                ? 'text-[var(--accent-pink)]'
                : hasNeed
                  ? 'text-[var(--accent-blue)]'
                  : 'text-[var(--accent-green)]'
            )}
          >
            {folder.state ?? 'unknown'}
          </span>
        </div>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-[9px] font-mono text-[#555555]">
            need {folder.needItems ?? 0}
          </span>
          <span className="text-[9px] font-mono text-[#555555]">
            errors {(folder.errors ?? 0) + (folder.pullErrors ?? 0)}
          </span>
          {folder.globalItems != null && (
            <span className="text-[9px] font-mono text-[#3a3a3a]">
              {folder.localItems ?? 0}/{folder.globalItems}
            </span>
          )}
        </div>
      </div>
    </li>
  )
}

function ConnectionRow({ conn }: { conn: SyncthingConnection }) {
  return (
    <li className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-[#0a0a0a] border border-white/[0.04]">
      <span
        className={cn(
          'w-1.5 h-1.5 rounded-full flex-shrink-0',
          conn.connected ? 'bg-[var(--accent-green)]' : 'bg-[#444444]',
          conn.paused && 'bg-[var(--accent-blue)]'
        )}
      />
      <div className="flex-1 min-w-0 grid grid-cols-2 gap-x-2">
        <span className="text-[10px] font-mono text-[#cccccc] truncate">{shortId(conn.deviceId)}</span>
        <span className="text-[10px] font-mono text-[#555555] truncate text-right">
          {conn.address ?? '—'}
        </span>
        <span className="text-[9px] font-mono text-[#3a3a3a] truncate">
          {conn.version ?? '—'}
        </span>
        <span className="text-[9px] font-mono text-[#3a3a3a] truncate text-right">
          {conn.at ?? ''}
        </span>
      </div>
    </li>
  )
}

function DeviceCard({ device }: { device: SyncthingDevice }) {
  const [expanded, setExpanded] = useState(true)
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/[0.02] transition-colors text-left"
      >
        <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', STATUS_DOT[device.status])} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono text-[#cccccc] truncate">{device.host}</p>
          <p className="text-[9px] font-mono text-[#444444]">
            <span className={STATUS_TEXT[device.status]}>{device.status}</span>
            {device.conflictCount != null && ` · conflicts ${device.conflictCount}`}
            {device.junkCount != null && ` · junk ${device.junkCount}`}
            {device.timestamp && ` · ${device.timestamp}`}
          </p>
        </div>
        {expanded ? (
          <ChevronDown size={10} className="text-[#444444] flex-shrink-0" />
        ) : (
          <ChevronRight size={10} className="text-[#444444] flex-shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-white/[0.05] px-3 py-2.5 flex flex-col gap-2.5">
          {!device.available && (
            <p className="text-[10px] font-mono text-[var(--accent-pink)]">
              Device unavailable
            </p>
          )}

          {device.folders.length > 0 && (
            <div>
              <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider mb-1">
                Folders
              </p>
              <ul className="flex flex-col gap-1">
                {device.folders.map((f) => (
                  <FolderRow key={f.folderId} folder={f} />
                ))}
              </ul>
            </div>
          )}

          {device.connections.length > 0 && (
            <div>
              <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider mb-1">
                Connections
              </p>
              <ul className="flex flex-col gap-1">
                {device.connections.map((c) => (
                  <ConnectionRow key={c.deviceId} conn={c} />
                ))}
              </ul>
            </div>
          )}

          {device.folders.length === 0 && device.connections.length === 0 && (
            <p className="text-[10px] font-mono text-[#3a3a3a] text-center py-2">
              No folders or connections reported
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Conflict actions ─────────────────────────────────────────────────────────

const ACTION_META: Record<ResolveAction, {
  label: string
  icon: React.ReactNode
  destructive: boolean
  accent: 'pink' | 'blue' | 'green'
  description: string
}> = {
  keep_canonical: {
    label: 'Keep canonical',
    icon: <CheckCircle size={10} />,
    destructive: true,
    accent: 'pink',
    description: 'Delete the conflict copy and keep the canonical file. This cannot be undone.',
  },
  keep_conflict: {
    label: 'Keep conflict',
    icon: <Copy size={10} />,
    destructive: true,
    accent: 'pink',
    description: 'Overwrite the canonical file with the conflict copy. This cannot be undone.',
  },
  keep_both: {
    label: 'Keep both',
    icon: <Archive size={10} />,
    destructive: false,
    accent: 'blue',
    description: 'Retain both files.',
  },
  stage_review: {
    label: 'Stage review',
    icon: <Trash2 size={10} />,
    destructive: false,
    accent: 'green',
    description: 'Move both files to the review directory.',
  },
}

interface ConflictCardProps {
  conflict: SyncthingConflict
  onRequestAction: (action: ResolveAction) => void
}

function ConflictCard({ conflict, onRequestAction }: ConflictCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-2.5 px-3 py-2.5 hover:bg-white/[0.02] transition-colors text-left"
      >
        <AlertTriangle
          size={12}
          style={{ color: 'var(--accent-pink)' }}
          className="flex-shrink-0 mt-0.5"
        />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono text-[#cccccc] truncate">{conflict.path}</p>
          <p className="text-[9px] font-mono text-[#444444] truncate">
            {conflict.folderId ?? 'unknown folder'}
            {conflict.reason && ` · ${conflict.reason}`}
          </p>
        </div>
        {expanded ? (
          <ChevronDown size={10} className="text-[#444444] flex-shrink-0 mt-0.5" />
        ) : (
          <ChevronRight size={10} className="text-[#444444] flex-shrink-0 mt-0.5" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-white/[0.05] px-3 py-2.5 flex flex-col gap-2">
          {conflict.canonicalPath && (
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider">
                Canonical
              </span>
              <span className="text-[10px] font-mono text-[#888888] break-all">
                {conflict.canonicalPath}
              </span>
            </div>
          )}

          {conflict.reviewDir && (
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider">
                Review dir
              </span>
              <span className="text-[10px] font-mono text-[#888888] break-all">
                {conflict.reviewDir}
              </span>
            </div>
          )}

          {conflict.devices.length > 0 && (
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider">
                Devices
              </span>
              <div className="flex flex-wrap gap-1">
                {conflict.devices.map((d) => (
                  <span
                    key={d}
                    className="text-[9px] font-mono text-[#888888] px-1.5 py-0.5 rounded bg-[#0a0a0a] border border-white/[0.05]"
                  >
                    {shortId(d)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {Object.keys(conflict.mtimes).length > 0 && (
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider">
                mtimes
              </span>
              <ul className="flex flex-col gap-0.5">
                {Object.entries(conflict.mtimes).map(([k, v]) => (
                  <li key={k} className="text-[9px] font-mono text-[#666666] flex gap-2">
                    <span className="text-[#888888]">{shortId(k)}</span>
                    <span>{v}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center gap-1.5 flex-wrap pt-1">
            {(Object.keys(ACTION_META) as ResolveAction[]).map((action) => {
              const meta = ACTION_META[action]
              return (
                <button
                  key={action}
                  onClick={() => onRequestAction(action)}
                  className={cn(
                    'inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[10px] font-mono transition-all',
                    meta.accent === 'pink' &&
                      'border-[var(--accent-pink)]/30 text-[var(--accent-pink)] hover:bg-[var(--accent-pink)]/10',
                    meta.accent === 'blue' &&
                      'border-[var(--accent-blue)]/30 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10',
                    meta.accent === 'green' &&
                      'border-[var(--accent-green)]/30 text-[var(--accent-green)] hover:bg-[var(--accent-green)]/10'
                  )}
                >
                  {meta.icon}
                  {meta.label}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Toast ────────────────────────────────────────────────────────────────────

interface PanelToast {
  id: number
  message: string
  tone: 'info' | 'success'
}

function ToastStack({ toasts }: { toasts: PanelToast[] }) {
  if (toasts.length === 0) return null
  return (
    <div className="pointer-events-none absolute top-3 right-3 z-40 flex flex-col gap-1.5">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            'pointer-events-auto rounded-lg border px-3 py-2 text-[10px] font-mono shadow-xl backdrop-blur',
            t.tone === 'success'
              ? 'bg-[var(--accent-green)]/10 border-[var(--accent-green)]/30 text-[var(--accent-green)]'
              : 'bg-[var(--accent-blue)]/10 border-[var(--accent-blue)]/30 text-[var(--accent-blue)]'
          )}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

interface SyncthingPanelProps {
  devices: SyncthingDevice[]
  conflicts: SyncthingConflict[]
  onRefresh: () => void | Promise<void>
  onResolveConflict: (
    path: string,
    action: ResolveAction,
    note?: string
  ) => void | Promise<void>
}

interface PendingConfirm {
  path: string
  action: ResolveAction
}

export function SyncthingPanel({
  devices,
  conflicts,
  onRefresh,
  onResolveConflict,
}: SyncthingPanelProps) {
  const [refreshing, setRefreshing] = useState(false)
  const [pending, setPending] = useState<PendingConfirm | null>(null)
  const [toasts, setToasts] = useState<PanelToast[]>([])

  const pushToast = useCallback((message: string, tone: PanelToast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((prev) => [...prev, { id, message, tone }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 2800)
  }, [])

  const handleRefresh = useCallback(() => {
    setRefreshing(true)
    Promise.resolve(onRefresh()).finally(() => {
      setTimeout(() => setRefreshing(false), 600)
    })
  }, [onRefresh])

  const handleRequestAction = useCallback(
    (path: string, action: ResolveAction) => {
      const meta = ACTION_META[action]
      if (meta.destructive) {
        setPending({ path, action })
      } else {
        onResolveConflict(path, action)
        pushToast(`${meta.label}: queued`, 'success')
      }
    },
    [onResolveConflict, pushToast]
  )

  const handleConfirm = useCallback(() => {
    if (!pending) return
    const { path, action } = pending
    const meta = ACTION_META[action]
    onResolveConflict(path, action)
    pushToast(`${meta.label}: submitted`, 'success')
    setPending(null)
  }, [pending, onResolveConflict, pushToast])

  return (
    <div className="relative flex flex-col gap-3 p-4">
      <ToastStack toasts={toasts} />

      {/* Header / refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-mono text-[#555555]">
            {devices.length} device{devices.length === 1 ? '' : 's'}
          </span>
          {conflicts.length > 0 && (
            <span className="text-[10px] font-mono text-[var(--accent-pink)]">
              {conflicts.length} conflict{conflicts.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          className="text-[#555555] hover:text-[var(--accent-blue)] transition-colors p-1 rounded"
          aria-label="Refresh syncthing"
        >
          <RefreshCw
            size={12}
            className={cn('transition-transform', refreshing && 'animate-spin')}
          />
        </button>
      </div>

      {/* Devices */}
      <div className="flex flex-col gap-2">
        <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider">
          Devices
        </p>
        {devices.length === 0 ? (
          <p className="text-xs font-mono text-[#3a3a3a] text-center py-3">
            No syncthing devices reported
          </p>
        ) : (
          devices.map((d) => <DeviceCard key={d.host} device={d} />)
        )}
      </div>

      {/* Conflicts */}
      <div className="flex flex-col gap-2 mt-1">
        <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider">
          Conflicts
        </p>
        {conflicts.length === 0 ? (
          <p className="text-xs font-mono text-[#3a3a3a] text-center py-3">
            No pending conflicts
          </p>
        ) : (
          conflicts.map((c) => (
            <ConflictCard
              key={c.path}
              conflict={c}
              onRequestAction={(action) => handleRequestAction(c.path, action)}
            />
          ))
        )}
      </div>

      {pending && (
        <ConfirmModal
          title={ACTION_META[pending.action].label}
          description={`${ACTION_META[pending.action].description}\n\nPath: ${pending.path}`}
          confirmLabel={ACTION_META[pending.action].label}
          onConfirm={handleConfirm}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  )
}
