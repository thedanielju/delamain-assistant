'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  FileText,
  RefreshCw,
  RotateCw,
  Trash2,
  UploadCloud,
  BookOpen,
  GraduationCap,
} from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { BackendUpload } from '@/lib/backend-types'
import type { UploadItem, UploadPreview, UploadPromotionCategory } from '@/lib/types'

function toUploadItem(upload: BackendUpload): UploadItem {
  return {
    id: upload.id,
    name: upload.filename ?? upload.original_filename ?? upload.name ?? upload.id,
    size: upload.size ?? upload.byte_count ?? null,
    contentType: upload.content_type ?? upload.mime_type ?? null,
    status: upload.status,
    previewStatus: upload.preview_status ?? null,
    conversionStatus: upload.conversion_status ?? null,
    createdAt: upload.created_at,
    updatedAt: upload.updated_at,
    expiresAt: upload.expires_at ?? null,
    errorMessage: upload.error_message ?? null,
    representation: upload.representation ?? null,
    category: upload.category ?? null,
    promotedPath: upload.promoted_path ?? null,
    metadata: upload.metadata,
  }
}

function toUploadPreview(raw: Awaited<ReturnType<typeof api.getUploadPreview>>): UploadPreview {
  return {
    uploadId: raw.upload_id,
    status: raw.status,
    filename: raw.filename,
    contentType: raw.content_type ?? null,
    size: raw.size ?? null,
    textPreview: raw.text_preview ?? null,
    markdownPreview: raw.markdown_preview ?? null,
    extractedText: raw.extracted_text ?? null,
    tokenEstimate: raw.token_estimate ?? null,
    pageCount: raw.page_count ?? null,
    metadata: raw.metadata,
    errorMessage: raw.error_message ?? null,
  }
}

function isBackendUpload(value: unknown): value is BackendUpload {
  return Boolean(
    value &&
      typeof value === 'object' &&
      typeof (value as { id?: unknown }).id === 'string' &&
      typeof (value as { status?: unknown }).status === 'string'
  )
}

