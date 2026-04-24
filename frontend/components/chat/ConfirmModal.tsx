'use client'

import { AlertTriangle, X } from 'lucide-react'

interface ConfirmModalProps {
  title: string
  description: string
  confirmLabel?: string
  /**
   * When true, show the "this will create an audit event" footer. Should
   * match actual backend behaviour — only Sensitive/settings/context/worker
   * actions persist audit events. Defaults to false so we don't lie.
   */
  auditEvent?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmModal({
  title,
  description,
  confirmLabel = 'Confirm',
  auditEvent = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#0f0f0f] border border-white/[0.1] rounded-2xl p-5 w-[340px] max-w-[90vw] shadow-2xl flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <AlertTriangle size={15} style={{ color: 'var(--accent-pink)' }} />
            <span className="text-sm font-sans font-semibold text-white">{title}</span>
          </div>
          <button
            onClick={onCancel}
            className="text-[#555555] hover:text-white transition-colors p-0.5"
            aria-label="Cancel"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <p className="text-xs font-sans text-[#888888] leading-relaxed">{description}</p>

        {/* Audit note (only when backend actually emits one) */}
        {auditEvent && (
          <p className="text-[10px] font-mono text-[#444444] border-t border-white/[0.06] pt-3">
            This action will create an audit event.
          </p>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 rounded-lg border border-white/[0.08] text-xs font-sans text-[#888888] hover:text-white hover:border-white/20 transition-all"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 rounded-lg text-xs font-sans font-medium text-black transition-all"
            style={{ backgroundColor: 'var(--accent-pink)' }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
