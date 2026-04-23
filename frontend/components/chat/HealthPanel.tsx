'use client'

import { useState } from 'react'
import { RefreshCw, CheckCircle, AlertTriangle, XCircle, HelpCircle, FolderSync, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { HealthEntry, HealthStatus, SyncthingDevice } from '@/lib/types'

const STATUS_ICON: Record<HealthStatus, React.ReactNode> = {
  ok: <CheckCircle size={12} className="text-[var(--accent-green)]" />,
  degraded: <AlertTriangle size={12} className="text-[var(--accent-blue)]" style={{ color: 'var(--accent-pink)' }} />,
  error: <XCircle size={12} className="text-[var(--accent-pink)]" />,
  unknown: <HelpCircle size={12} className="text-[#555555]" />,
}

const STATUS_DOT: Record<HealthStatus, string> = {
  ok: 'bg-[var(--accent-green)]',
  degraded: 'bg-[var(--accent-blue)]',
  error: 'bg-[var(--accent-pink)]',
  unknown: 'bg-[#444444]',
}

const SYNCTHING_HOSTS: Array<SyncthingDevice['host']> = ['local', 'serrano', 'winpc', 'iphone']

const SYNC_STATUS_DOT: Record<SyncthingDevice['status'], string> = {
  ok: 'bg-[var(--accent-green)]',
  degraded: 'bg-[var(--accent-blue)]',
  unavailable: 'bg-[var(--accent-pink)]',
  unknown: 'bg-[#444444]',
}

function SyncthingSummaryCard({
  devices,
  conflictCount,
  onOpen,
}: {
  devices: SyncthingDevice[]
  conflictCount: number
  onOpen: () => void
}) {
  const byHost = new Map(devices.map((d) => [d.host, d]))

  return (
    <button
      onClick={onOpen}
      className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-white/[0.07] bg-[#0d0d0d] hover:bg-white/[0.02] hover:border-white/[0.12] transition-all text-left"
      aria-label="Open Syncthing panel"
    >
      <FolderSync size={12} className="text-[#555555] flex-shrink-0" />
      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
        <div className="flex items-center gap-3">
          {SYNCTHING_HOSTS.map((host) => {
            const dev = byHost.get(host)
            const isStub = host === 'iphone' && !dev
            const status: SyncthingDevice['status'] = dev?.status ?? 'unknown'
            return (
              <span key={host} className="flex items-center gap-1">
                <span
                  className={cn(
                    'w-1.5 h-1.5 rounded-full inline-block',
                    SYNC_STATUS_DOT[status],
                    isStub && 'bg-[#2a2a2a]'
                  )}
                />
                <span
                  className={cn(
                    'text-[10px] font-mono',
                    isStub ? 'text-[#3a3a3a]' : 'text-[#888888]'
                  )}
                >
                  {host}
                </span>
              </span>
            )
          })}
        </div>
        <p className="text-[9px] font-mono text-[#3a3a3a]">
          {!byHost.has('iphone') && 'Awaiting iOS backend wiring'}
          {!byHost.has('iphone') && conflictCount > 0 && ' · '}
          {conflictCount > 0 && (
            <span className="text-[var(--accent-pink)]">
              {conflictCount} conflict{conflictCount === 1 ? '' : 's'}
            </span>
          )}
        </p>
      </div>
      <ChevronRight size={11} className="text-[#444444] flex-shrink-0" />
    </button>
  )
}

interface HealthPanelProps {
  entries: HealthEntry[]
  syncthingDevices: SyncthingDevice[]
  syncthingConflictCount: number
  onRefresh?: () => void
  onOpenSyncthing: () => void
}

export function HealthPanel({
  entries,
  syncthingDevices,
  syncthingConflictCount,
  onRefresh,
  onOpenSyncthing,
}: HealthPanelProps) {
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = () => {
    setRefreshing(true)
    onRefresh?.()
    setTimeout(() => setRefreshing(false), 1200)
  }

  const countByStatus = {
    ok: entries.filter((e) => e.status === 'ok').length,
    degraded: entries.filter((e) => e.status === 'degraded').length,
    error: entries.filter((e) => e.status === 'error').length,
    unknown: entries.filter((e) => e.status === 'unknown').length,
  }

  return (
    <div className="flex flex-col gap-4 py-2 px-4">
      {/* Syncthing summary card */}
      <SyncthingSummaryCard
        devices={syncthingDevices}
        conflictCount={syncthingConflictCount}
        onOpen={onOpenSyncthing}
      />

      {/* Summary row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {countByStatus.ok > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-[var(--accent-green)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)] inline-block" />
              {countByStatus.ok} ok
            </span>
          )}
          {countByStatus.degraded > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono" style={{ color: 'var(--accent-pink)' }}>
              <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: 'var(--accent-pink)' }} />
              {countByStatus.degraded} degraded
            </span>
          )}
          {countByStatus.error > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-[var(--accent-pink)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-pink)] inline-block" />
              {countByStatus.error} error
            </span>
          )}
          {countByStatus.unknown > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-mono text-[#555555]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#444444] inline-block" />
              {countByStatus.unknown} unknown
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          className="text-[#555555] hover:text-[var(--accent-blue)] transition-colors p-1 rounded"
          aria-label="Refresh health status"
        >
          <RefreshCw size={12} className={cn('transition-transform', refreshing && 'animate-spin')} />
        </button>
      </div>

      {/* Entry list */}
      <ul className="flex flex-col gap-1">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="flex items-start gap-2.5 py-2 px-2.5 rounded-lg bg-[#0d0d0d] border border-white/[0.05]"
          >
            <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1', STATUS_DOT[entry.status])} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-mono text-[#cccccc] truncate">{entry.label}</span>
                <span className={cn(
                  'text-[10px] font-mono flex-shrink-0',
                  entry.status === 'ok' && 'text-[var(--accent-green)]',
                  entry.status === 'degraded' && 'text-[var(--accent-pink)]',
                  entry.status === 'error' && 'text-[var(--accent-pink)]',
                  entry.status === 'unknown' && 'text-[#555555]',
                )}>
                  {entry.status}
                </span>
              </div>
              {entry.detail && (
                <p className="text-[10px] font-sans text-[#555555] mt-0.5 leading-tight">{entry.detail}</p>
              )}
              {entry.lastChecked && (
                <p className="text-[9px] font-mono text-[#3a3a3a] mt-0.5">checked {entry.lastChecked}</p>
              )}
            </div>
          </li>
        ))}
      </ul>

      {/* Future endpoint list */}
      <div className="mt-1 pt-3 border-t border-white/[0.04]">
        <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider mb-1.5">Anticipated endpoints</p>
        <ul className="flex flex-col gap-1">
          {[
            'GET /api/health',
            'GET /api/health/syncthing',
            'GET /api/health/hosts',
            'GET /api/health/copilot-budget',
            'GET /api/health/models',
          ].map((ep) => (
            <li key={ep} className="text-[10px] font-mono text-[#3a3a3a]">{ep}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}
