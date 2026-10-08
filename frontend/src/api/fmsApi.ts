const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`
const API_BASE = (import.meta.env.VITE_FMS_API_BASE ?? DEFAULT_API_BASE).replace(/\/$/, '')

export const MAP_IMAGE_URL = `${API_BASE}/api/map/image`

function wsBaseFromHttp(base: string) {
  if (base.startsWith('https://')) return `wss://${base.slice('https://'.length)}`
  if (base.startsWith('http://')) return `ws://${base.slice('http://'.length)}`
  return base
}

export const WS_BASE = (import.meta.env.VITE_FMS_WS_BASE ?? wsBaseFromHttp(API_BASE)).replace(/\/$/, '')

export type RobotMode = 'real' | 'simulation'

export type RobotModeDto = {
  mode: RobotMode
  real_available: boolean
  simulation_active: boolean
}

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

export type MapInfoDto = {
  width: number
  height: number
  image_url: string
  image_name: string
}

export function getMapInfo() {
  return request<MapInfoDto>('/api/map/info')
}

export function getRobotMode() {
  return request<RobotModeDto>('/api/mode')
}

export function setRobotMode(mode: RobotMode) {
  return request<RobotModeDto>('/api/mode', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
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

export type RouteModelDto = { selector: 'ollama' | 'laya' | 'kev'; model: string }
export type RouteModelGroupsDto = { ollama: RouteModelDto[]; decision_model: RouteModelDto[] }

export function getRouteModels() {
  return request<RouteModelGroupsDto>('/api/command/route-models')
}

export function sendGoalNode(
  robotId: string,
  nodeId: string | number,
  drivingMode: 'standard' | 'llm' = 'standard',
  routeModel?: RouteModelDto,
) {
  return request<{ mode: RobotMode; driving_mode: 'standard' | 'llm'; llm?: Omit<LlmRoutePreviewDto, 'mode' | 'robot_id' | 'start_node' | 'target_node'> }>(
    '/api/command/goal-node',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ robot_id: robotId, node_id: nodeId, driving_mode: drivingMode, selector: routeModel?.selector, model: routeModel?.model }),
    },
  )
}

export type LlmRoutePreviewDto = {
  mode: RobotMode
  robot_id: string
  start_node: string
  target_node: string
  dispatched: boolean
  path: string[]
  model: string | null
  total_weight: number
  calls: number
  baseline_path: string[]
  baseline_weight: number
  same_path: boolean
  same_distance: boolean
  distance_difference: number
}

export function previewLlmRoute(robotId: string, nodeId: string | number, routeModel: RouteModelDto) {
  return request<LlmRoutePreviewDto>('/api/command/llm-route-preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId, node_id: nodeId, selector: routeModel.selector, model: routeModel.model }),
  })
}

export function sendCharging(robotId: string) {
  return request<Record<string, unknown>>('/api/command/charging', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId }),
  })
}

export function sendGoalCoordinate(robotId: string, targetX: number, targetY: number) {
  return request<Record<string, unknown>>('/api/command/goal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId, target_x: targetX, target_y: targetY }),
  })
}

export function returnNearestNode(robotId: string) {
  return request<Record<string, unknown>>(
    '/api/command/return-nearest-node',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ robot_id: robotId }),
    },
  )
}

export function stopRobot(robotId: string) {
  return request<Record<string, unknown>>('/api/command/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId }),
  })
}

export function emergencyReleaseRobot(robotId: string) {
  return request<Record<string, unknown>>('/api/command/emergency-release', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId }),
  })
}

export function stopAllRobots() {
  return request<Record<string, unknown>>('/api/command/stop-all', {
    method: 'POST',
  })
}

export function emergencyReleaseAll() {
  return request<Record<string, unknown>>('/api/command/emergency-release-all', {
    method: 'POST',
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
  battery: number | null
  x: number
  y: number
  yaw: number
  updated_at?: string | null
  mode: 'real' | 'simulation'
  route?: RobotRoute | null
  pixel_x?: number | null
  pixel_y?: number | null
  map_pose_received: boolean
  connection_state: string
}

export type OmxDeviceDto = {
  omx_id: string
  connected: boolean
  x: number
  y: number
  pixel_x: number
  pixel_y: number
}

export function getConnections() {
  return request<{ devices: ConnectionDeviceDto[] }>('/api/connections')
}

export function getRobots() {
  return request<RobotStateDto[]>('/api/robots')
}

export function dashboardWsUrl() {
  return `${WS_BASE}/ws/dashboard`
}

export function getOmxDevices() {
  return request<OmxDeviceDto[]>('/api/omx')
}