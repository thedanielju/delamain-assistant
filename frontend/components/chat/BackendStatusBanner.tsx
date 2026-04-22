'use client'

import type { BackendConnection } from '@/hooks/useDelamainBackend'
import { AlertTriangle, Loader2, Wifi } from 'lucide-react'

interface Props {
  connection: BackendConnection
}

export function BackendStatusBanner({ connection }: Props) {
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
    </div>
  )
}
