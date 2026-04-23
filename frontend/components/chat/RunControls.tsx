'use client'

import { RotateCcw, Square } from 'lucide-react'
import type { ChatMessage, RunStatus } from '@/lib/types'

interface RunControlsProps {
  status?: RunStatus
  messages: ChatMessage[]
  onRetry: (runId: string) => void
  onCancel: (runId: string) => void
}

function lastRunId(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const runId = messages[i].runId
    if (runId) return runId
  }
  return null
}

export function RunControls({ status, messages, onRetry, onCancel }: RunControlsProps) {
  const runId = lastRunId(messages)
  if (!runId || !status) return null

  const showCancel = status === 'running' || status === 'queued' || status === 'waiting_approval'
  const showRetry = status === 'failed' || status === 'interrupted' || status === 'cancelled'

  if (!showCancel && !showRetry) return null

  return (
    <div className="inline-flex items-center gap-1">
      {showCancel && (
        <button
          onClick={() => onCancel(runId)}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-white/[0.08] text-[10px] font-mono text-[#aaaaaa] hover:text-accent-pink hover:border-accent-pink/40 transition-colors"
          title="Cancel run"
          aria-label="Cancel run"
        >
          <Square size={9} />
          cancel
        </button>
      )}
      {showRetry && (
        <button
          onClick={() => onRetry(runId)}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-white/[0.08] text-[10px] font-mono text-[#aaaaaa] hover:text-accent-blue hover:border-accent-blue/40 transition-colors"
          title="Retry run"
          aria-label="Retry run"
        >
          <RotateCcw size={9} />
          retry
        </button>
      )}
    </div>
  )
}
