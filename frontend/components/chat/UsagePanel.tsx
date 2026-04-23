'use client'

import { useState } from 'react'
import { RefreshCw, DollarSign } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Progress } from '@/components/ui/progress'
import type {
  UsageProviderSummary,
  SubscriptionProvider,
  SubscriptionHost,
} from '@/lib/types'

// ── helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso?: string | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  if (diff < 0) return 'just now'
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

function statusDotClass(status: string): string {
  switch (status) {
    case 'ok':
      return 'bg-[var(--accent-green)]'
    case 'degraded':
      return 'bg-[var(--accent-blue)]'
    case 'unavailable':
    case 'error':
      return 'bg-[var(--accent-pink)]'
    default:
      return 'bg-[#444444]'
  }
}

function statusTextClass(status: string): string {
  switch (status) {
    case 'ok':
      return 'text-[var(--accent-green)]'
    case 'degraded':
      return 'text-[var(--accent-blue)]'
    case 'unavailable':
    case 'error':
      return 'text-[var(--accent-pink)]'
    default:
      return 'text-[#555555]'
  }
}

function formatUsed(p: UsageProviderSummary): string {
  const { used, limit, unit } = p
  const fmt = (n: number) => {
    if (unit === 'usd') return `$${n.toFixed(2)}`
    return n.toLocaleString()
  }
  if (limit != null) return `${fmt(used)} / ${fmt(limit)}`
  return fmt(used)
}

function unitLabel(unit: UsageProviderSummary['unit']): string {
  if (unit === 'premium_requests') return 'premium requests'
  if (unit === 'calls') return 'calls'
  return ''
}

// ── cards ─────────────────────────────────────────────────────────────────────

function UsageProviderCard({ provider }: { provider: UsageProviderSummary }) {
  const pct = provider.percent != null ? Math.min(100, Math.max(0, provider.percent)) : null
  const hasBar = provider.limit != null && pct != null

  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', statusDotClass(provider.status))} />
          <span className="text-xs font-mono text-[#cccccc] truncate">{provider.label}</span>
        </div>
        <span className={cn('text-[10px] font-mono flex-shrink-0', statusTextClass(provider.status))}>
          {provider.wired ? provider.status : 'not wired'}
        </span>
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] font-mono text-[#888888]">
        <span className="truncate">{provider.period || '—'}</span>
        <span className="text-[#cccccc] flex-shrink-0">{formatUsed(provider)}</span>
      </div>

      {hasBar && (
        <div className="mt-2">
          <Progress value={pct ?? 0} className="h-1 bg-white/[0.05]" />
          <div className="mt-1 flex justify-between text-[9px] font-mono text-[#3a3a3a]">
            <span>{unitLabel(provider.unit)}</span>
            <span>{pct?.toFixed(0)}%</span>
          </div>
        </div>
      )}

      {!hasBar && (
        <p className="mt-1.5 text-[9px] font-mono text-[#3a3a3a]">
          {unitLabel(provider.unit) || 'no limit'}
        </p>
      )}
    </div>
  )
}

function SubscriptionHostRow({ host }: { host: SubscriptionHost }) {
  return (
    <li className="flex items-start gap-2 py-1.5 border-t border-white/[0.04] first:border-t-0">
      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1', statusDotClass(host.status))} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-mono text-[#cccccc] truncate">{host.host}</span>
          <span className={cn('text-[10px] font-mono flex-shrink-0', statusTextClass(host.status))}>
            {host.status}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0 text-[9px] font-mono text-[#666666]">
          {host.account && <span>{host.account}</span>}
          {host.subscriptionType && <span className="text-[var(--accent-blue)]">{host.subscriptionType}</span>}
          {host.authMethod && <span>{host.authMethod}</span>}
          {host.version && <span>v{host.version}</span>}
        </div>
        {host.detail && (
          <p className="mt-0.5 text-[10px] font-sans text-[#555555] leading-tight">{host.detail}</p>
        )}
        {host.checkedAt && (
          <p className="mt-0.5 text-[9px] font-mono text-[#3a3a3a]">checked {relativeTime(host.checkedAt)}</p>
        )}
      </div>
    </li>
  )
}

function SubscriptionCard({ sub }: { sub: SubscriptionProvider }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', statusDotClass(sub.aggregateStatus))} />
          <span className="text-xs font-mono text-[#cccccc] truncate">{sub.label}</span>
        </div>
        <span className={cn('text-[10px] font-mono flex-shrink-0', statusTextClass(sub.aggregateStatus))}>
          {sub.aggregateStatus}
        </span>
      </div>

      {sub.hosts.length === 0 ? (
        <p className="mt-2 text-[10px] font-mono text-[#3a3a3a]">No hosts probed yet</p>
      ) : (
        <ul className="mt-2 flex flex-col">
          {sub.hosts.map((h) => (
            <SubscriptionHostRow key={`${sub.provider}-${h.host}`} host={h} />
          ))}
        </ul>
      )}
    </div>
  )
}

