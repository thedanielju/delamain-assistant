'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Zap, CheckCheck, Loader2, AlertCircle, ChevronRight, ChevronLeft, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DirectAction, DirectActionGroup } from '@/lib/types'

const GROUP_LABELS: Record<DirectActionGroup, string> = {
  health: 'Health',
  ref: 'References',
  vault_index: 'Vault Index',
  sync_guard: 'Sync Guard',
  winpc: 'WinPC',
}

const GROUP_ACCENT: Record<DirectActionGroup, string> = {
  health: 'var(--accent-green)',
  ref: 'var(--accent-blue)',
  vault_index: 'var(--accent-blue)',
  sync_guard: 'var(--accent-purple)',
  winpc: 'var(--accent-pink)',
}

interface DirectActionsBarProps {
  actions?: DirectAction[]
  onRun: (actionId: string) => void
  conversationId?: string
}

export function DirectActionsBar({ actions: rawActions, onRun }: DirectActionsBarProps) {
  const actions: DirectAction[] = Array.isArray(rawActions) ? rawActions : []

  const [open, setOpen] = useState(false)
  const [activeGroup, setActiveGroup] = useState<DirectActionGroup | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const close = useCallback(() => {
    setOpen(false)
    setActiveGroup(null)
  }, [])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open, close])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (activeGroup !== null) {
          // First Escape goes back to group list
          setActiveGroup(null)
        } else {
          close()
          triggerRef.current?.focus()
        }
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, activeGroup, close])

  const toggleOpen = () => {
    const next = !open
    setOpen(next)
    if (!next) setActiveGroup(null)
  }

  const groups = (Object.keys(GROUP_LABELS) as DirectActionGroup[]).filter(
    (g) => actions.some((a) => a.group === g)
  )

  const actionsForGroup = (group: DirectActionGroup) =>
    actions.filter((a) => a.group === group)

  const runningCount = actions.filter((a) => a.status === 'running').length

  const handleRunAction = useCallback(
    (actionId: string) => {
      onRun(actionId)
      // keep menu open so user sees running state update
    },
    [onRun]
  )

  return (
    <div ref={containerRef} className="relative flex-shrink-0">
      {/* Trigger pill */}
      <button
        ref={triggerRef}
        onClick={toggleOpen}
        className={cn(
          'inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[10px] font-mono transition-all flex-shrink-0',
          open
            ? 'text-[var(--accent-blue)] border-[var(--accent-blue)]/50 bg-[var(--accent-blue)]/[0.08]'
            : 'border-[#333333] text-[#555555] hover:border-[#555555] hover:text-[#888888]'
        )}
        style={
          open ? { color: 'var(--accent-blue)', borderColor: 'color-mix(in srgb, var(--accent-blue) 50%, transparent)' } : {}
        }
        aria-label="Direct actions"
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <Zap size={9} />
        Actions
        {runningCount > 0 && (
          <span
            className="w-1.5 h-1.5 rounded-full dot-pulse flex-shrink-0"
            style={{ backgroundColor: 'var(--accent-green)' }}
          />
        )}
      </button>

      {/* Flyup menu */}
      {open && (
        <div
          className="absolute bottom-[calc(100%+8px)] left-0 z-50 bg-[#0f0f0f] border border-white/[0.10] rounded-xl shadow-2xl"
          style={{ width: 264 }}
          role="menu"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.06]">
            <p className="text-[9px] font-mono text-[#444444] uppercase tracking-wider">
              {activeGroup ? `${GROUP_LABELS[activeGroup]}` : 'Direct actions'}
            </p>
            <button
              onClick={close}
              className="text-[#444444] hover:text-[#888888] transition-colors p-0.5 rounded"
              aria-label="Close actions menu"
            >
              <X size={10} />
            </button>
          </div>

          {/* Group list view */}
          {activeGroup === null ? (
            <ul className="py-1 max-h-[280px] overflow-y-auto">
              {groups.length === 0 ? (
                <li className="px-3 py-3 text-xs font-mono text-[#444444]">No actions available</li>
              ) : (
                groups.map((group) => {
                  const groupActions = actionsForGroup(group)
                  const runningInGroup = groupActions.filter((a) => a.status === 'running').length
                  const doneInGroup = groupActions.filter((a) => a.status === 'done').length
                  return (
                    <li key={group}>
                      <button
                        onClick={() => setActiveGroup(group)}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2.5 hover:bg-white/[0.04] transition-colors text-left group"
                        role="menuitem"
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span
                            className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                            style={{ backgroundColor: GROUP_ACCENT[group] }}
                          />
                          <span className="text-xs font-mono text-[#aaaaaa] group-hover:text-white transition-colors">
                            {GROUP_LABELS[group]}
                          </span>
                          <span className="text-[9px] font-mono text-[#333333]">
                            {groupActions.length}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          {runningInGroup > 0 && (
                            <Loader2 size={9} className="animate-spin" style={{ color: 'var(--accent-green)' }} />
                          )}
                          {doneInGroup > 0 && runningInGroup === 0 && (
                            <CheckCheck size={9} style={{ color: 'var(--accent-green)' }} />
                          )}
                          <ChevronRight size={10} className="text-[#333333] group-hover:text-[#666666] transition-colors" />
                        </div>
                      </button>
                    </li>
                  )
                })
              )}
            </ul>
          ) : (
            /* Action list view */
            <div>
              {/* Back button */}
              <button
                onClick={() => setActiveGroup(null)}
                className="w-full flex items-center gap-1.5 px-3 py-2 text-[10px] font-mono text-[#555555] hover:text-[#aaaaaa] border-b border-white/[0.06] transition-colors"
                role="menuitem"
                aria-label="Back to groups"
              >
                <ChevronLeft size={10} />
                All groups
              </button>

              <ul className="py-1 max-h-[260px] overflow-y-auto">
                {actionsForGroup(activeGroup).map((action) => (
                  <li key={action.id}>
                    <button
                      onClick={() => handleRunAction(action.id)}
                      disabled={action.status === 'running'}
                      className="w-full flex items-center justify-between gap-2 px-3 py-2.5 hover:bg-white/[0.04] transition-colors disabled:opacity-50 disabled:cursor-not-allowed group"
                      role="menuitem"
                    >
                      <div className="flex flex-col gap-0.5 text-left min-w-0 flex-1">
                        <span className="text-xs font-mono text-[#cccccc] group-hover:text-white transition-colors">
                          {action.label}
                        </span>
                        {action.description && (
                          <span className="text-[10px] font-sans text-[#444444] leading-tight truncate">
                            {action.description}
                          </span>
                        )}
                      </div>
                      <div className="flex-shrink-0 ml-2">
                        {action.status === 'running' && (
                          <Loader2 size={10} className="animate-spin" style={{ color: 'var(--accent-blue)' }} />
                        )}
                        {action.status === 'done' && (
                          <CheckCheck size={10} style={{ color: 'var(--accent-green)' }} />
                        )}
                        {action.status === 'error' && (
                          <AlertCircle size={10} style={{ color: 'var(--accent-pink)' }} />
                        )}
                      </div>
                    </button>

                    {/* Inline result output */}
                    {action.result && (
                      <div className="mx-3 mb-1.5 rounded-md bg-[#080808] border border-white/[0.04] px-2.5 py-1.5">
                        <p className="text-[10px] font-mono text-[#888888] leading-relaxed whitespace-pre-wrap break-all">
                          {action.result}
                        </p>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
