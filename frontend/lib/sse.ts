import { useEffect, useRef } from 'react'
import { sseUrl } from './api'
import { SSE_RECONNECT_MAX_MS, SSE_RECONNECT_MIN_MS } from './config'
import type { BackendSSEEvent } from './backend-types'

interface UseSSEOptions {
  path: string | null
  onEvent: (event: BackendSSEEvent) => void
  onError?: (err: Event) => void
  enabled?: boolean
}

export function useSSE({ path, onEvent, onError, enabled = true }: UseSSEOptions) {
  const lastEventIdRef = useRef<string | null>(null)
  const reconnectMsRef = useRef<number>(SSE_RECONNECT_MIN_MS)
  const sourceRef = useRef<EventSource | null>(null)
  const onEventRef = useRef(onEvent)
  const onErrorRef = useRef(onError)

  onEventRef.current = onEvent
  onErrorRef.current = onError

  useEffect(() => {
    if (!enabled || !path) return

    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      const url = sseUrl(path)
      const source = new EventSource(url, { withCredentials: true })
      sourceRef.current = source

      source.onopen = () => {
        reconnectMsRef.current = SSE_RECONNECT_MIN_MS
      }

      const handleEvent = (type: string) => (ev: MessageEvent) => {
        if (ev.lastEventId) lastEventIdRef.current = ev.lastEventId
        let payload: unknown = null
        try {
          payload = ev.data ? JSON.parse(ev.data) : null
        } catch {
          payload = ev.data
        }
        const event: BackendSSEEvent = {
          id: ev.lastEventId || undefined,
          type,
          payload: (payload && typeof payload === 'object' ? payload : { value: payload }) as Record<string, unknown>,
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
  }, [path, enabled])
}
