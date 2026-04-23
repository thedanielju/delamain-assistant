import { useEffect, useRef } from 'react'
import { sseUrl } from './api'
import { SSE_RECONNECT_MAX_MS, SSE_RECONNECT_MIN_MS } from './config'
import type { BackendSSEEvent } from './backend-types'

interface UseSSEOptions {
  path: string | null
  onEvent: (event: BackendSSEEvent) => void
  onError?: (err: Event) => void
  enabled?: boolean
  /**
   * Key under which the latest event id is persisted in localStorage so the
   * stream can replay missed events after a full reload. Usually the
   * conversation or run id.
   */
  resumeKey?: string | null
}

const LS_PREFIX = 'delamain:sse:last-event-id:'

function loadLastEventId(key: string | null | undefined): string | null {
  if (!key || typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(LS_PREFIX + key)
  } catch {
    return null
  }
}

function saveLastEventId(key: string | null | undefined, id: string): void {
  if (!key || typeof window === 'undefined') return
  try {
    window.localStorage.setItem(LS_PREFIX + key, id)
  } catch {
    /* no-op */
  }
}

export function useSSE({ path, onEvent, onError, enabled = true, resumeKey }: UseSSEOptions) {
  const lastEventIdRef = useRef<string | null>(null)
  const reconnectMsRef = useRef<number>(SSE_RECONNECT_MIN_MS)
  const sourceRef = useRef<EventSource | null>(null)
  const onEventRef = useRef(onEvent)
  const onErrorRef = useRef(onError)

  onEventRef.current = onEvent
  onErrorRef.current = onError

  useEffect(() => {
    if (!enabled || !path) return

    lastEventIdRef.current = loadLastEventId(resumeKey)

    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      const last = lastEventIdRef.current
      const url = last
        ? `${sseUrl(path)}?last_event_id=${encodeURIComponent(last)}`
        : sseUrl(path)
      const source = new EventSource(url, { withCredentials: true })
      sourceRef.current = source

      source.onopen = () => {
        reconnectMsRef.current = SSE_RECONNECT_MIN_MS
      }

      const handleEvent = (type: string) => (ev: MessageEvent) => {
        if (ev.lastEventId) {
          lastEventIdRef.current = ev.lastEventId
          saveLastEventId(resumeKey, ev.lastEventId)
        }
        let payload: unknown = null
        try {
          payload = ev.data ? JSON.parse(ev.data) : null
        } catch {
          payload = ev.data
        }
        const raw = (payload && typeof payload === 'object'
          ? payload
          : { value: payload }) as Record<string, unknown>
        const inner =
          raw.payload && typeof raw.payload === 'object'
            ? (raw.payload as Record<string, unknown>)
            : raw
        const event: BackendSSEEvent = {
          id: ev.lastEventId || undefined,
          type,
          payload: inner,
        }
        onEventRef.current(event)
      }

      const registered: string[] = [
        'run.queued',
        'run.started',
        'context.loaded',
        'message.delta',
        'message.completed',
        'tool.started',
        'tool.output',
        'tool.finished',
        'model.usage',
        'audit',
        'error',
        'run.completed',
        'permission.requested',
        'permission.resolved',
        'conversation.title',
      ]
      for (const t of registered) {
        source.addEventListener(t, handleEvent(t) as EventListener)
      }
      source.onmessage = handleEvent('message')

      source.onerror = (err) => {
        onErrorRef.current?.(err)
        source.close()
        sourceRef.current = null
        if (cancelled) return
        const delay = reconnectMsRef.current
        reconnectMsRef.current = Math.min(delay * 2, SSE_RECONNECT_MAX_MS)
        reconnectTimer = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      sourceRef.current?.close()
      sourceRef.current = null
    }
  }, [path, enabled, resumeKey])
}
