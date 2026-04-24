'use client'

import type { BackendConnection } from '@/hooks/useDelamainBackend'
import { AlertTriangle, Loader2, RefreshCw, Wifi } from 'lucide-react'

interface Props {
  connection: BackendConnection
  authRedirectUrl?: string | null
  onRetry?: () => void
}

export function BackendStatusBanner({ connection, authRedirectUrl, onRetry }: Props) {
  if (connection === 'connected') return null

  const meta = {
    probing: {
      text: 'Probing backend…',
      icon: <Loader2 size={10} className="animate-spin" />,
      color: 'var(--accent-blue)',
    },
    offline: {
      text: 'Backend unreachable — retrying every 5s',
      icon: <AlertTriangle size={10} />,
      color: 'var(--accent-pink)',
    },
    auth_required: {
      text: authRedirectUrl
        ? 'Authentication required — sign in to continue'
        : 'Authentication required — Cloudflare Access session expired',
      icon: <AlertTriangle size={10} />,
      color: 'var(--accent-purple)',
    },
    mock: {
      text: 'Mock mode — no backend calls',
      icon: <Wifi size={10} />,
      color: 'var(--accent-purple)',
    },
  }[connection]

  return (
    <div
      className="flex-shrink-0 flex items-center justify-center gap-2 px-3 py-1 text-[10px] font-mono border-b border-white/[0.06]"
      style={{ backgroundColor: `color-mix(in srgb, ${meta.color} 8%, transparent)`, color: meta.color }}
    >
      {meta.icon}
      <span>{meta.text}</span>
      {connection === 'auth_required' && authRedirectUrl ? (
        <button
          onClick={() => {
            window.location.href = authRedirectUrl
          }}
          className="px-2 py-0.5 rounded border border-current text-[10px] font-mono hover:bg-current/10"
        >
          Sign in
        </button>
      ) : null}
      {connection === 'auth_required' && !authRedirectUrl ? (
        <button
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-current text-[10px] font-mono hover:bg-current/10"
        >
          <RefreshCw size={9} />
          Reload
        </button>
      ) : null}
      {connection === 'offline' && onRetry ? (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-current text-[10px] font-mono hover:bg-current/10"
        >
          <RefreshCw size={9} />
          Retry now
        </button>
      ) : null}
    </div>
  )
}
