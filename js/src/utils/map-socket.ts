/**
 * MapSocket — the map page's websocket to the server's map-event stream
 * (Django Channels, `brewgis/workspace/consumers.py`).
 *
 * The connection is kept open for the life of the page: when it drops, it
 * reconnects with exponential backoff (1s doubling up to 30s). Events
 * published while the socket was down are lost, so every reconnect after the
 * first open fires `onReconnected`, and the owner resyncs fully then.
 */

/** A map event as the server publishes it (`services/map_events.py`). */
export interface MapEvent {
  kind: string
  [key: string]: unknown
}

export interface MapSocketOptions {
  /** Called with every event the server sends. */
  onEvent: (event: MapEvent) => void
  /** Called when the socket opens again after having been closed. */
  onReconnected?: () => void
  /** First reconnect delay, in ms. */
  initialDelayMs?: number
  /** Longest reconnect delay, in ms. */
  maxDelayMs?: number
}

/** Close code the server uses to refuse a subscription; never retried. */
export const FORBIDDEN_CLOSE_CODE = 4403

/** Resolve a path (`/ws/...`) to a `ws:`/`wss:` URL on the page's own host. */
export function websocketUrl(path: string, loc: Location = window.location): string {
  if (/^wss?:\/\//.test(path)) return path
  const scheme = loc.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${loc.host}${path.startsWith('/') ? '' : '/'}${path}`
}

export class MapSocket {
  private readonly _url: string
  private readonly _options: Required<MapSocketOptions>
  private _socket: WebSocket | null = null
  private _delayMs: number
  private _retryTimer: ReturnType<typeof setTimeout> | null = null
  private _hasOpened = false
  private _closed = false

  constructor(url: string, options: MapSocketOptions) {
    this._url = websocketUrl(url)
    this._options = {
      onReconnected: () => undefined,
      initialDelayMs: 1000,
      maxDelayMs: 30000,
      ...options,
    }
    this._delayMs = this._options.initialDelayMs
  }

  /** Whether the socket is currently open. */
  get isOpen(): boolean {
    return this._socket?.readyState === WebSocket.OPEN
  }

  /** Open the socket (and keep it open until `close()`). */
  connect(): void {
    this._closed = false
    this._open()
  }

  /** Close the socket for good: no further reconnects. */
  close(): void {
    this._closed = true
    if (this._retryTimer !== null) {
      clearTimeout(this._retryTimer)
      this._retryTimer = null
    }
    this._socket?.close()
    this._socket = null
  }

  private _open(): void {
    const socket = new WebSocket(this._url)
    this._socket = socket

    socket.addEventListener('open', () => {
      this._delayMs = this._options.initialDelayMs
      if (this._hasOpened) this._options.onReconnected()
      this._hasOpened = true
    })

    socket.addEventListener('message', (e: MessageEvent) => {
      let event: unknown
      try {
        event = JSON.parse(String(e.data))
      } catch {
        console.warn('MapSocket: ignoring a non-JSON message', e.data)
        return
      }
      if (event && typeof event === 'object' && typeof (event as MapEvent).kind === 'string') {
        this._options.onEvent(event as MapEvent)
      }
    })

    socket.addEventListener('close', (e: CloseEvent) => {
      if (this._socket !== socket) return
      this._socket = null
      if (this._closed || e.code === FORBIDDEN_CLOSE_CODE) return
      this._scheduleReconnect()
    })
  }

  private _scheduleReconnect(): void {
    const delay = this._delayMs
    this._delayMs = Math.min(this._delayMs * 2, this._options.maxDelayMs)
    this._retryTimer = setTimeout(() => {
      this._retryTimer = null
      if (!this._closed) this._open()
    }, delay)
  }
}
