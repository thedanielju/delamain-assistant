'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Network, FileText, RefreshCw, Tag, Link2, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api, BackendError } from '@/lib/api'
import type { VaultGraph, VaultNode, VaultNoteDetail } from '@/lib/types'

interface VaultPanelProps {
  conversationId: string
  onPinToContext?: (paths: string[]) => void
}

type LoadState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; status: number | null; message: string }
  | { kind: 'loaded'; graph: VaultGraph }

/**
 * Vault index panel. Depends on backend endpoints spec'd in Prompt D:
 *   GET /api/vault/graph        — list of nodes + edges
 *   GET /api/vault/note?path=…  — bounded note content
 *   POST/DELETE /api/conversations/{id}/context/pin  — pin notes to a run
 *
 * Until those land the panel shows a clear "awaiting backend" state and
 * documents the expected shape so the backend agent has a reference.
 */
export function VaultPanel({ conversationId, onPinToContext }: VaultPanelProps) {
  const [state, setState] = useState<LoadState>({ kind: 'idle' })
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [note, setNote] = useState<VaultNoteDetail | null>(null)
  const [tagFilter, setTagFilter] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    try {
      const graph = await api.getVaultGraph({ limit: 2000 })
      setState({ kind: 'loaded', graph })
    } catch (err) {
      const status = err instanceof BackendError ? err.status : null
      const message = err instanceof Error ? err.message : 'Failed to load vault graph'
      setState({ kind: 'error', status, message })
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const loadNote = useCallback(async (path: string) => {
    setSelectedPath(path)
    setNote(null)
    try {
      const detail = await api.getVaultNote(path)
      setNote(detail)
    } catch {
      setNote(null)
    }
  }, [])

  // All tags across nodes, sorted by count
  const tagCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    const counts = new Map<string, number>()
    for (const n of state.graph.nodes) {
      for (const t of n.tags) counts.set(t, (counts.get(t) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [state])

  const nodes = useMemo(() => {
    if (state.kind !== 'loaded') return [] as VaultNode[]
    const list = tagFilter
      ? state.graph.nodes.filter((n) => n.tags.includes(tagFilter))
      : state.graph.nodes
    return [...list].sort((a, b) => a.title.localeCompare(b.title))
  }, [state, tagFilter])

  const handlePin = () => {
    if (!selectedPath || !onPinToContext) return
    onPinToContext([selectedPath])
  }

  return (
    <div className="flex flex-col gap-3 p-4 h-full overflow-hidden">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[10px] font-mono text-[#555555]">
          <Network size={11} style={{ color: 'var(--accent-blue)' }} />
          <span>
            {state.kind === 'loaded'
              ? `${state.graph.nodes.length} notes · ${state.graph.edges.length} links`
              : 'vault index'}
          </span>
        </div>
        <button
          onClick={load}
          className="text-[#555555] hover:text-[var(--accent-blue)] transition-colors p-1 rounded"
          title="Reload vault graph"
          aria-label="Reload"
        >
          <RefreshCw size={12} className={cn(state.kind === 'loading' && 'animate-spin')} />
        </button>
      </div>

      {state.kind === 'loading' && (
        <p className="text-xs font-mono text-[#555555] text-center py-4">Loading vault graph…</p>
      )}

      {state.kind === 'error' && (
        <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-3 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <AlertCircle size={12} style={{ color: 'var(--accent-pink)' }} />
            <span className="text-xs font-mono text-[var(--accent-pink)]">
              Vault endpoints not available
            </span>
          </div>
          <p className="text-[10px] font-mono text-[#888888] leading-relaxed">
            The backend returned
            {state.status != null ? ` ${state.status}` : ' a network error'}: {state.message}
          </p>
          <p className="text-[10px] font-mono text-[#555555] leading-relaxed">
            Expected endpoints (backend Prompt D):
          </p>
          <ul className="text-[10px] font-mono text-[#666666] leading-relaxed list-disc pl-4">
            <li>
              <code>GET /api/vault/graph</code> → nodes/edges
            </li>
            <li>
              <code>GET /api/vault/note?path=…</code> → content + backlinks
            </li>
            <li>
              <code>POST /api/conversations/{'{id}'}/context/pin</code>
            </li>
          </ul>
        </div>
      )}

      {state.kind === 'loaded' && (
        <>
          {/* Tags row */}
          {tagCounts.length > 0 && (
            <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
              <button
                onClick={() => setTagFilter(null)}
                className={cn(
                  'inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-mono',
                  tagFilter === null
                    ? 'border-accent-blue/40 text-accent-blue bg-accent-blue/10'
                    : 'border-white/[0.08] text-[#888888] hover:text-white hover:border-white/20'
                )}
              >
                all
              </button>
              {tagCounts.slice(0, 40).map(([tag, count]) => (
                <button
                  key={tag}
                  onClick={() => setTagFilter(tag === tagFilter ? null : tag)}
                  className={cn(
                    'inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-mono',
                    tag === tagFilter
                      ? 'border-accent-blue/40 text-accent-blue bg-accent-blue/10'
                      : 'border-white/[0.08] text-[#888888] hover:text-white hover:border-white/20'
                  )}
                >
                  <Tag size={8} />
                  {tag}
                  <span className="text-[#444444]">{count}</span>
                </button>
              ))}
            </div>
          )}

          {/* Notes list */}
          <div className="flex-1 min-h-0 flex flex-col gap-0.5 overflow-y-auto rounded-lg border border-white/[0.05] bg-[#0a0a0a] p-1">
            {nodes.length === 0 ? (
              <p className="text-[11px] font-mono text-[#3a3a3a] text-center py-4">
                No notes {tagFilter ? `tagged "${tagFilter}"` : 'in index'}
              </p>
            ) : (
              nodes.map((n) => {
                const isSelected = selectedPath === n.path
                return (
                  <button
                    key={n.id}
                    onClick={() => loadNote(n.path)}
                    className={cn(
                      'w-full text-left px-2 py-1 rounded flex items-start gap-2 transition-colors',
                      isSelected
                        ? 'bg-accent-blue/15 text-white'
                        : 'hover:bg-white/[0.04] text-[#cccccc]'
                    )}
                  >
                    <FileText size={11} className="mt-0.5 flex-shrink-0 text-[#666666]" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] font-mono truncate">{n.title}</p>
                      <p className="text-[9px] font-mono text-[#555555] truncate">{n.path}</p>
                    </div>
                  </button>
                )
              })
            )}
          </div>

          {/* Note preview + pin */}
          {note && (
            <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-3 flex flex-col gap-2 max-h-64 overflow-hidden">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-[#cccccc] truncate">{note.title}</span>
                {onPinToContext && conversationId && (
                  <button
                    onClick={handlePin}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-accent-blue/40 text-[10px] font-mono text-accent-blue hover:bg-accent-blue/10"
                    title="Pin this note into the next run's context"
                  >
                    <Link2 size={10} /> Pin
                  </button>
                )}
              </div>
              <pre className="text-[10px] font-mono text-[#888888] whitespace-pre-wrap break-words overflow-y-auto flex-1">
                {note.content.slice(0, 1200)}
                {note.content.length > 1200 && '\n…'}
              </pre>
              {note.backlinks.length > 0 && (
                <div className="text-[9px] font-mono text-[#555555]">
                  backlinks: {note.backlinks.slice(0, 5).join(', ')}
                  {note.backlinks.length > 5 && ` +${note.backlinks.length - 5}`}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
