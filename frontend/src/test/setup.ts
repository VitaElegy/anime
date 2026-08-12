import '@testing-library/jest-dom/vitest'

/**
 * Minimal EventSource mock for jsdom.
 *
 * The watch-room pages subscribe to SSE via `useRoomEventStream`. jsdom does
 * not ship EventSource, so tests that render those pages need this stub.
 * Tests that need to simulate a pushed event can use
 * `MockEventSource.instances` to dispatch `room_state` / `room_message`.
 */
class MockEventSource {
  static instances: MockEventSource[] = []

  url: string
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null

  private listeners: Record<string, Array<(event: Event) => void>> = {}

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    ;(this.listeners[type] ||= []).push(listener)
  }

  removeEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== listener)
  }

  dispatch(type: string, data?: unknown): void {
    const event = {
      type,
      data: data === undefined ? undefined : JSON.stringify(data),
    } as MessageEvent
    for (const listener of this.listeners[type] || []) listener(event)
    if (type === 'open') this.onopen?.(event as unknown as Event)
    if (type === 'error') this.onerror?.(event as unknown as Event)
    if (type === 'message') this.onmessage?.(event)
  }

  close(): void {
    this.readyState = 2
  }
}

globalThis.EventSource = MockEventSource as unknown as typeof EventSource
