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
}

export async function createOrder(payload: CreateOrderPayload) {
  const response = await fetch(`${API_BASE}/api/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(
      `${response.status} ${response.statusText}${text ? `: ${text}` : ''}`,
    )
  }

  return response.json() as Promise<CreateOrderResponse>
}