// ── section ──────────────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <p className="text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider px-1">{label}</p>
  )
}

// ── main panel ───────────────────────────────────────────────────────────────

interface UsagePanelProps {
  usageProviders: UsageProviderSummary[]
  subscriptions: SubscriptionProvider[]
  onRefresh: (opts: { refreshSubscriptions?: boolean }) => void
}

export function UsagePanel({ usageProviders, subscriptions, onRefresh }: UsagePanelProps) {
  const [refreshing, setRefreshing] = useState(false)
  const [refreshingSubs, setRefreshingSubs] = useState(false)

  const handleRefresh = () => {
    setRefreshing(true)
    onRefresh({})
    setTimeout(() => setRefreshing(false), 1200)
  }

  const handleRefreshSubs = () => {
    setRefreshingSubs(true)
    onRefresh({ refreshSubscriptions: true })
    setTimeout(() => setRefreshingSubs(false), 1500)
  }

  const byId = (id: string) => usageProviders.find((p) => p.provider === id)

  const copilot = byId('copilot')
  const openrouter = byId('openrouter')
  const claudeUsage = byId('claude')
  const codexUsage = byId('codex')

  const subscriptionOrder = ['codex', 'claude', 'gemini']
  const sortedSubscriptions = [...subscriptions].sort((a, b) => {
    const ai = subscriptionOrder.indexOf(a.provider)
    const bi = subscriptionOrder.indexOf(b.provider)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi) || a.label.localeCompare(b.label)
  })

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-[#555555]">
          <DollarSign size={11} style={{ color: 'var(--accent-blue)' }} />
          <span>usage &amp; subscriptions</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleRefreshSubs}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-white/[0.08] text-[10px] font-mono text-[#888888] hover:border-white/20 hover:text-white transition-all"
            aria-label="Refresh subscriptions"
            title="Re-probe subscription hosts"
          >
            <RefreshCw size={10} className={cn('transition-transform', refreshingSubs && 'animate-spin')} />
            subs
          </button>
          <button
            onClick={handleRefresh}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-white/[0.08] text-[10px] font-mono text-[#888888] hover:border-white/20 hover:text-white transition-all"
            aria-label="Refresh usage"
            title="Refresh usage"
          >
            <RefreshCw size={10} className={cn('transition-transform', refreshing && 'animate-spin')} />
            refresh
          </button>
        </div>
      </div>

      {/* Subscriptions section */}
      <section className="flex flex-col gap-2">
        <SectionHeader label="Subscriptions" />
        {copilot && <UsageProviderCard provider={copilot} />}
        {openrouter && <UsageProviderCard provider={openrouter} />}
        {sortedSubscriptions.map((sub) => (
          <SubscriptionCard key={sub.provider} sub={sub} />
        ))}
        {sortedSubscriptions.length === 0 && (
          <p className="text-[10px] font-mono text-[#3a3a3a] px-1">No subscription probes</p>
        )}
      </section>

      {/* API section */}
      <section className="flex flex-col gap-2">
        <SectionHeader label="API" />
        {claudeUsage && <UsageProviderCard provider={claudeUsage} />}
        {codexUsage && <UsageProviderCard provider={codexUsage} />}
        {!claudeUsage && !codexUsage && (
          <p className="text-[10px] font-mono text-[#3a3a3a] px-1">No API usage data</p>
        )}
      </section>
    </div>
  )
}
