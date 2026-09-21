import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  allowConnection,
  blockConnection,
  dashboardWsUrl,
  getConnections,
  getRobots,
  type ConnectionDeviceDto,
  type RobotStateDto,
  type RobotRoute,
} from '../api/fmsApi'

export type RobotId = 'R-01' | 'R-02' | 'R-03'

export type ManagedRobot = {
  id: RobotId
  backendId: string
  ip: string
  connected: boolean
  blocked: boolean
  battery: number | null
  status: string
  x: number
  y: number
  yaw: number
  updatedAt?: string | null
  mode: 'real' | 'simulation'
  route: RobotRoute | null
}

const STORAGE_KEY = 'fms-managed-robots'
const SIMULATION_BOOTSTRAP_KEY = 'fms-simulation-fleet-bootstrap-v1'

function backendToUiId(value: string): RobotId | null {
  const match = /^robot0*([1-9][0-9]*)$/i.exec(value.trim())
  if (!match) return null
  const n = Number(match[1])
  if (n < 1 || n > 3) return null
  return `R-${String(n).padStart(2, '0')}` as RobotId
}

function uiToBackendId(id: RobotId) {
  return `robot${Number(id.replace('R-', ''))}`
}

function loadManagedIds(): RobotId[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is RobotId => /^R-0[1-3]$/.test(String(v)))
  } catch {
    return []
  }
}

export function useRobotFleet() {
  const [devices, setDevices] = useState<ConnectionDeviceDto[]>([])
  const [managedIds, setManagedIds] = useState<RobotId[]>(loadManagedIds)
  const [robotStates, setRobotStates] = useState<Record<string, RobotStateDto>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reconnectTimer = useRef<number | null>(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(managedIds))
  }, [managedIds])

  const refreshConnections = useCallback(async () => {
    try {
      const result = await getConnections()
      setDevices(result.devices)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const refreshRobots = useCallback(async () => {
    try {
      const rows = await getRobots()
      const simulationIds = rows
        .filter(row => row.mode === 'simulation')
        .map(row => backendToUiId(row.robot_id))
        .filter((id): id is RobotId => id !== null)
      if (simulationIds.length && localStorage.getItem(SIMULATION_BOOTSTRAP_KEY) !== 'done') {
        setManagedIds(prev => prev.length ? prev : simulationIds)
        localStorage.setItem(SIMULATION_BOOTSTRAP_KEY, 'done')
      }
      setRobotStates(prev => {
        const next = { ...prev }
        rows.forEach(row => {
          const current = next[row.robot_id]
          if (!current?.updated_at || !row.updated_at || Date.parse(row.updated_at) >= Date.parse(current.updated_at)) {
            next[row.robot_id] = row
          }
        })
        return next
      })
    } catch (e) {
      console.warn('robot state refresh failed:', e)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      setLoading(true)
      await Promise.all([refreshConnections(), refreshRobots()])
      if (!cancelled) setLoading(false)
    }
    boot()
    const timer = window.setInterval(() => {
      refreshConnections()
      refreshRobots()
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refreshConnections, refreshRobots])

  useEffect(() => {
    let socket: WebSocket | null = null
    let closedByEffect = false

    const connect = () => {
      socket = new WebSocket(dashboardWsUrl())

      socket.onmessage = event => {
        try {
          const message = JSON.parse(event.data)
          if (message?.type !== 'telemetry' || !message.data?.robot_id) return
          const data = message.data as RobotStateDto
          setRobotStates(prev => {
            const current = prev[data.robot_id]
            if (current?.updated_at && data.updated_at && Date.parse(data.updated_at) < Date.parse(current.updated_at)) return prev
            return { ...prev, [data.robot_id]: data }
          })
        } catch (e) {
          console.warn('dashboard telemetry parse failed:', e)
        }
      }

      socket.onclose = () => {
        if (closedByEffect) return
        reconnectTimer.current = window.setTimeout(connect, 1500)
      }

      socket.onerror = () => socket?.close()
    }

    connect()

    return () => {
      closedByEffect = true
      if (reconnectTimer.current !== null) window.clearTimeout(reconnectTimer.current)
      socket?.close()
    }
  }, [])

  const addRobot = useCallback(async (device: ConnectionDeviceDto) => {
    const uiId = backendToUiId(device.name)
    if (!uiId) throw new Error(`지원하지 않는 로봇 이름: ${device.name}`)

    if (device.blocked) {
      const result = await allowConnection(device.ip)
      setDevices(result.devices)
    }

    setManagedIds(prev => prev.includes(uiId) ? prev : [...prev, uiId])
    await refreshRobots()
  }, [refreshRobots])

  const removeRobot = useCallback((id: RobotId) => {
    setManagedIds(prev => prev.filter(item => item !== id))
  }, [])

  const disconnectRobot = useCallback(async (id: RobotId) => {
    const backendId = uiToBackendId(id)
    const device = devices.find(item => item.name === backendId)
    if (!device) throw new Error(`${id}의 연결 IP를 찾을 수 없습니다.`)
    const result = await blockConnection(device.ip)
    setDevices(result.devices)
    setManagedIds(prev => prev.filter(item => item !== id))
  }, [devices])

  const allowRobot = useCallback(async (device: ConnectionDeviceDto) => {
    const result = await allowConnection(device.ip)
    setDevices(result.devices)
  }, [])

  const managedRobots = useMemo<ManagedRobot[]>(() => {
    return managedIds.map(id => {
      const backendId = uiToBackendId(id)
      const device = devices.find(item => item.name === backendId)
      const state = robotStates[backendId]
      const telemetryFresh = Boolean(
        state?.updated_at &&
        Date.now() - Date.parse(state.updated_at) <= 5000
      )
      return {
        id,
        backendId,
        ip: device?.ip ?? '',
        connected: Boolean(device?.connected && !device?.blocked && telemetryFresh),
        blocked: Boolean(device?.blocked),
        battery: typeof state?.battery === 'number' ? state.battery : null,
        status: state?.status ?? (device?.connected ? 'ONLINE' : 'OFFLINE'),
        x: state?.x ?? 0,
        y: state?.y ?? 0,
        yaw: state?.yaw ?? 0,
        updatedAt: state?.updated_at ?? null,
        mode: state?.mode ?? 'real',
        route: state?.route ?? null,
      }
    })
  }, [devices, managedIds, robotStates])

  const availableDevices = useMemo(() => {
    return devices.filter(device => backendToUiId(device.name) !== null)
  }, [devices])

  return {
    availableDevices,
    managedIds,
    managedRobots,
    loading,
    error,
    refreshConnections,
    addRobot,
    removeRobot,
    disconnectRobot,
    allowRobot,
  }
}
