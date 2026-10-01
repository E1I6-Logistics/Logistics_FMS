const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`
const API_BASE = (import.meta.env.VITE_FMS_API_BASE ?? DEFAULT_API_BASE).replace(/\/$/, '')

export type OrderItems = {
  A: number
  B: number
  C: number
  D: number
}

export type CreateOrderPayload = {
  robot_id: string
  items: OrderItems
  total_quantity: number
  workstation_node: '3' | '4'
}

export type CreateOrderResponse = {
  order_id: string
  robot_id: string
  items: OrderItems
  total_quantity: number
  pickup_nodes: string[]
  workstation_node: '3' | '4'
  status: string
  phase: string
  destination_node: string
}

export async function createOrder(payload: CreateOrderPayload) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch(`${API_BASE}/api/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })

    if (!response.ok) {
      const text = await response.text()
      const error = new Error(
        `${response.status} ${response.statusText}${text ? `: ${text}` : ''}`,
      )
      reportClientIssue('warning', 'order_create_failed', error, {
        robot_id: payload.robot_id,
        status: response.status,
      })
      throw error
    }

    return response.json() as Promise<CreateOrderResponse>
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      const timeoutError = new Error('주문 전송 시간이 초과되었습니다. FMS 연결을 확인하세요.')
      reportClientIssue('warning', 'order_create_timeout', timeoutError, {
        robot_id: payload.robot_id,
      })
      throw timeoutError
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}
import { reportClientIssue } from '../utils/clientLogger'
