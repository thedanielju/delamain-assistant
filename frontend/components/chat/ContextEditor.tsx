'use client'

import { useState, useEffect } from 'react'
import { X, Save, Eye, Code2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import type { ContextFile } from '@/lib/types'

interface ContextEditorProps {
  file: ContextFile
  initialContent: string
  onSave: (fileId: string, content: string) => void
  onClose: () => void
}

export function ContextEditor({ file, initialContent, onSave, onClose }: ContextEditorProps) {
  const [draft, setDraft] = useState(initialContent)
  const [mode, setMode] = useState<'edit' | 'preview'>('edit')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setDraft(initialContent)
    setDirty(false)
  }, [initialContent])

  const handleChange = (v: string) => {
    setDraft(v)
    setDirty(v !== initialContent)
  }

  const handleSave = () => {
    onSave(file.id, draft)
    setDirty(false)
  }

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-8"
      style={{ backgroundColor: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="flex flex-col w-full max-w-3xl max-h-[85vh] bg-[#0c0c0c] border border-white/[0.1] rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.07] flex-shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-[10px] font-mono text-[#555555] uppercase tracking-wider flex-shrink-0">
              Context
            </span>
            <span className="text-[10px] font-mono text-[#444444] flex-shrink-0">/</span>
            <span
              className="text-xs font-mono truncate"
              style={{ color: 'var(--accent-blue)' }}
            >
              {file.path}
            </span>
            {file.tokenEstimate && (
              <span className="text-[9px] font-mono text-[#3a3a3a] flex-shrink-0">
                ~{file.tokenEstimate} tokens
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0 ml-3">
            {/* Edit / Preview toggle */}
            <div className="flex items-center bg-[#141414] rounded-lg border border-white/[0.06] p-0.5">
              <button
                onClick={() => setMode('edit')}
                className={cn(
                  'flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-mono transition-all',
                  mode === 'edit'
                    ? 'bg-[#222222] text-[#cccccc]'
                    : 'text-[#555555] hover:text-[#888888]'
                )}
              >
                <Code2 size={10} />
                Edit
              </button>
              <button
                onClick={() => setMode('preview')}
                className={cn(
                  'flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-mono transition-all',
                  mode === 'preview'
                    ? 'bg-[#222222] text-[#cccccc]'
                    : 'text-[#555555] hover:text-[#888888]'
                )}
              >
                <Eye size={10} />
                Preview
              </button>
            </div>

            {/* Save */}
            <button
              onClick={handleSave}
              disabled={!dirty}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-mono border transition-all',
                dirty
                  ? 'text-black border-transparent hover:opacity-90'
                  : 'text-[#3a3a3a] border-white/[0.05] cursor-not-allowed'
              )}
              style={dirty ? { backgroundColor: 'var(--accent-blue)', borderColor: 'var(--accent-blue)' } : {}}
            >
              <Save size={10} />
              Save
            </button>

            <button
              onClick={onClose}
              className="text-[#555555] hover:text-white transition-colors p-1.5 rounded-lg"
              aria-label="Close editor"
            >
              <X size={13} />
            </button>
          </div>
        </div>

        {/* Editor / Preview body */}
        <div className="flex-1 overflow-hidden min-h-0">
          {mode === 'edit' ? (
            <textarea
              value={draft}
              onChange={(e) => handleChange(e.target.value)}
              className="w-full h-full bg-transparent text-[13px] font-mono text-[#cccccc] leading-relaxed outline-none resize-none px-5 py-4"
              spellCheck={false}
              placeholder="# Context file content..."
              aria-label="Edit context file"
            />
          ) : (
            <div className="h-full overflow-y-auto px-5 py-4 assistant-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {draft || '*Empty file*'}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* Dirty indicator */}
        {dirty && (
          <div className="flex items-center gap-1.5 px-4 py-2 border-t border-white/[0.04] bg-[#0a0a0a] flex-shrink-0">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: 'var(--accent-blue)' }}
            />
            <span className="text-[10px] font-mono text-[#555555]">Unsaved changes</span>
          </div>
        )}
      </div>
    </div>
  )
}
