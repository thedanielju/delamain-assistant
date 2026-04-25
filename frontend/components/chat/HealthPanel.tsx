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
import type { HealthEntry, HealthStatus, HealthSystemMetrics, SyncthingDevice } from '@/lib/types'

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

function formatBytes(mb: number): string {
  if (!Number.isFinite(mb)) return 'unknown'
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${Math.round(mb)} MB`
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return 'unknown'
  return `${Math.round(value)}%`
}

function formatUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return 'unknown'
  const totalMinutes = Math.floor(seconds / 60)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function metricTone(status: 'ok' | 'warn' | 'error') {
  if (status === 'error') {
    return {
      border: 'border-[var(--accent-pink)]/25',
      icon: 'text-[var(--accent-pink)]',
      value: 'text-[var(--accent-pink)]',
    }
  }
  if (status === 'warn') {
    return {
      border: 'border-[var(--accent-blue)]/20',
      icon: 'text-[var(--accent-blue)]',
      value: 'text-[var(--accent-blue)]',
    }
  }
  return {
    border: 'border-white/[0.04]',
    icon: 'text-[#555555]',
    value: 'text-[#cccccc]',
  }
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  status = 'ok',
}: {
  icon: React.ReactNode
  label: string
  value: string
  detail: string
  status?: 'ok' | 'warn' | 'error'
}) {
  const tone = metricTone(status)
  return (
    <div className={cn('rounded-md bg-[#0a0a0a] border px-2 py-2 flex flex-col gap-1 min-w-0', tone.border)}>
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={cn('flex-shrink-0', tone.icon)}>{icon}</span>
        <span className="text-[9px] font-mono text-[#3a3a3a] uppercase">{label}</span>
      </div>
      <span className={cn('text-[11px] font-mono leading-tight', tone.value)}>{value}</span>
      <span className="text-[9px] font-mono text-[#4a4a4a] leading-tight break-words">{detail}</span>
    </div>
  )
}

function SystemMetricsCard({ system }: { system: HealthSystemMetrics | null }) {
  if (!system) {
    return (
      <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-3 flex flex-col gap-2">
        <div className="grid grid-cols-3 gap-2">
          <MetricCard icon={<MemoryStick size={12} />} label="memory" value="missing" detail="/api/health.system" />
          <MetricCard icon={<Cpu size={12} />} label="backend" value="missing" detail="process metrics" />
          <MetricCard icon={<HardDrive size={12} />} label="disk" value="missing" detail="host disks" />
        </div>
        <p className="text-[9px] font-mono text-[#3a3a3a] leading-relaxed">
          The backend did not include <code>system</code> in <code>/api/health</code>.
        </p>
      </div>
    )
  }

  const memoryUsedPercent =
    system.host.memoryTotalMb > 0
      ? ((system.host.memoryTotalMb - system.host.memoryAvailableMb) / system.host.memoryTotalMb) * 100
      : 0
  const memoryAvailablePercent =
    system.host.memoryTotalMb > 0
      ? (system.host.memoryAvailableMb / system.host.memoryTotalMb) * 100
      : 0
  const memoryStatus =
    system.host.memoryAvailableMb < 2048 || memoryAvailablePercent < 10
      ? 'error'
      : system.host.memoryAvailableMb < 4096 || memoryAvailablePercent < 20
      ? 'warn'
      : 'ok'

  const primaryDisk = [...system.host.disks].sort((a, b) => b.percentUsed - a.percentUsed)[0]
  const diskStatus = primaryDisk
    ? primaryDisk.percentUsed >= 95
      ? 'error'
      : primaryDisk.percentUsed >= 90
      ? 'warn'
      : 'ok'
    : 'warn'

  const load = system.host.loadAvg
  const loadLabel = [load.one, load.five, load.fifteen]
    .map((n) => (typeof n === 'number' ? n.toFixed(2) : '?'))
    .join(' / ')

  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-3 flex flex-col gap-2">
      <div className="grid grid-cols-3 gap-2">
        <MetricCard
          icon={<MemoryStick size={12} />}
          label="mem"
          value={formatBytes(system.host.memoryAvailableMb)}
          detail={`free; ${formatPercent(memoryUsedPercent)} used`}
          status={memoryStatus}
        />
        <MetricCard
          icon={<Cpu size={12} />}
          label="api"
          value={`${formatPercent(system.delamainBackend.cpuPercent1Min)} cpu`}
          detail={`${formatBytes(system.delamainBackend.rssMb)} RSS; ${system.delamainBackend.numThreads} threads`}
        />
        <MetricCard
          icon={<HardDrive size={12} />}
          label="disk"
          value={primaryDisk ? formatPercent(primaryDisk.percentUsed) : 'unknown'}
          detail={
            primaryDisk
              ? `${primaryDisk.mountpoint}; ${formatBytes(primaryDisk.freeMb)} free`
              : 'no disks reported'
          }
          status={diskStatus}
        />
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[9px] font-mono text-[#555555]">
        <span>host: {system.host.hostname}</span>
        <span className="break-all">kernel: {system.host.kernel}</span>
        <span>load: {loadLabel}</span>
        <span>pid: {system.delamainBackend.pid}</span>
        <span>uptime: {formatUptime(system.delamainBackend.uptimeSeconds)}</span>
        <span>
          tmux: {system.tmuxWorkers.count} workers / {formatBytes(system.tmuxWorkers.rssMbTotal)}
        </span>
      </div>
    </div>
  )
}

interface HealthPanelProps {
  entries: HealthEntry[]
  system: HealthSystemMetrics | null
  syncthingDevices: SyncthingDevice[]
  syncthingConflictCount: number
  onRefresh?: () => void | Promise<void>
  onOpenSyncthing: () => void
}

export function HealthPanel({
  entries,
  system,
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

      <section className="flex flex-col gap-1.5">
        <SectionLabel>System resources (serrano)</SectionLabel>
        <SystemMetricsCard system={system} />
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
