import { wsUrl } from './http'

export type StreamEventType =
  | 'stage_start'
  | 'stage_end'
  | 'thinking'
  | 'observation'
  | 'content'
  | 'tool_call'
  | 'tool_result'
  | 'progress'
  | 'sources'
  | 'result'
  | 'error'
  | 'session'
  | 'session_meta'
  | 'done'

export interface StreamEvent {
  type: StreamEventType
  source: string
  stage: string
  content: string
  metadata: Record<string, unknown>
  session_id?: string
  turn_id?: string
  seq?: number
  timestamp: number
}

export interface StartTurnMessage {
  type: 'message' | 'start_turn'
  content: string
  tools?: string[]
  capability?: string | null
  session_id?: string | null
  attachments?: {
    type: string
    url?: string
    base64?: string
    filename?: string
    mime_type?: string
  }[]
  language?: string
  config?: Record<string, unknown>
}

export interface SubscribeSessionMessage {
  type: 'subscribe_session'
  session_id: string
  after_seq?: number
}

export interface ResumeTurnMessage {
  type: 'resume_from'
  turn_id: string
  seq?: number
}

export interface CancelTurnMessage {
  type: 'cancel_turn'
  turn_id: string
}

export type ClientMessage =
  | StartTurnMessage
  | SubscribeSessionMessage
  | ResumeTurnMessage
  | CancelTurnMessage

export type EventHandler = (event: StreamEvent) => void

const HEARTBEAT_INTERVAL_MS = 30_000
const HEARTBEAT_TIMEOUT_MS = 45_000
const MAX_RECONNECT_ATTEMPTS = 5
const BASE_RECONNECT_DELAY_MS = 200

export class UnifiedWSClient {
  private ws: WebSocket | null = null
  private onEvent: EventHandler
  private onClose?: () => void
  private onOpen?: () => void

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private lastReceivedAt = 0

  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false

  private activeTurnId: string | null = null
  private lastSeq = 0
  private pending: ClientMessage[] = []

  constructor(onEvent: EventHandler, onClose?: () => void, onOpen?: () => void) {
    this.onEvent = onEvent
    this.onClose = onClose
    this.onOpen = onOpen
  }

  setResumeState(turnId: string | null, seq: number): void {
    this.activeTurnId = turnId
    this.lastSeq = seq
  }

  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return
    this.intentionalClose = false

    this.ws = new WebSocket(wsUrl('/api/v1/ws'))

    this.ws.onopen = () => {
      this.reconnectAttempt = 0
      this.lastReceivedAt = Date.now()
      this.startHeartbeat()
      this.onOpen?.()
      for (const msg of this.pending) {
        this.ws?.send(JSON.stringify(msg))
      }
      this.pending = []
      if (this.activeTurnId) {
        this.send({
          type: 'resume_from',
          turn_id: this.activeTurnId,
          seq: this.lastSeq,
        })
      }
    }

    this.ws.onmessage = (ev) => {
      this.lastReceivedAt = Date.now()
      try {
        const event = JSON.parse(ev.data) as StreamEvent
        const type = (event as { type?: string }).type
        if (type === 'ping' || type === 'pong') return
        if (event.turn_id) this.activeTurnId = event.turn_id
        if (event.seq != null) this.lastSeq = Math.max(this.lastSeq, event.seq)
        this.onEvent(event)
      } catch {
        console.warn('Unparseable WS message:', ev.data)
      }
    }

    this.ws.onclose = () => {
      this.ws = null
      this.stopHeartbeat()
      if (!this.intentionalClose) this.attemptReconnect()
    }

    this.ws.onerror = (err) => {
      console.error('WS error:', err)
    }
  }

  send(msg: ClientMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push(msg)
      if (!this.ws) this.connect()
      return true
    }
    this.ws.send(JSON.stringify(msg))
    return true
  }

  disconnect(): void {
    this.intentionalClose = true
    this.stopHeartbeat()
    this.clearReconnectTimer()
    this.ws?.close()
    this.ws = null
    this.resetResumeState()
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      if (Date.now() - this.lastReceivedAt > HEARTBEAT_TIMEOUT_MS) {
        this.ws.close()
        return
      }
      try {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      } catch {
        /* ignore */
      }
    }, HEARTBEAT_INTERVAL_MS)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      this.resetResumeState()
      this.onClose?.()
      return
    }
    const delay = BASE_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt
    this.reconnectAttempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private resetResumeState(): void {
    this.activeTurnId = null
    this.lastSeq = 0
    this.reconnectAttempt = 0
  }
}
