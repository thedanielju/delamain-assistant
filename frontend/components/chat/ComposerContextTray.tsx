'use client'

import { FileText, Pin, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { VaultContextItem } from '@/lib/types'

interface ComposerContextTrayProps {
  items: VaultContextItem[]
  onRemove: (path: string) => void
  onOpenVault?: () => void
}

export function ComposerContextTray({ items, onRemove, onOpenVault }: ComposerContextTrayProps) {
  if (!items.length) return null

  return (
    <div className="border-t border-white/[0.05] bg-[#070707] px-3 py-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onOpenVault}
          className={cn(
            'flex items-center gap-1.5 text-[10px] font-mono text-[#666666] flex-shrink-0',
            onOpenVault && 'hover:text-[var(--accent-blue)] transition-colors'
          )}
          disabled={!onOpenVault}
          title="Open vault panel"
        >
          <Pin size={11} style={{ color: 'var(--accent-blue)' }} />
          context
        </button>
        <div className="min-w-0 flex-1 flex items-center gap-1.5 overflow-x-auto scrollbar-none">
          {items.map((item) => (
            <span
              key={item.path}
              className={cn(
                'group inline-flex max-w-[260px] items-center gap-1.5 rounded-md border px-2 py-1',
                'border-white/[0.08] bg-[#101010] text-[10px] font-mono text-[#aaaaaa]',
                item.pinned === false && 'border-white/[0.05] text-[#666666]',
                item.excluded && 'border-[var(--accent-pink)]/30 text-[var(--accent-pink)]'
              )}
              title={`${item.pinned === false ? 'Suggested context, not submitted\n' : ''}${item.path}${item.preview ? `\n\n${item.preview}` : ''}`}
            >
              {item.pinned === false ? (
                <FileText size={10} className="flex-shrink-0 text-[#444444]" />
              ) : (
                <Pin size={10} className="flex-shrink-0 text-[var(--accent-blue)]" />
              )}
              <span className="truncate">{item.title || item.path}</span>
              {item.pinned === false && <span className="text-[#444444]">suggested</span>}
              {typeof item.tokenEstimate === 'number' && (
                <span className="text-[#444444]">{item.tokenEstimate}t</span>
              )}
              <button
                type="button"
                onClick={() => onRemove(item.path)}
                className="text-[#555555] hover:text-white transition-colors"
                aria-label={`Remove ${item.title || item.path} from context`}
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
