import { G0_EVENT_TYPES, type G0EventType } from './types'

export interface EventStreamHandlers {
  onOpen(): void
  onEvent(eventType: G0EventType, rawData: string, lastEventId: string): void
  onError(): void
}

export interface EventStreamConnection {
  close(): void
}

export type EventSourceFactory = (
  url: string,
  handlers: EventStreamHandlers,
) => EventStreamConnection

export const browserEventSourceFactory: EventSourceFactory = (url, handlers) => {
  const source = new EventSource(url)
  source.addEventListener('open', () => handlers.onOpen())
  for (const eventType of G0_EVENT_TYPES) {
    source.addEventListener(eventType, (event) => {
      const message = event as MessageEvent<string>
      handlers.onEvent(eventType, message.data, message.lastEventId)
    })
  }
  source.onerror = () => handlers.onError()
  return { close: () => source.close() }
}

export function buildEventStreamUrl(
  eventsUrl: string,
  afterEventSeq: number,
  afterOffset: number,
): string {
  const url = new URL(eventsUrl, window.location.origin)
  url.searchParams.set('after_event_seq', String(afterEventSeq))
  url.searchParams.set('after_offset', String(afterOffset))
  return `${url.pathname}${url.search}`
}
