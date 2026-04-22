'use client'

import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ContextFile, ContextMode } from '@/lib/types'

const MODE_COLORS: Record<ContextMode, string> = {
  Normal:       'text-[#7ec8a0]',
  'Blank-slate': 'text-[#7eb8da]',
  Incognito:    'text-[#b8a0e8]',
}

interface ContextBannerProps {
  mode: ContextMode
  files: ContextFile[]
  onDismissFile: (id: string) => void
  onClickFile?: (file: ContextFile) => void
}

export function ContextBanner({ mode, files, onDismissFile, onClickFile }: ContextBannerProps) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-[#0a0a0a] border-b border-white/[0.06] overflow-x-auto min-h-[32px]">
      <span className={cn('text-[10px] font-mono font-medium flex-shrink-0', MODE_COLORS[mode])}>
        {mode}
      </span>
      <span className="text-[#333333] flex-shrink-0 text-[10px]">|</span>
      {files.length === 0 ? (
        <span className="text-[10px] font-mono text-[#555555]">No context files loaded</span>
      ) : (
        <div className="flex items-center gap-1.5 flex-nowrap">
          {files.map((file) => (
            <span
              key={file.id}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#111111] border border-white/[0.08] text-[10px] font-mono text-[#999999] flex-shrink-0"
            >
              <button
                onClick={() => onClickFile?.(file)}
                className="hover:underline transition-colors hover:text-white truncate max-w-[120px]"
                aria-label={`Open ${file.name}`}
                title={`Edit ${file.path}`}
              >
                {file.name}
              </button>
              <button
                onClick={() => onDismissFile(file.id)}
                className="text-[#555555] hover:text-white ml-0.5 transition-colors flex-shrink-0"
                aria-label={`Remove ${file.name} from context`}
              >
                <X size={9} />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
