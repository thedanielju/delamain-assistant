'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Plus, Square, Camera, FileText, Terminal, Globe, X,
  Maximize2, Minimize2, ChevronDown, ChevronRight, PlugZap, Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Worker, WorkerStatus } from '@/lib/types'

const WORKER_ICON: Record<Worker['type'], React.ReactNode> = {
  codex:    <Cpu size={12} />,
  opencode: <Cpu size={12} />,
  claude:   <Cpu size={12} />,
  goose:    <Cpu size={12} />,
  gemini:   <Cpu size={12} />,
  gh_cli:   <Globe size={12} />,
  tmux:     <Terminal size={12} />,
  generic:  <Terminal size={12} />,
}

const STATUS_COLOR: Record<WorkerStatus, string> = {
  running:   'bg-[var(--accent-green)]',
  idle:      'bg-[#555555]',
  stopped:   'bg-[var(--accent-pink)]',
  capturing: 'bg-[var(--accent-blue)]',
}

const WORKER_PRESETS: { type: Worker['type']; label: string }[] = [
  { type: 'codex',   label: 'Codex' },
  { type: 'claude',  label: 'Claude Code' },
  { type: 'goose',   label: 'Goose' },
  { type: 'gemini',  label: 'Gemini' },
  { type: 'gh_cli',  label: 'GitHub CLI' },
  { type: 'tmux',    label: 'tmux (local)' },
]

const DEMO_OUTPUT: Record<Worker['type'], string[]> = {
  codex:    ['$ codex --model gpt-4.1', '> Loading context...', '> Ready.'],
  opencode: ['$ opencode', '> Starting session...'],
  claude:   ['$ claude', '> Authenticating...', '> Session started.'],
  goose:    ['$ goose session', '> Initialising...', '> Provider: openai'],
  gemini:   ['$ gemini-cli', '> Connected to Gemini 2.5 Pro'],
  gh_cli:   ['$ gh pr list', '#42  fix: memory leak       open', '#41  feat: sse support      merged'],
  tmux:     ['$ tmux new -s delamain', '[delamain] 0:bash*'],
  generic:  ['$ /bin/bash'],
}

// ── Terminal ─────────────────────────────────────────────────────────────────

function WorkerTerminal({
  worker,
  fullscreen,
  onToggleFullscreen,
  onClose,
}: {
  worker: Worker
  fullscreen: boolean
  onToggleFullscreen: () => void
  onClose?: () => void
}) {
  const [lines, setLines] = useState<string[]>(DEMO_OUTPUT[worker.type] ?? ['$ _'])
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && input.trim()) {
      const cmd = input.trim()
      setLines((prev) => [...prev, `$ ${cmd}`, '[output pending — backend not connected]'])
      setInput('')
    }
  }

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
        </div>
        <div className="flex items-center gap-1">
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
            className={cn('whitespace-pre-wrap break-all', line.startsWith('$') && 'text-[#666666]')}
          >
            {line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-t border-white/[0.05] flex-shrink-0 bg-[#040404]">
        <span className="text-[10px] font-mono text-[#3a3a3a] flex-shrink-0">$</span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={worker.status === 'stopped' ? 'session stopped' : 'type a command…'}
          disabled={worker.status === 'stopped'}
          className="flex-1 bg-transparent text-[11px] font-mono text-[#cccccc] outline-none placeholder-[#333333] disabled:opacity-40"
          aria-label="Terminal input"
          autoComplete="off"
          spellCheck={false}
        />
        {worker.status !== 'stopped' && (
          <kbd className="text-[9px] font-mono text-[#2a2a2a] border border-[#2a2a2a] rounded px-1 flex-shrink-0">
            Enter
          </kbd>
        )}
      </div>
    </div>
  )
}

// ── Action button ─────────────────────────────────────────────────────────────

