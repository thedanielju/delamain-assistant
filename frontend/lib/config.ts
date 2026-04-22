export const API_BASE =
  (process.env.NEXT_PUBLIC_DELAMAIN_API_BASE ?? '/api').replace(/\/$/, '')

export const MOCK_MODE = process.env.NEXT_PUBLIC_DELAMAIN_MOCK === '1'

export const HEALTH_PROBE_TIMEOUT_MS = 2500
export const SSE_RECONNECT_MIN_MS = 1000
export const SSE_RECONNECT_MAX_MS = 15000
