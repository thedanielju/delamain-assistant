'use client'

import { cn } from '@/lib/utils'
import type { RunStatus } from '@/lib/types'

interface RunStatusPillProps {
  status?: RunStatus
  className?: string
}

type StatusMeta = {
  label: string
  dotClass: string
  textClass: string
  pulse?: boolean
}

const STATUS_META: Record<RunStatus, StatusMeta> = {
  queued:           { label: 'queued',    dotClass: 'bg-[#888888]',  textClass: 'text-[#888888]' },
  running:          { label: 'running',   dotClass: 'bg-accent-blue', textClass: 'text-accent-blue', pulse: true },
  waiting_approval: { label: 'approval',  dotClass: 'bg-accent-pink', textClass: 'text-accent-pink', pulse: true },
  completed:        { label: 'ready',     dotClass: 'bg-accent-green', textClass: 'text-[#888888]' },
  failed:           { label: 'failed',    dotClass: 'bg-destructive',  textClass: 'text-destructive' },
  interrupted:      { label: 'interrupt', dotClass: 'bg-accent-pink',  textClass: 'text-accent-pink' },
  cancelled:        { label: 'cancelled', dotClass: 'bg-[#555555]',    textClass: 'text-[#555555]' },
}

export function RunStatusPill({ status, className }: RunStatusPillProps) {
  if (!status) return null
  const meta = STATUS_META[status]
  if (!meta) return null

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-white/[0.08] bg-black text-[10px] font-mono tracking-tight whitespace-nowrap',
        meta.textClass,
        className
      )}
      title={`Run status: ${status}`}
      aria-label={`Run status: ${status}`}
    >
      <span
        className={cn(
          'inline-block w-1.5 h-1.5 rounded-full',
          meta.dotClass,
          meta.pulse && 'dot-pulse'
        )}
      />
      {meta.label}
    </span>
  )
}
