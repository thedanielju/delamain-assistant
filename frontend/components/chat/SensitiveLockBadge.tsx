'use client'

import { Lock, Unlock } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  unlocked: boolean
  onToggle: () => void
}

export function SensitiveLockBadge({ unlocked, onToggle }: Props) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-mono transition-all flex-shrink-0',
        unlocked
          ? 'text-white border-current'
          : 'text-[#555555] border-[#2a2a2a] hover:text-[#888888] hover:border-[#444444]'
      )}
      style={
        unlocked
          ? {
              color: 'var(--accent-pink)',
              borderColor: 'var(--accent-pink)',
              backgroundColor: 'color-mix(in srgb, var(--accent-pink) 12%, transparent)',
            }
          : {}
      }
      aria-pressed={unlocked}
      title={unlocked ? 'Sensitive unlocked — click to lock' : 'Sensitive locked — click to unlock'}
    >
      {unlocked ? <Unlock size={9} /> : <Lock size={9} />}
      <span>{unlocked ? 'unlocked' : 'locked'}</span>
    </button>
  )
}
