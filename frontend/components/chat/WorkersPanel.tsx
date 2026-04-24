'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Plus, Square, Camera, FileText, Terminal, Globe, X,
  Maximize2, Minimize2, ChevronDown, ChevronRight, PlugZap, Cpu, Pencil,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Worker, WorkerStatus, WorkerTypeOption } from '@/lib/types'

const WORKER_ICON: Record<Worker['type'], React.ReactNode> = {
  opencode:       <Cpu size={12} />,
  claude:         <Cpu size={12} />,
  codex:          <Cpu size={12} />,
  gemini:         <Cpu size={12} />,
  tmux:           <Terminal size={12} />,
  winpc_shell:    <Globe size={12} />,
  winpc_opencode: <Globe size={12} />,
  winpc_claude:   <Globe size={12} />,
  winpc_codex:    <Globe size={12} />,
  winpc_gemini:   <Globe size={12} />,
  generic:        <Terminal size={12} />,
}

const TYPE_ID_ICON: Record<string, React.ReactNode> = {
  opencode:           WORKER_ICON.opencode,
  claude_code:        WORKER_ICON.claude,
  codex_cli:          WORKER_ICON.codex,
  gemini_cli:         WORKER_ICON.gemini,
  shell:              WORKER_ICON.tmux,
  winpc_shell:        WORKER_ICON.winpc_shell,
  winpc_opencode:     WORKER_ICON.winpc_opencode,
  winpc_claude_code:  WORKER_ICON.winpc_claude,
  winpc_codex_cli:    WORKER_ICON.winpc_codex,
  winpc_gemini_cli:   WORKER_ICON.winpc_gemini,
}

const STATUS_COLOR: Record<WorkerStatus, string> = {
  running:   'bg-[var(--accent-green)]',
  idle:      'bg-[#555555]',
  stopped:   'bg-[var(--accent-pink)]',
  capturing: 'bg-[var(--accent-blue)]',
}

const LIVE_POLL_MS = 2000

// ── Terminal (live-polled capture) ───────────────────────────────────────────