function formatBytes(bytes: number | null) {
  if (bytes == null) return 'size unknown'
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function statusTone(status: string) {
  if (status === 'failed') return 'text-[var(--accent-pink)]'
  if (status === 'converted' || status === 'promoted' || status === 'preview_ready') {
    return 'text-[var(--accent-green)]'
  }
  if (status === 'expired') return 'text-[#555555]'
  return 'text-[var(--accent-blue)]'
}

function previewText(preview: UploadPreview | undefined) {
  return preview?.markdownPreview ?? preview?.textPreview ?? preview?.extractedText ?? null
}

export function UploadsPanel() {
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [previews, setPreviews] = useState<Record<string, UploadPreview>>({})
  const [loading, setLoading] = useState(false)
  const [busyIds, setBusyIds] = useState<Set<string>>(() => new Set())
  const [error, setError] = useState<string | null>(null)

  const pendingCount = useMemo(
    () => uploads.filter((upload) => !['promoted', 'expired'].includes(upload.status)).length,
    [uploads]
  )

  const setBusy = useCallback((id: string, busy: boolean) => {
    setBusyIds((prev) => {
      const next = new Set(prev)
      if (busy) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  const loadUploads = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await api.listUploads()
      const nextUploads = response.uploads.map(toUploadItem)
      setUploads(nextUploads)
      const previewPairs = await Promise.all(
        nextUploads.slice(0, 20).map(async (upload) => {
          try {
            const preview = await api.getUploadPreview(upload.id)
            return [upload.id, toUploadPreview(preview)] as const
          } catch {
            return null
          }
        })
      )
      setPreviews((prev) => {
        const next = { ...prev }
        for (const pair of previewPairs) {
          if (pair) next[pair[0]] = pair[1]
        }
        return next
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load uploads')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUploads()
  }, [loadUploads])

  const handleConvert = useCallback(
    async (id: string) => {
      setBusy(id, true)
      try {
        const updated = await api.convertUpload(id)
        setUploads((prev) => prev.map((item) => (item.id === id ? toUploadItem(updated) : item)))
        const preview = await api.getUploadPreview(id).catch(() => null)
        if (preview) setPreviews((prev) => ({ ...prev, [id]: toUploadPreview(preview) }))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Convert failed')
      } finally {
        setBusy(id, false)
      }
    },
    [setBusy]
  )

  const handlePromote = useCallback(
    async (id: string, category: UploadPromotionCategory) => {
      setBusy(id, true)
      try {
        const result = await api.promoteUpload(id, { category })
        const updated = isBackendUpload(result) ? result : result.upload
        if (updated) {
          setUploads((prev) => prev.map((item) => (item.id === id ? toUploadItem(updated) : item)))
        } else {
          await loadUploads()
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Promote failed')
      } finally {
        setBusy(id, false)
      }
    },
    [loadUploads, setBusy]
  )

  const handleDelete = useCallback(
    async (id: string) => {
      setBusy(id, true)
      try {
        await api.deleteUpload(id)
        setUploads((prev) => prev.filter((item) => item.id !== id))
        setPreviews((prev) => {
          const next = { ...prev }
          delete next[id]
          return next
        })
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Delete failed')
      } finally {
        setBusy(id, false)
      }
    },
    [setBusy]
  )

  const handleClear = useCallback(async () => {
    setLoading(true)
    try {
      const result = await api.clearUploads()
      if (result && typeof result === 'object' && 'uploads' in result) {
        setUploads(result.uploads.map(toUploadItem))
      } else {
        setUploads([])
      }
      setPreviews({})
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clear failed')
    } finally {
      setLoading(false)
    }
  }, [])

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-white/[0.05]">
        <div className="flex items-center gap-2 min-w-0">
          <UploadCloud size={13} className="text-[#555555] flex-shrink-0" />
          <span className="text-[10px] font-mono text-[#888888]">
            {pendingCount} pending
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={loadUploads}
            disabled={loading}
            className="p-1.5 rounded text-[#555555] hover:text-white disabled:opacity-40"
            aria-label="Refresh uploads"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={handleClear}
            disabled={loading || uploads.length === 0}
            className="px-2 py-1 rounded border border-white/[0.08] text-[10px] font-mono text-[#777777] hover:text-white hover:border-white/[0.16] disabled:opacity-40"
          >
            clear all
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-3 mt-3 rounded-md border border-[var(--accent-pink)]/25 bg-[var(--accent-pink)]/5 px-2 py-1.5 text-[10px] font-mono text-[var(--accent-pink)]">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {uploads.length === 0 && !loading && (
          <div className="rounded-md border border-white/[0.06] bg-[#0b0b0b] px-3 py-3 text-[10px] font-mono text-[#555555]">
            No uploads in intake.
          </div>
        )}

        {uploads.map((upload) => {
          const busy = busyIds.has(upload.id)
          const preview = previews[upload.id]
          const text = previewText(preview)
          return (
            <div
              key={upload.id}
              className="rounded-md border border-white/[0.06] bg-[#0b0b0b] px-2.5 py-2"
            >
              <div className="flex items-start gap-2">
                <FileText size={13} className="text-[#555555] mt-0.5 flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-mono text-[#cfcfcf]">{upload.name}</p>
                    <span className={cn('text-[9px] font-mono flex-shrink-0', statusTone(upload.status))}>
                      {upload.status}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[9px] font-mono text-[#444444]">
                    {formatBytes(upload.size)}
                    {upload.contentType ? ` · ${upload.contentType}` : ''}
                    {preview?.tokenEstimate ? ` · ~${preview.tokenEstimate} tok` : ''}
                    {preview?.pageCount ? ` · ${preview.pageCount}p` : ''}
                  </p>
                  {upload.errorMessage && (
                    <p className="mt-1 text-[10px] font-mono text-[var(--accent-pink)]">
                      {upload.errorMessage}
                    </p>
                  )}
                  {text && (
                    <p className="mt-1.5 max-h-20 overflow-hidden whitespace-pre-wrap text-[10px] leading-relaxed text-[#777777]">
                      {text}
                    </p>
                  )}
                  {upload.promotedPath && (
                    <p className="mt-1 text-[9px] font-mono text-[var(--accent-green)] truncate">
                      {upload.promotedPath}
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                <button
                  onClick={() => handleConvert(upload.id)}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded border border-white/[0.08] px-1.5 py-1 text-[9px] font-mono text-[#777777] hover:text-white hover:border-white/[0.16] disabled:opacity-40"
                >
                  <RotateCw size={10} />
                  convert
                </button>
                <button
                  onClick={() => handlePromote(upload.id, 'reference')}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded border border-white/[0.08] px-1.5 py-1 text-[9px] font-mono text-[#777777] hover:text-white hover:border-white/[0.16] disabled:opacity-40"
                >
                  <BookOpen size={10} />
                  reference
                </button>
                <button
                  onClick={() => handlePromote(upload.id, 'syllabi')}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded border border-white/[0.08] px-1.5 py-1 text-[9px] font-mono text-[#777777] hover:text-white hover:border-white/[0.16] disabled:opacity-40"
                >
                  <GraduationCap size={10} />
                  syllabi
                </button>
                <button
                  onClick={() => handleDelete(upload.id)}
                  disabled={busy}
                  className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-1 text-[9px] font-mono text-[#555555] hover:text-[var(--accent-pink)] disabled:opacity-40"
                  aria-label={`Delete ${upload.name}`}
                >
                  <Trash2 size={10} />
                  delete
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
