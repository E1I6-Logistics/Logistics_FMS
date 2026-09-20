const defaultApi = new URL(window.location.href)
defaultApi.port = '8000'
const API_BASE = (import.meta.env.VITE_FMS_API_BASE ?? defaultApi.origin).replace(/\/$/, '')

function wsBaseFromHttp(base: string) {
  if (base.startsWith('https://')) return `wss://${base.slice('https://'.length)}`
  if (base.startsWith('http://')) return `ws://${base.slice('http://'.length)}`
  return base
}

export const WS_BASE = (import.meta.env.VITE_FMS_WS_BASE ?? wsBaseFromHttp(API_BASE)).replace(/\/$/, '')

export type RouteNodeDto = {
  id: string | number
  x: number
  y: number
  frame?: string
  pixel_x?: number
  pixel_y?: number
  properties?: Record<string, unknown>
}

export type GeoJsonFeature = {
  type: 'Feature'
  geometry?: {
    type?: string
    coordinates?: unknown
  } | null
  properties?: Record<string, unknown> | null
}

export type GeoJsonFeatureCollection = {
  type: 'FeatureCollection'
  name?: string
  features: GeoJsonFeature[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`${response.status} ${response.statusText}${text ? `: ${text}` : ''}`)
  }
  return response.json() as Promise<T>
}

export function getRouteNodes() {
  return request<RouteNodeDto[]>('/api/route/nodes?include_pixel=true')
}

export function getRouteGraph() {
  return request<GeoJsonFeatureCollection>('/api/route/graph?raw=true')
}

export function sendGoalNode(robotId: string, nodeId: string | number) {
  return request<Record<string, unknown>>('/api/command/goal-node', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId, node_id: nodeId }),
  })
}

export function stopRobot(robotId: string) {
  return request<Record<string, unknown>>('/api/command/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId }),
  })
}

export function cmdVelWsUrl() {
  return `${WS_BASE}/ws/cmd_vel`
}

export type ConnectionDeviceDto = {
  ip: string
  name: string
  known: boolean
  connected: boolean
  blocked: boolean
  state: 'CONNECTED' | 'OFFLINE' | 'BLOCKED' | string
}

export type RobotRoute = {
  node_ids: string[]
  edge_ids: string[]
  phase: 'ready' | 'moving'
  segment_index: number
}

export type RobotStateDto = {
  robot_id: string
  ui_id?: string
  status: string
  battery: number
  x: number
  y: number
  yaw: number
  updated_at?: string | null
  mode: 'real' | 'simulation'
  route?: RobotRoute | null
}

export function getConnections() {
  return request<{ devices: ConnectionDeviceDto[] }>('/api/connections')
}

export function allowConnection(ip: string) {
  return request<{ status: string; ip: string; devices: ConnectionDeviceDto[] }>('/api/connections/allow', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip }),
  })
}

export function blockConnection(ip: string) {
  return request<{ status: string; ip: string; devices: ConnectionDeviceDto[] }>('/api/connections/block', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip }),
  })
}

export function getRobots() {
  return request<RobotStateDto[]>('/api/robots')
}

export function dashboardWsUrl() {
  return `${WS_BASE}/ws/dashboard`
}