function WorkerTerminal({
  worker,
  fullscreen,
  onCapture,
  onToggleFullscreen,
  onClose,
}: {
  worker: Worker
  fullscreen: boolean
  onCapture: (id: string) => void
  onToggleFullscreen: () => void
  onClose?: () => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const lines = worker.output
    ? worker.output.split('\n')
    : ['(waiting for first capture…)']
  const live = worker.status === 'running'

  // Auto-scroll on new output
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [worker.output])

  // Poll capture while visible + worker is running. This is the
  // closest thing we have to a live feed until the backend adds a PTY
  // websocket. Each poll is GET /api/workers/{id}/output?lines=200.
  useEffect(() => {
    if (!live) return
    onCapture(worker.id)
    const h = setInterval(() => onCapture(worker.id), LIVE_POLL_MS)
    return () => clearInterval(h)
  }, [worker.id, live, onCapture])

  return (
    <div
      className={cn(
        'flex flex-col bg-[#030303] overflow-hidden',
        fullscreen
          ? 'fixed inset-0 z-50 rounded-none'
          : 'rounded-b-xl border-t border-white/[0.05]'
      )}
    >
      {/* Terminal title bar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/[0.06] flex-shrink-0 bg-[#080808]">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-[#555555]">{worker.name}</span>
          <span
            className={cn('w-1.5 h-1.5 rounded-full', STATUS_COLOR[worker.status], worker.status === 'running' && 'dot-pulse')}
          />
          {live && (
            <span className="text-[9px] font-mono text-[#3a3a3a]">
              polling every {LIVE_POLL_MS / 1000}s
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onCapture(worker.id)}
            className="p-1 text-[#444444] hover:text-[#888888] transition-colors rounded"
            aria-label="Refresh capture"
            title="Refresh now"
          >
            <Camera size={11} />
          </button>
          <button
            onClick={onToggleFullscreen}
            className="p-1 text-[#444444] hover:text-[#888888] transition-colors rounded"
            aria-label={fullscreen ? 'Minimize terminal' : 'Fullscreen terminal'}
            title={fullscreen ? 'Minimize' : 'Fullscreen'}
          >
            {fullscreen ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 text-[#444444] hover:text-[#888888] transition-colors rounded"
              aria-label="Close terminal"
            >
              <X size={11} />
            </button>
          )}
        </div>
      </div>

      {/* Output area */}
      <div
        className={cn(
          'overflow-y-auto px-3 py-2 font-mono text-[11px] leading-[1.7] text-[#7ec8a0] scrollbar-thin flex-1',
          fullscreen ? 'min-h-0' : 'h-48'
        )}
      >
        {lines.map((line, i) => (
          <div
            key={i}
            className="whitespace-pre-wrap break-all"
          >
            {line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Footer note — read-only for now */}
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-t border-white/[0.05] flex-shrink-0 bg-[#040404]">
        <span className="text-[9px] font-mono text-[#3a3a3a]">
          read-only · interactive PTY requires backend websocket bridge
        </span>
      </div>
    </div>
  )
}

// ── Action button ─────────────────────────────────────────────────────────────

function ActionBtn({
  icon, label, onClick, accent, disabled, title,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  accent?: 'pink' | 'red' | 'blue'
  disabled?: boolean
  title?: string
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        'inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[10px] font-mono transition-all',
        accent === 'pink' && 'border-[var(--accent-pink)]/30 text-[var(--accent-pink)] hover:bg-[var(--accent-pink)]/10',
        accent === 'red'  && 'border-[#c04040]/40 text-[#c04040] hover:bg-[#c04040]/10',
        accent === 'blue' && 'border-[var(--accent-blue)]/30 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10',
        !accent && 'border-white/[0.08] text-[#888888] hover:border-white/20 hover:text-white',
        disabled && 'opacity-40 cursor-not-allowed hover:!border-white/[0.08] hover:!text-[#888888]'
      )}
    >
      {icon}
      {label}
    </button>
  )
}

// ── Worker card ───────────────────────────────────────────────────────────────

interface WorkerCardProps {
  worker: Worker
  onCapture: (id: string) => void
  onSummarize: (id: string) => void
  onStop: (id: string) => void
  onKill: (id: string) => void
  onRename: (id: string, name: string) => void
}

function WorkerCard({ worker, onCapture, onSummarize, onStop, onKill, onRename }: WorkerCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [showTerminal, setShowTerminal] = useState(false)
  const [termFullscreen, setTermFullscreen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameDraft, setRenameDraft] = useState(worker.name)

  const handleToggleFullscreen = useCallback(() => {
    setTermFullscreen((v) => !v)
  }, [])

  const handleCloseTerminal = useCallback(() => {
    setShowTerminal(false)
    setTermFullscreen(false)
  }, [])

  const commitRename = () => {
    const v = renameDraft.trim()
    if (v && v !== worker.name) onRename(worker.id, v)
    setRenaming(false)
  }

  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] overflow-hidden">
      {/* Header row */}
      <div
        className="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/[0.02] transition-colors cursor-pointer group"
        onClick={() => !renaming && setExpanded((v) => !v)}
      >
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full flex-shrink-0',
            STATUS_COLOR[worker.status],
            worker.status === 'running' && 'dot-pulse'
          )}
        />
        <span style={{ color: 'var(--accent-blue)' }}>
          {WORKER_ICON[worker.type]}
        </span>
        <div className="flex-1 min-w-0">
          {renaming ? (
            <input
              autoFocus
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                e.stopPropagation()
                if (e.key === 'Enter') commitRename()
                if (e.key === 'Escape') {
                  setRenaming(false)
                  setRenameDraft(worker.name)
                }
              }}
              onClick={(e) => e.stopPropagation()}
              className="w-full bg-[#0a0a0a] border border-white/[0.12] text-xs font-mono text-white outline-none px-1.5 py-0.5 rounded"
            />
          ) : (
            <p className="text-xs font-mono text-[#cccccc] truncate">{worker.name}</p>
          )}
          <p className="text-[9px] font-mono text-[#444444]">
            {worker.host} &middot; {worker.status} &middot; {worker.type}
            {worker.lastActivity ? ` · ${worker.lastActivity}` : ''}
          </p>
        </div>
        {!renaming && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              setRenameDraft(worker.name)
              setRenaming(true)
            }}
            className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 text-[#555555] hover:text-white"
            aria-label={`Rename ${worker.name}`}
            title="Rename worker"
          >
            <Pencil size={11} />
          </button>
        )}
        {expanded
          ? <ChevronDown size={10} className="text-[#444444] flex-shrink-0" />
          : <ChevronRight size={10} className="text-[#444444] flex-shrink-0" />
        }
      </div>

      {expanded && (
        <div className="border-t border-white/[0.05]">
          {/* Action row */}
          <div className="flex items-center gap-1.5 flex-wrap px-3 py-2.5">
            <ActionBtn
              icon={<Camera size={10} />}
              label="Capture"
              onClick={() => onCapture(worker.id)}
              title="One-shot: fetch last 200 lines of tmux pane"
            />
            <ActionBtn
              icon={<FileText size={10} />}
              label="Summarize"
              onClick={() => onSummarize(worker.id)}
              title="Capture current pane, then ask the task model for a summary in a new conversation"
            />
            <ActionBtn
              icon={<PlugZap size={10} />}
              label={showTerminal ? 'Hide pane' : 'Live pane'}
              onClick={() => setShowTerminal((v) => !v)}
              accent="blue"
              title="Live-poll the tmux pane (read-only until PTY bridge exists)"
            />
            {worker.status === 'running' && (
              <ActionBtn icon={<Square size={10} />} label="Stop" onClick={() => onStop(worker.id)} accent="pink" />
            )}
            <ActionBtn icon={<X size={10} />} label="Kill" onClick={() => onKill(worker.id)} accent="red" />
          </div>

          {/* Inline live pane */}
          {showTerminal && !termFullscreen && (
            <WorkerTerminal
              worker={worker}
              fullscreen={false}
              onCapture={onCapture}
              onToggleFullscreen={handleToggleFullscreen}
              onClose={handleCloseTerminal}
            />
          )}
        </div>
      )}

      {/* Fullscreen pane */}
      {showTerminal && termFullscreen && (
        <WorkerTerminal
          worker={worker}
          fullscreen={true}
          onCapture={onCapture}
          onToggleFullscreen={handleToggleFullscreen}
          onClose={handleCloseTerminal}
        />
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface WorkersPanelProps {
  workers: Worker[]
  workerTypeOptions: WorkerTypeOption[]
  onAction: (workerId: string, action: 'capture' | 'stop' | 'kill') => void
  onSummarize: (workerId: string) => void
  onRename: (workerId: string, name: string) => void
  onStartWorker: (workerTypeId: string) => void
}

export function WorkersPanel({
  workers,
  workerTypeOptions,
  onAction,
  onSummarize,
  onRename,
  onStartWorker,
}: WorkersPanelProps) {
  const [showPresets, setShowPresets] = useState(false)
  const presetRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!showPresets) return
    const handler = (e: MouseEvent) => {
      if (presetRef.current && !presetRef.current.contains(e.target as Node)) {
        setShowPresets(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showPresets])

  // Group by host for easier scanning (serrano vs winpc)
  const grouped = workerTypeOptions.reduce<Record<string, WorkerTypeOption[]>>((acc, opt) => {
    const key = opt.host || 'local'
    acc[key] = acc[key] ?? []
    acc[key].push(opt)
    return acc
  }, {})

  return (
    <div className="flex flex-col gap-3 p-4">
      {/* Start new session */}
      <div ref={presetRef} className="relative">
        <button
          onClick={() => setShowPresets((v) => !v)}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl border border-dashed border-white/[0.1] text-[11px] font-mono text-[#555555] hover:border-white/20 hover:text-[#888888] transition-all"
        >
          <Plus size={11} />
          Start worker session
        </button>
        {showPresets && (
          <div className="absolute top-full left-0 right-0 mt-1 z-20 bg-[#111111] border border-white/[0.1] rounded-xl overflow-hidden shadow-2xl">
            {Object.entries(grouped).map(([host, opts]) => (
              <div key={host}>
                <div className="px-3 py-1.5 text-[9px] font-mono text-[#3a3a3a] uppercase tracking-wider bg-[#080808] border-b border-white/[0.04]">
                  {host}
                </div>
                {opts.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => { onStartWorker(p.id); setShowPresets(false) }}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs font-mono text-[#888888] hover:bg-white/[0.04] hover:text-white transition-colors"
                  >
                    <span style={{ color: 'var(--accent-blue)' }}>
                      {TYPE_ID_ICON[p.id] ?? WORKER_ICON.generic}
                    </span>
                    {p.label}
                  </button>
                ))}
              </div>
            ))}
            {workerTypeOptions.length === 0 && (
              <div className="px-3 py-2.5 text-xs font-mono text-[#555555]">
                No worker types available
              </div>
            )}
          </div>
        )}
      </div>

      {/* Worker cards */}
      {workers.length === 0 ? (
        <p className="text-xs font-mono text-[#3a3a3a] text-center py-6">No active worker sessions</p>
      ) : (
        <div className="flex flex-col gap-2">
          {workers.map((w) => (
            <WorkerCard
              key={w.id}
              worker={w}
              onCapture={(id) => onAction(id, 'capture')}
              onSummarize={onSummarize}
              onStop={(id) => onAction(id, 'stop')}
              onKill={(id) => onAction(id, 'kill')}
              onRename={onRename}
            />
          ))}
        </div>
      )}

      <p className="text-[9px] font-mono text-[#2a2a2a] mt-1 leading-relaxed">
        Workers are persistent tmux sessions for deep coding/research/admin jobs. They survive browser disconnects.
        Kill destroys the tmux session; Stop tries Ctrl-C then exit.
      </p>
    </div>
  )
}
