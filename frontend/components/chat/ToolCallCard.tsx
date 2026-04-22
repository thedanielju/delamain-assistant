'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ToolCall } from '@/lib/types'

const ACCENT_COLORS = {
  blue: { border: 'border-l-[#7eb8da]', dot: 'bg-[#7eb8da]', text: 'text-[#7eb8da]' },
  green: { border: 'border-l-[#7ec8a0]', dot: 'bg-[#7ec8a0]', text: 'text-[#7ec8a0]' },
  pink: { border: 'border-l-[#f4a0b0]', dot: 'bg-[#f4a0b0]', text: 'text-[#f4a0b0]' },
}

function StatusDot({ status }: { status: ToolCall['status'] }) {
  if (status === 'running') {
    return (
      <span className="inline-block w-2 h-2 rounded-full bg-[#7eb8da] dot-pulse" aria-label="Running" />
    )
  }
  if (status === 'success') {
    return <span className="inline-block w-2 h-2 rounded-full bg-[#7ec8a0]" aria-label="Success" />
  }
  return <span className="inline-block w-2 h-2 rounded-full bg-[#f4a0b0]" aria-label="Error" />
}

interface ToolCallCardProps {
  tool: ToolCall
  defaultExpanded?: boolean
}

export function ToolCallCard({ tool, defaultExpanded = false }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const accent = ACCENT_COLORS[tool.accentColor ?? 'blue']
  const isError = tool.status === 'error'

  return (
    <div
      className={cn(
        'rounded-md border border-white/[0.06] border-l-2 bg-[#0d0d0d] overflow-hidden text-xs',
        isError ? 'border-l-[#f4a0b0]' : accent.border
      )}
    >
      {/* Collapsed header — always visible */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-white/[0.02] transition-colors text-left"
        aria-expanded={expanded}
      >
        <span className="text-[#888888]">
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </span>
        <span className={cn('font-mono font-medium text-[11px]', accent.text)}>
          {tool.name}
        </span>
        <span className="text-[#888888] font-mono text-[11px] flex-1 truncate">
          {tool.summary}
        </span>
        <div className="flex items-center gap-2 flex-shrink-0">
          {tool.durationMs !== undefined && tool.status !== 'running' && (
            <span className="text-[#555555] font-mono text-[10px]">
              {tool.durationMs}ms
            </span>
          )}
          <StatusDot status={tool.status} />
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-white/[0.06] px-3 py-2.5 flex flex-col gap-2.5">
          {/* Args */}
          {tool.args && (
            <div>
              <p className="text-[10px] font-mono text-[#555555] uppercase tracking-wider mb-1">Arguments</p>
              <pre className="bg-[#111111] rounded p-2 text-[11px] font-mono text-[#cccccc] overflow-x-auto leading-relaxed">
                {JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          )}

          {/* Stdout */}
          {tool.stdout && (
            <div>
              <p className="text-[10px] font-mono text-[#555555] uppercase tracking-wider mb-1">Output</p>
              <pre className="bg-[#0a0a0a] rounded p-2 text-[11px] font-mono text-[#9ab8a0] overflow-x-auto leading-relaxed whitespace-pre-wrap">
                {tool.stdout}
              </pre>
            </div>
          )}

          {/* Stderr */}
          {tool.stderr && (
            <div>
              <p className="text-[10px] font-mono text-[#555555] uppercase tracking-wider mb-1">Stderr</p>
              <pre className="bg-[#1a0808] rounded p-2 text-[11px] font-mono text-[#f4a0b0] overflow-x-auto leading-relaxed whitespace-pre-wrap">
                {tool.stderr}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
