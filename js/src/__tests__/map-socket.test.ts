import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MapSocket, websocketUrl, FORBIDDEN_CLOSE_CODE } from '../utils/map-socket.js'

/** A WebSocket stand-in the tests open, message and close by hand. */
class FakeWebSocket extends EventTarget {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  readyState = 0
  constructor(public url: string) {
    super()
    FakeWebSocket.instances.push(this)
  }
  open() {
    this.readyState = FakeWebSocket.OPEN
    this.dispatchEvent(new Event('open'))
  }
  message(data: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
  drop(code = 1006) {
    this.readyState = 3
    const event = new Event('close') as Event & { code: number }
    event.code = code
    this.dispatchEvent(event)
  }
  close = vi.fn(() => this.drop(1000))
}

describe('websocketUrl', () => {
  it('maps the page scheme to ws/wss on the same host', () => {
    expect(
      websocketUrl('/ws/workspace/1/map/', { protocol: 'http:', host: 'h:8000' } as Location),
    ).toBe('ws://h:8000/ws/workspace/1/map/')
    expect(websocketUrl('/ws/x/', { protocol: 'https:', host: 'h' } as Location)).toBe(
      'wss://h/ws/x/',
    )
  })

  it('leaves an absolute ws URL alone', () => {
    expect(websocketUrl('wss://other/ws/x/')).toBe('wss://other/ws/x/')
  })
})

describe('MapSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('delivers JSON events that carry a kind, and ignores anything else', () => {
    const onEvent = vi.fn()
    new MapSocket('/ws/x/', { onEvent }).connect()
    const ws = FakeWebSocket.instances[0]
    ws.open()
    ws.message({ kind: 'layers.changed' })
    ws.message({ nope: true })
    ws.dispatchEvent(new MessageEvent('message', { data: 'not json' }))
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenCalledWith({ kind: 'layers.changed' })
  })

  it('reconnects with doubling backoff and reports the reconnect', () => {
    const onReconnected = vi.fn()
    new MapSocket('/ws/x/', { onEvent: vi.fn(), onReconnected }).connect()
    FakeWebSocket.instances[0].open()
    expect(onReconnected).not.toHaveBeenCalled()

    FakeWebSocket.instances[0].drop()
    vi.advanceTimersByTime(999)
    expect(FakeWebSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(2)

    // Still down: the next attempt waits twice as long.
    FakeWebSocket.instances[1].drop()
    vi.advanceTimersByTime(1999)
    expect(FakeWebSocket.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(3)

    FakeWebSocket.instances[2].open()
    expect(onReconnected).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect after close() or a refused subscription', () => {
    const socket = new MapSocket('/ws/x/', { onEvent: vi.fn() })
    socket.connect()
    socket.close()
    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(1)

    new MapSocket('/ws/y/', { onEvent: vi.fn() }).connect()
    FakeWebSocket.instances[1].drop(FORBIDDEN_CLOSE_CODE)
    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })
})
