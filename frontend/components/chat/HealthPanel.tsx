'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  RefreshCw,
  FolderSync,
  ChevronRight,
  Cpu,
  HardDrive,
  MemoryStick,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { HealthEntry, HealthStatus, SyncthingDevice } from '@/lib/types'

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
  probe_only: 'bg-[var(--accent-blue)]',
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
            const status: SyncthingDevice['status'] = dev?.status ?? 'unknown'
            return (
              <span key={host} className="flex items-center gap-1">
                <span
                  className={cn(
                    'w-1.5 h-1.5 rounded-full inline-block',
                    SYNC_STATUS_DOT[status]
                  )}
                />
                <span
                  className={cn(
                    'text-[10px] font-mono',
                    dev ? 'text-[#888888]' : 'text-[#3a3a3a]'
                  )}
                >
                  {host}
                </span>
              </span>
            )
          })}
        </div>
        <p className="text-[9px] font-mono text-[#3a3a3a]">
          {conflictCount > 0 && (
            <span className="text-[var(--accent-pink)]">
              {conflictCount} conflict{conflictCount === 1 ? '' : 's'}
            </span>
          )}
          {conflictCount === 0 && 'Syncthing status'}
        </p>
      </div>
      <ChevronRight size={11} className="text-[#444444] flex-shrink-0" />
    </button>
  )
}

function EntryRow({ entry }: { entry: HealthEntry }) {
  return (
    <li className="flex items-start gap-2.5 py-2 px-2.5 rounded-lg bg-[#0d0d0d] border border-white/[0.05]">
      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1', STATUS_DOT[entry.status])} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-mono text-[#cccccc] truncate">{entry.label}</span>
          <span
            className={cn(
              'text-[10px] font-mono flex-shrink-0',
              entry.status === 'ok' && 'text-[var(--accent-green)]',
              entry.status === 'degraded' && 'text-[var(--accent-pink)]',
              entry.status === 'error' && 'text-[var(--accent-pink)]',
              entry.status === 'unknown' && 'text-[#555555]'
            )}
          >
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
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider px-1">{children}</p>
  )
}

// Placeholder card for system metrics that the backend will expose via
// Prompt E. When the field starts appearing in /api/health we'll populate.
function SystemMetricsPlaceholder() {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-3 flex flex-col gap-2">
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-md bg-[#0a0a0a] border border-white/[0.04] px-2 py-2 flex flex-col items-center gap-1">
          <MemoryStick size={12} className="text-[#555555]" />
          <span className="text-[9px] font-mono text-[#3a3a3a] uppercase">mem</span>
          <span className="text-[10px] font-mono text-[#666666]">—</span>
        </div>
        <div className="rounded-md bg-[#0a0a0a] border border-white/[0.04] px-2 py-2 flex flex-col items-center gap-1">
          <Cpu size={12} className="text-[#555555]" />
          <span className="text-[9px] font-mono text-[#3a3a3a] uppercase">cpu</span>
          <span className="text-[10px] font-mono text-[#666666]">—</span>
        </div>
        <div className="rounded-md bg-[#0a0a0a] border border-white/[0.04] px-2 py-2 flex flex-col items-center gap-1">
          <HardDrive size={12} className="text-[#555555]" />
          <span className="text-[9px] font-mono text-[#3a3a3a] uppercase">disk</span>
          <span className="text-[10px] font-mono text-[#666666]">—</span>
        </div>
      </div>
      <p className="text-[9px] font-mono text-[#3a3a3a] leading-relaxed">
        Waiting for backend Prompt E: <code>system</code> block under <code>/api/health</code>
        (rss, cpu%, load, disk free, worker tmux RSS). Falls into the three cards above.
      </p>
    </div>
  )
}

interface HealthPanelProps {
  entries: HealthEntry[]
  syncthingDevices: SyncthingDevice[]
  syncthingConflictCount: number
  onRefresh?: () => void | Promise<void>
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
    if (!onRefresh) return
    setRefreshing(true)
    Promise.resolve(onRefresh()).finally(() => {
      setTimeout(() => setRefreshing(false), 600)
    })
  }

  useEffect(() => {
    if (!onRefresh) return
    const h = setInterval(() => onRefresh(), 30_000)
    return () => clearInterval(h)
  }, [onRefresh])

  const { serviceEntries, helperEntries, budgetEntries, otherEntries } = useMemo(() => {
    const service: HealthEntry[] = []
    const helper: HealthEntry[] = []
    const budget: HealthEntry[] = []
    const other: HealthEntry[] = []
    for (const e of entries) {
      if (e.id === 'backend' || e.id === 'sqlite' || e.id === 'litellm') service.push(e)
      else if (e.id.startsWith('helper-')) helper.push(e)
      else if (e.id === 'copilot-budget') budget.push(e)
      else other.push(e)
    }
    return { serviceEntries: service, helperEntries: helper, budgetEntries: budget, otherEntries: other }
  }, [entries])

  const countByStatus = useMemo(() => {
    return {
      ok: entries.filter((e) => e.status === 'ok').length,
      degraded: entries.filter((e) => e.status === 'degraded').length,
      error: entries.filter((e) => e.status === 'error').length,
      unknown: entries.filter((e) => e.status === 'unknown').length,
    }
  }, [entries])

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
        <div className="flex items-center gap-3 flex-wrap">
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
          title="Re-fetch /api/health"
        >
          <RefreshCw size={12} className={cn('transition-transform', refreshing && 'animate-spin')} />
        </button>
      </div>

      {/* Service */}
      {serviceEntries.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <SectionLabel>Service</SectionLabel>
          <ul className="flex flex-col gap-1">
            {serviceEntries.map((e) => (
              <EntryRow key={e.id} entry={e} />
            ))}
          </ul>
        </section>
      )}

      {/* System resources — placeholder until backend Prompt E lands */}
      <section className="flex flex-col gap-1.5">
        <SectionLabel>System resources (serrano)</SectionLabel>
        <SystemMetricsPlaceholder />
      </section>

      {/* Helpers */}
      {helperEntries.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <SectionLabel>Helpers</SectionLabel>
          <ul className="flex flex-col gap-1">
            {helperEntries.map((e) => (
              <EntryRow key={e.id} entry={e} />
            ))}
          </ul>
          <p className="text-[9px] font-mono text-[#3a3a3a] leading-relaxed px-1">
            <code>now</code>: live wall-clock time.{' '}
            <code>delamain_ref</code>: reference bundle status/list/reconcile.{' '}
            <code>delamain_vault_index</code>: deterministic vault index used by <code>search_vault</code>.
          </p>
        </section>
      )}

      {/* Budget */}
      {budgetEntries.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <SectionLabel>Copilot budget</SectionLabel>
          <ul className="flex flex-col gap-1">
            {budgetEntries.map((e) => (
              <EntryRow key={e.id} entry={e} />
            ))}
          </ul>
          <p className="text-[9px] font-mono text-[#3a3a3a] leading-relaxed px-1">
            Local counter only. GitHub does not expose per-account Copilot premium-request
            usage via REST; authoritative numbers require parsing Copilot response headers
            (backend Prompt B). Resets each UTC month.
          </p>
        </section>
      )}

      {otherEntries.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <SectionLabel>Other</SectionLabel>
          <ul className="flex flex-col gap-1">
            {otherEntries.map((e) => (
              <EntryRow key={e.id} entry={e} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
