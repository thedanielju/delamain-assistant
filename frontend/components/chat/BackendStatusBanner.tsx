'use client'

import type { BackendConnection } from '@/hooks/useDelamainBackend'
import { AlertTriangle, Loader2, Wifi } from 'lucide-react'

interface Props {
  connection: BackendConnection
  authRedirectUrl?: string | null
}

export function BackendStatusBanner({ connection, authRedirectUrl }: Props) {
  if (connection === 'connected') return null

  const meta = {
    probing: {
      text: 'Probing backend…',
      icon: <Loader2 size={10} className="animate-spin" />,
      color: 'var(--accent-blue)',
    },
    offline: {
      text: 'Backend unreachable — using local sample data',
      icon: <AlertTriangle size={10} />,
      color: 'var(--accent-pink)',
    },
    auth_required: {
      text: authRedirectUrl
        ? 'Authentication required — sign in to continue'
        : 'Authentication required — refresh after Cloudflare Access login',
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
          className="px-2 py-0.5 rounded border border-current text-[10px] font-mono"
        >
          Sign in
        </button>
      ) : null}
    </div>
  )
}
