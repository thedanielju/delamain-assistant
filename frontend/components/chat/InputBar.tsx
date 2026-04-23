'use client'

import { useRef, useState, useCallback } from 'react'
import { Send, Lock, Paperclip, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DirectActionsBar } from './DirectActionsBar'
import type { DirectAction } from '@/lib/types'

function TogglePill({
  label,
  active,
  accentColor,
  icon,
  onClick,
}: {
  label: string
  active: boolean
  accentColor: string
  icon?: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[10px] font-mono transition-all flex-shrink-0',
        active
          ? 'text-white border-current'
          : 'text-[#555555] border-[#333333] hover:border-[#555555] hover:text-[#888888]'
      )}
      style={
        active
          ? { color: accentColor, borderColor: accentColor, backgroundColor: `${accentColor}18` }
          : {}
      }
      aria-pressed={active}
    >
      {icon}
      {label}
    </button>
  )
}

interface AttachedFile {
  id: string
  name: string
  size: number
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

interface InputBarProps {
  onSend: (message: string, attachments?: AttachedFile[]) => void
  blankSlate: boolean
  incognito: boolean
  sensitive: boolean
  directActions?: DirectAction[]
  onToggleBlankSlate: () => void
  onToggleIncognito: () => void
  onToggleSensitive: () => void
  onRunDirectAction: (actionId: string) => void
  conversationId?: string
}

export function InputBar({
  onSend,
  blankSlate,
  incognito,
  sensitive,
  directActions,
  onToggleBlankSlate,
  onToggleIncognito,
  onToggleSensitive,
  onRunDirectAction,
  conversationId,
}: InputBarProps) {
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<AttachedFile[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [])

  const addFiles = useCallback((fileList: FileList | null) => {
    if (!fileList) return
    const next: AttachedFile[] = Array.from(fileList).map((f) => ({
      id: Math.random().toString(36).slice(2),
      name: f.name,
      size: f.size,
    }))
    setAttachments((prev) => [...prev, ...next])
  }, [])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      addFiles(e.target.files)
      if (fileInputRef.current) fileInputRef.current.value = ''
    },
    [addFiles]
  )

  // ── Drag-and-drop handlers ──────────────────────────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // Only clear if leaving the outer container (not entering a child)
    if (e.currentTarget.contains(e.relatedTarget as Node)) return
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragOver(false)
      addFiles(e.dataTransfer.files)
      // Focus textarea after drop
      textareaRef.current?.focus()
    },
    [addFiles]
  )

  const handleSend = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed) return
    onSend(trimmed, attachments)
    setValue('')
    setAttachments([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [value, attachments, onSend])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const canSend = value.trim().length > 0

  return (
    <div
      className={cn(
        'flex-shrink-0 bg-[#080808] border-t border-white/[0.05] px-3 pt-2 pb-3 transition-colors',
        isDragOver && 'bg-[#0d0d0d]'
      )}
      style={{ position: 'relative', overflow: 'visible' }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drag-over overlay */}
      {isDragOver && (
        <div className="absolute inset-0 z-[5] flex items-center justify-center rounded-xl border-2 border-dashed pointer-events-none"
          style={{ borderColor: 'var(--accent-blue)', backgroundColor: 'color-mix(in srgb, var(--accent-blue) 5%, transparent)' }}>
          <div className="flex flex-col items-center gap-1.5">
            <Paperclip size={18} style={{ color: 'var(--accent-blue)' }} />
            <p className="text-xs font-mono" style={{ color: 'var(--accent-blue)' }}>
              Drop files to attach
            </p>
          </div>
        </div>
      )}

      {/* Quick action pills — two rows so the flyup is never clipped by overflow */}
      <div className="flex items-center gap-1.5 mb-1.5">
        {/* Scrollable model-routed toggles */}
        <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-none flex-shrink min-w-0">
          <TogglePill
            label="Blank-slate"
            active={blankSlate}
            accentColor="var(--accent-blue)"
            onClick={onToggleBlankSlate}
          />
          <TogglePill
            label="Incognito"
            active={incognito}
            accentColor="var(--accent-purple)"
            onClick={onToggleIncognito}
          />
          <TogglePill
            label="Sensitive"
            active={sensitive}
            accentColor="var(--accent-pink)"
            icon={<Lock size={9} />}
            onClick={onToggleSensitive}
          />
        </div>

        {/* Separator + DirectActionsBar — outside the overflow-x container */}
        <span className="w-px h-4 bg-white/[0.08] flex-shrink-0" aria-hidden="true" />
        <DirectActionsBar
          actions={directActions}
          onRun={onRunDirectAction}
          conversationId={conversationId}
        />
      </div>

      {/* Attachment chips */}
      {attachments.length > 0 && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          {attachments.map((a) => (
            <span
              key={a.id}
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#141414] border border-white/[0.08] text-[10px] font-mono text-[#888888]"
            >
              <Paperclip size={9} />
              <span className="truncate max-w-[120px]">{a.name}</span>
              <span className="text-[#444444]">{formatBytes(a.size)}</span>
              <button
                onClick={() => removeAttachment(a.id)}
                className="text-[#555555] hover:text-white transition-colors ml-0.5"
                aria-label={`Remove ${a.name}`}
              >
                <X size={9} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input row */}
      <div
        className={cn(
          'flex items-end gap-1.5 bg-[#111111] border rounded-xl px-2.5 py-2 transition-colors',
          isDragOver ? 'border-[var(--accent-blue)]/50' : 'border-white/[0.08]'
        )}
      >
        {/* File attach button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex-shrink-0 flex items-center justify-center w-7 h-7 rounded-lg text-[#555555] hover:text-[#888888] transition-colors"
          aria-label="Attach file"
          title="Attach file (or drag & drop)"
        >
          <Paperclip size={13} />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileChange}
          aria-hidden="true"
        />

        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Message Delamain..."
          rows={1}
          className="flex-1 bg-transparent text-sm text-white placeholder-[#444444] outline-none resize-none font-sans leading-relaxed min-h-[22px] max-h-[200px] overflow-y-auto"
          aria-label="Message input"
        />

        <button
          onClick={handleSend}
          disabled={!canSend}
          className={cn(
            'flex-shrink-0 flex items-center justify-center w-7 h-7 rounded-lg transition-all',
            canSend ? 'hover:opacity-90 text-black' : 'bg-[#1a1a1a] text-[#3a3a3a] cursor-not-allowed'
          )}
          style={canSend ? { backgroundColor: 'var(--accent-blue)' } : {}}
          aria-label="Send message"
        >
          <Send size={13} />
        </button>
      </div>

      {!isDragOver && (
        <p className="text-[9px] font-mono text-[#2a2a2a] mt-1.5 text-center">
          Shift+Enter for new line &middot; drag files to attach
        </p>
      )}
    </div>
  )
}
