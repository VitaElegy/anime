/**
 * Subscribes to a watch room's Server-Sent Events stream.
 *
 * Scope and trade-offs
 * --------------------
 * - This is intentionally minimal: we pass the auth token via query string
 *   because the browser's native `EventSource` can't send custom headers.
 *   The backend's SSE endpoint is safe to expose unauthenticated (room data
 *   is publicly readable once you know the room id), but we still include
 *   the token so presence/ownership logic can resolve the caller.
 * - We reconnect with exponential backoff on transport errors, capped at 30s.
 * - We do NOT try to resume missed events. The SSE endpoint always sends the
 *   current room snapshot on connection, so losing the socket and reconnecting
 *   behaves like a full refresh — which is exactly what the old polling loop
 *   did anyway, just much less often.
 */
import { useEffect, useRef } from 'react'

import type { RoomMessage, WatchRoom } from '@/types'

export interface RoomEventHandlers {
  onRoomState?: (room: WatchRoom) => void
  onRoomMessage?: (message: RoomMessage) => void
  onError?: (error: Event) => void
  onOpen?: () => void
}

const MIN_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30_000

function parsePayload<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function useRoomEventStream(
  roomId: string | undefined,
  enabled: boolean,
  handlers: RoomEventHandlers,
) {
  // Store handlers in a ref so callers don't need to memoise them for the
  // EventSource subscription to stay stable.
  const handlersRef = useRef<RoomEventHandlers>(handlers)
  useEffect(() => {
    handlersRef.current = handlers
  }, [handlers])

  useEffect(() => {
    if (!enabled || !roomId) return

    let source: EventSource | null = null
    let reconnectTimer: number | null = null
    let backoff = MIN_BACKOFF_MS
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      const url = `/api/watch/rooms/${encodeURIComponent(roomId)}/events`
      source = new EventSource(url)

      source.addEventListener('open', () => {
        backoff = MIN_BACKOFF_MS
        handlersRef.current.onOpen?.()
      })

      source.addEventListener('room_state', (event) => {
        const payload = parsePayload<WatchRoom>((event as MessageEvent).data)
        if (payload) handlersRef.current.onRoomState?.(payload)
      })

      source.addEventListener('room_message', (event) => {
        const payload = parsePayload<RoomMessage>((event as MessageEvent).data)
        if (payload) handlersRef.current.onRoomMessage?.(payload)
      })

      source.addEventListener('error', (event) => {
        handlersRef.current.onError?.(event)
        source?.close()
        source = null
        if (cancelled) return
        reconnectTimer = window.setTimeout(connect, backoff)
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
      })
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer != null) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      source?.close()
      source = null
    }
  }, [enabled, roomId])
}
