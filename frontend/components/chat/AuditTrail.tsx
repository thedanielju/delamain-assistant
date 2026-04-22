'use client'

import { ShieldAlert, ShieldCheck, Shield } from 'lucide-react'
import type { AuditEntry } from '@/hooks/useDelamainBackend'

interface Props {
  entries: AuditEntry[]
  conversationId: string
}

function pickIcon(event: string) {
  if (event.includes('denied') || event === 'error') return ShieldAlert
  if (event.includes('unlock') || event.includes('allowed')) return ShieldCheck
  return Shield
}

function pickColor(event: string) {
  if (event.includes('denied') || event === 'error') return 'var(--accent-pink)'
  if (event.includes('unlock') || event.includes('allowed')) return 'var(--accent-green)'
  if (event.includes('lock')) return 'var(--accent-purple)'
  return '#888888'
}

function fmtTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString()
  } catch {
    return iso
  }
}

export function AuditTrail({ entries, conversationId }: Props) {
  const filtered = entries.filter((e) => e.conversationId === conversationId)
  if (filtered.length === 0) return null

  return (
    <div className="mx-3 my-2 rounded-lg border border-white/[0.06] bg-[#0b0b0b]">
      <div className="px-3 py-1.5 text-[9px] font-mono text-[#555555] uppercase tracking-wider border-b border-white/[0.05]">
        Audit
      </div>
      <ul className="divide-y divide-white/[0.04]">
        {filtered.slice(-8).map((entry) => {
          const Icon = pickIcon(entry.event)
          const color = pickColor(entry.event)
          return (
            <li key={entry.id} className="flex items-center gap-2 px-3 py-1.5">
              <Icon size={10} style={{ color }} className="flex-shrink-0" />
              <span className="text-[10px] font-mono text-white truncate">{entry.event}</span>
              {entry.detail && (
                <span className="text-[10px] font-mono text-[#555555] truncate flex-1">
                  {entry.detail}
                </span>
              )}
              <span className="text-[9px] font-mono text-[#333333] flex-shrink-0 ml-auto">
                {fmtTime(entry.timestamp)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
