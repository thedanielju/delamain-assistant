'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, Maximize2, Minimize2, X } from 'lucide-react'
import { workerPtyWebSocketUrl } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Worker, WorkerStatus } from '@/lib/types'

const STATUS_COLOR: Record<WorkerStatus, string> = {
  running: 'bg-[var(--accent-green)]',
  idle: 'bg-[#555555]',
  stopped: 'bg-[var(--accent-pink)]',
  capturing: 'bg-[var(--accent-blue)]',
}

type TerminalInstance = import('@xterm/xterm').Terminal

interface WorkerTerminalXtermProps {
  worker: Worker
  fullscreen: boolean
  onCapture: (id: string) => void
  onToggleFullscreen: () => void
  onClose?: () => void
}

export function WorkerTerminalXterm({
  worker,
  fullscreen,
  onCapture,
  onToggleFullscreen,
  onClose,
}: WorkerTerminalXtermProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<TerminalInstance | null>(null)
  const fitRef = useRef<{ fit: () => void } | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const [connection, setConnection] = useState<'connecting' | 'connected' | 'closed' | 'fallback'>(
    worker.status === 'running' ? 'connecting' : 'fallback'
  )
  const [statusMessage, setStatusMessage] = useState(
    worker.status === 'running' ? 'opening websocket' : 'manual snapshot mode'
  )

  const fitTerminal = useCallback(() => {
    requestAnimationFrame(() => {
      try {
        fitRef.current?.fit()
      } catch {
        /* no-op */
      }
    })
  }, [])

  const live = worker.status === 'running'
  const fallbackOutput = live ? undefined : worker.output

  useEffect(() => {
    let disposed = false
    let dataDisposable: { dispose: () => void } | null = null
    let resizeObserver: ResizeObserver | null = null
    let terminal: TerminalInstance | null = null
    let socket: WebSocket | null = null

    const setup = async () => {
      const [{ Terminal }, { FitAddon }, { WebLinksAddon }] = await Promise.all([
        import('@xterm/xterm'),
        import('@xterm/addon-fit'),
        import('@xterm/addon-web-links'),
      ])
      if (disposed || !containerRef.current) return

      terminal = new Terminal({
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: true,
        fontFamily: 'var(--font-mono), ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 11,
        lineHeight: 1.25,
        scrollback: 5000,
        theme: {
          background: '#030303',
          foreground: '#9fd8b7',
          cursor: '#7eb8da',
          selectionBackground: '#1e3a4a',
          black: '#000000',
          red: '#f4a0b0',
          green: '#7ec8a0',
          yellow: '#d8c070',
          blue: '#7eb8da',
          magenta: '#b8a0e8',
          cyan: '#80d0d0',
          white: '#dddddd',
          brightBlack: '#555555',
          brightRed: '#ffb0c0',
          brightGreen: '#9fe0b8',
          brightYellow: '#ead489',
          brightBlue: '#9bcbe5',
          brightMagenta: '#cdb5f0',
          brightCyan: '#9de0e0',
          brightWhite: '#ffffff',
        },
      })
      const fitAddon = new FitAddon()
      terminal.loadAddon(fitAddon)
      terminal.loadAddon(new WebLinksAddon())
      terminal.open(containerRef.current)
      terminalRef.current = terminal
      fitRef.current = fitAddon
      fitTerminal()

      resizeObserver = new ResizeObserver(fitTerminal)
      resizeObserver.observe(containerRef.current)

      if (!live) {
        setConnection('fallback')
        setStatusMessage('manual snapshot mode')
        terminal.write(fallbackOutput || 'No snapshot captured.\r\n')
        return
      }

      terminal.writeln('connecting to worker pty...')
      socket = new WebSocket(workerPtyWebSocketUrl(worker.id))
      wsRef.current = socket

      dataDisposable = terminal.onData((data) => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'input', data }))
        }
      })

      socket.onopen = () => {
        if (disposed) return
        setConnection('connected')
        setStatusMessage('websocket live')
      }
      socket.onmessage = (event) => {
        if (disposed || !terminal) return
        try {
          const payload = JSON.parse(String(event.data)) as {
            type?: string
            data?: string
            message?: string
          }
          if (payload.type === 'snapshot') {
            terminal.reset()
            terminal.write(payload.data ?? '')
          } else if (payload.type === 'data') {
            terminal.write(payload.data ?? '')
          } else if (payload.type === 'error') {
            setConnection('closed')
            setStatusMessage(payload.message || 'pty bridge closed')
            terminal.writeln(`\r\n${payload.message || 'pty bridge closed'}`)
          }
        } catch {
          terminal.write(String(event.data))
        }
      }
      socket.onclose = () => {
        if (disposed) return
        setConnection('closed')
        setStatusMessage('websocket closed; capture is available')
      }
      socket.onerror = () => {
        if (disposed) return
        setConnection('closed')
        setStatusMessage('websocket error; capture is available')
      }
    }

    setup()

    return () => {
      disposed = true
      dataDisposable?.dispose()
      resizeObserver?.disconnect()
      if (socket && socket.readyState <= WebSocket.OPEN) socket.close()
      wsRef.current = null
      terminalRef.current = null
      fitRef.current = null
      terminal?.dispose()
    }
  }, [fallbackOutput, fitTerminal, live, worker.id])

  useEffect(() => {
    fitTerminal()
  }, [fitTerminal, fullscreen])

  useEffect(() => {
    if (connection !== 'closed' || !worker.output || !terminalRef.current) return
    terminalRef.current.reset()
    terminalRef.current.write(worker.output)
  }, [connection, worker.output])

  return (
    <div
      className={cn(
        'flex flex-col bg-[#030303] overflow-hidden',
        fullscreen ? 'fixed inset-0 z-50 rounded-none' : 'rounded-b-xl border-t border-white/[0.05]'
      )}
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/[0.06] flex-shrink-0 bg-[#080808]">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] font-mono text-[#555555] truncate">{worker.name}</span>
          <span
            className={cn(
              'w-1.5 h-1.5 rounded-full flex-shrink-0',
              STATUS_COLOR[worker.status],
              worker.status === 'running' && connection === 'connected' && 'dot-pulse'
            )}
          />
          <span className="text-[9px] font-mono text-[#3a3a3a] truncate">{statusMessage}</span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={() => onCapture(worker.id)}
            className="p-1 text-[#444444] hover:text-[#888888] transition-colors rounded"
            aria-label="Refresh capture"
            title="Capture snapshot"
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
              title="Close terminal"
            >
              <X size={11} />
            </button>
          )}
        </div>
      </div>

      <div
        ref={containerRef}
        className={cn(
          'worker-xterm min-w-0 flex-1 overflow-hidden bg-[#030303]',
          fullscreen ? 'min-h-0' : 'h-48'
        )}
      />

      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-t border-white/[0.05] flex-shrink-0 bg-[#040404]">
        <span className="text-[9px] font-mono text-[#3a3a3a] truncate">
          {connection === 'connected' ? 'interactive tmux pty' : 'snapshot fallback available'}
        </span>
        <span className="text-[9px] font-mono text-[#2f2f2f] flex-shrink-0">{worker.host}</span>
      </div>
    </div>
  )
}