function ActionBtn({
  icon, label, onClick, accent,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  accent?: 'pink' | 'red' | 'blue'
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[10px] font-mono transition-all',
        accent === 'pink' && 'border-[var(--accent-pink)]/30 text-[var(--accent-pink)] hover:bg-[var(--accent-pink)]/10',
        accent === 'red'  && 'border-[#c04040]/40 text-[#c04040] hover:bg-[#c04040]/10',
        accent === 'blue' && 'border-[var(--accent-blue)]/30 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10',
        !accent && 'border-white/[0.08] text-[#888888] hover:border-white/20 hover:text-white'
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
}

function WorkerCard({ worker, onCapture, onSummarize, onStop, onKill }: WorkerCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [showTerminal, setShowTerminal] = useState(false)
  const [termFullscreen, setTermFullscreen] = useState(false)

  const handleToggleFullscreen = useCallback(() => {
    setTermFullscreen((v) => !v)
  }, [])

  const handleCloseTerminal = useCallback(() => {
    setShowTerminal(false)
    setTermFullscreen(false)
  }, [])

  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/[0.02] transition-colors text-left"
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
          <p className="text-xs font-mono text-[#cccccc] truncate">{worker.name}</p>
          <p className="text-[9px] font-mono text-[#444444]">
            {worker.host} &middot; {worker.status}
            {worker.lastActivity ? ` · ${worker.lastActivity}` : ''}
          </p>
        </div>
        {expanded
          ? <ChevronDown size={10} className="text-[#444444] flex-shrink-0" />
          : <ChevronRight size={10} className="text-[#444444] flex-shrink-0" />
        }
      </button>

      {expanded && (
        <div className="border-t border-white/[0.05]">
          {/* Action row */}
          <div className="flex items-center gap-1.5 flex-wrap px-3 py-2.5">
            <ActionBtn icon={<Camera size={10} />} label="Capture" onClick={() => onCapture(worker.id)} />
            <ActionBtn icon={<FileText size={10} />} label="Summarize" onClick={() => onSummarize(worker.id)} />
            <ActionBtn
              icon={<PlugZap size={10} />}
              label={showTerminal ? 'Hide' : 'Terminal'}
              onClick={() => setShowTerminal((v) => !v)}
              accent="blue"
            />
            {worker.status === 'running' && (
              <ActionBtn icon={<Square size={10} />} label="Stop" onClick={() => onStop(worker.id)} accent="pink" />
            )}
            <ActionBtn icon={<X size={10} />} label="Kill" onClick={() => onKill(worker.id)} accent="red" />
          </div>

          {/* Inline terminal */}
          {showTerminal && !termFullscreen && (
            <WorkerTerminal
              worker={worker}
              fullscreen={false}
              onToggleFullscreen={handleToggleFullscreen}
              onClose={handleCloseTerminal}
            />
          )}
        </div>
      )}

      {/* Fullscreen terminal — portal-like overlay */}
      {showTerminal && termFullscreen && (
        <WorkerTerminal
          worker={worker}
          fullscreen={true}
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
  onAction: (workerId: string, action: 'capture' | 'summarize' | 'stop' | 'kill') => void
  onStartWorker: (type: Worker['type']) => void
}

export function WorkersPanel({ workers, onAction, onStartWorker }: WorkersPanelProps) {
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
            {WORKER_PRESETS.map((p) => (
              <button
                key={p.type}
                onClick={() => { onStartWorker(p.type); setShowPresets(false) }}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs font-mono text-[#888888] hover:bg-white/[0.04] hover:text-white transition-colors"
              >
                <span style={{ color: 'var(--accent-blue)' }}>{WORKER_ICON[p.type]}</span>
                {p.label}
              </button>
            ))}
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
              onSummarize={(id) => onAction(id, 'summarize')}
              onStop={(id) => onAction(id, 'stop')}
              onKill={(id) => onAction(id, 'kill')}
            />
          ))}
        </div>
      )}

      <p className="text-[9px] font-mono text-[#2a2a2a] mt-1 leading-relaxed">
        Workers are for deep coding/research/admin jobs &mdash; not Q&amp;A, health checks, or vault indexing.
      </p>
    </div>
  )
}
