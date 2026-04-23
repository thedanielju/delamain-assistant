'use client'

import { useMemo, useState } from 'react'
import { ShieldCheck, ShieldX, Check, X as XIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Permission } from '@/lib/types'

interface PermissionModalProps {
  permissions: Permission[]
  onResolve: (permissionId: string, decision: 'approved' | 'denied', note?: string) => void
  onRememberPolicy?: (toolName: string, policy: 'auto' | 'confirm') => void
}

function parseDetails(json: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(json)
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

function extractToolName(kind: string, details: Record<string, unknown>): string | null {
  if (typeof details.tool === 'string') return details.tool
  if (typeof details.tool_name === 'string') return details.tool_name
  if (kind.startsWith('tool:')) return kind.slice(5)
  return null
}

export function PermissionModal({
  permissions,
  onResolve,
  onRememberPolicy,
}: PermissionModalProps) {
  const pending = useMemo(
    () => permissions.filter((p) => p.status === 'pending'),
    [permissions]
  )
  const [noteDraft, setNoteDraft] = useState('')

  if (pending.length === 0) return null
  const current = pending[0]
  const details = parseDetails(current.detailsJson)
  const toolName = extractToolName(current.kind, details)

  const approve = (remember: boolean) => {
    if (remember && toolName && onRememberPolicy) {
      onRememberPolicy(toolName, 'auto')
    }
    onResolve(current.id, 'approved', noteDraft || undefined)
    setNoteDraft('')
  }

  const deny = () => {
    onResolve(current.id, 'denied', noteDraft || undefined)
    setNoteDraft('')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="w-full max-w-lg bg-[#0a0a0a] border border-accent-pink/40 rounded-lg shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-2">
            <ShieldCheck size={14} className="text-accent-pink" />
            <span className="text-xs font-mono font-semibold text-white uppercase tracking-wider">
              Permission required
            </span>
            {pending.length > 1 && (
              <span className="text-[10px] font-mono text-[#888888]">
                · {pending.length} pending
              </span>
            )}
          </div>
          <span className="text-[10px] font-mono text-[#555555]">{current.kind}</span>
        </div>

        <div className="px-4 py-4 space-y-3">
          <p className="text-sm text-white font-sans leading-relaxed">{current.summary}</p>

          {Object.keys(details).length > 0 && (
            <details className="rounded-md bg-[#050505] border border-white/[0.06] overflow-hidden">
              <summary className="px-3 py-2 text-[11px] font-mono text-[#888888] cursor-pointer hover:text-white">
                details
              </summary>
              <pre className="px-3 py-2 text-[11px] font-mono text-[#cccccc] whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                {JSON.stringify(details, null, 2)}
              </pre>
            </details>
          )}

          <input
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            placeholder="Note (optional)"
            className="w-full bg-[#111111] border border-white/[0.08] text-xs text-white placeholder-[#555555] font-mono outline-none px-2.5 py-1.5 rounded"
          />
        </div>

        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-white/[0.06] bg-[#050505]">
          <button
            onClick={deny}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs font-sans',
              'border-accent-pink/40 text-accent-pink hover:bg-accent-pink/10 transition-colors'
            )}
          >
            <ShieldX size={12} />
            Deny
          </button>
          <div className="flex items-center gap-2">
            {toolName && onRememberPolicy && (
              <button
                onClick={() => approve(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-white/[0.08] text-[#cccccc] hover:text-white hover:border-white/[0.18] text-xs font-sans transition-colors"
                title={`Approve and set ${toolName}'s policy to auto for future runs`}
              >
                <Check size={12} />
                Approve &amp; auto-allow
              </button>
            )}
            <button
              onClick={() => approve(false)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-accent-green/40 text-accent-green hover:bg-accent-green/10 text-xs font-sans transition-colors"
            >
              <Check size={12} />
              Approve
            </button>
          </div>
        </div>

        <button
          onClick={deny}
          className="absolute top-2 right-2 text-[#555555] hover:text-white p-1 rounded"
          aria-label="Close"
          tabIndex={-1}
        >
          <XIcon size={14} />
        </button>
      </div>
    </div>
  )
}
