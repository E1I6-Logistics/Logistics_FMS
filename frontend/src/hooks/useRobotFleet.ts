import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  allowConnection,
  blockConnection,
  dashboardWsUrl,
  getConnections,
  getRobotMode,
  getRobots,
  setRobotMode,
  type ConnectionDeviceDto,
  type RobotMode,
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
  pixelX: number | null
  pixelY: number | null
  hasPose: boolean
  connectionState: string
  updatedAt?: string | null
  mode: 'real' | 'simulation'
  route: RobotRoute | null
}

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

export function useRobotFleet() {
  const [devices, setDevices] = useState<ConnectionDeviceDto[]>([])
  const [robotStates, setRobotStates] = useState<Record<string, RobotStateDto>>({})
  const [mode, setModeState] = useState<RobotMode>('simulation')
  const [modeSwitching, setModeSwitching] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reconnectTimer = useRef<number | null>(null)

  const refreshMode = useCallback(async () => {
    const result = await getRobotMode()
    setModeState(result.mode)
    return result.mode
  }, [])

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
      setRobotStates(Object.fromEntries(rows.map(row => [row.robot_id, row])))
    } catch (e) {
      console.warn('robot state refresh failed:', e)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      setLoading(true)
      await Promise.all([refreshMode(), refreshConnections(), refreshRobots()])
      if (!cancelled) setLoading(false)
    }
    boot()
    const connectionTimer = window.setInterval(
      refreshConnections,
      2000,
    )

    const robotTimer = window.setInterval(
      refreshRobots,
      500,
    )

    return () => {
      cancelled = true
      window.clearInterval(connectionTimer)
      window.clearInterval(robotTimer)
    }
  }, [refreshConnections, refreshMode, refreshRobots])

  useEffect(() => {
    let socket: WebSocket | null = null
    let closedByEffect = false

    const connect = () => {
      socket = new WebSocket(dashboardWsUrl())

      socket.onmessage = event => {
        try {
          const message = JSON.parse(event.data)
          if (message?.type === 'system' && message.data?.mode) {
            setModeState(message.data.mode as RobotMode)
            void refreshRobots()
            return
          }
          if (message?.type !== 'telemetry' || !message.data?.robot_id) return
          const data = message.data as RobotStateDto
          if (data.mode && data.mode !== mode) return
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
  }, [mode, refreshRobots])

  const changeMode = useCallback(async (nextMode: RobotMode) => {
    if (nextMode === mode) return
    setModeSwitching(true)
    try {
      const result = await setRobotMode(nextMode)
      setModeState(result.mode)
      setRobotStates({})
      await refreshRobots()
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      throw e
    } finally {
      setModeSwitching(false)
    }
  }, [mode, refreshRobots])

  const disconnectRobot = useCallback(async (id: RobotId) => {
    const backendId = uiToBackendId(id)
    const device = devices.find(item => item.name === backendId)
    if (!device) throw new Error(`${id}의 연결 IP를 찾을 수 없습니다.`)
    const result = await blockConnection(device.ip)
    setDevices(result.devices)
  }, [devices])

  const allowRobot = useCallback(async (device: ConnectionDeviceDto) => {
    const result = await allowConnection(device.ip)
    setDevices(result.devices)
  }, [])

  const robotIds = useMemo(() => Object.values(robotStates)
    .filter(state => state.mode === mode)
    .map(state => backendToUiId(state.robot_id))
    .filter((id): id is RobotId => id !== null), [mode, robotStates])

  const managedRobots = useMemo<ManagedRobot[]>(() => {
    return robotIds.map(id => {
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
        connected: mode === 'simulation'
          ? Boolean(state && telemetryFresh)
          : Boolean(
              state?.connection_state === 'ONLINE'
              && telemetryFresh
            ),
        blocked: Boolean(device?.blocked),
        battery: typeof state?.battery === 'number' ? state.battery : null,
        status: state?.status ?? (device?.connected ? 'ONLINE' : 'OFFLINE'),
        x: state?.x ?? 0,
        y: state?.y ?? 0,
        yaw: state?.yaw ?? 0,
        updatedAt: state?.updated_at ?? null,
        mode: state?.mode ?? mode,
        route: state?.route ?? null,
        pixelX: state?.pixel_x ?? null,
        pixelY: state?.pixel_y ?? null,
        hasPose: state?.map_pose_received === true,
        connectionState: state?.connection_state ?? 'OFFLINE',
      }
    })
  }, [devices, mode, robotIds, robotStates])

  const managedIds = useMemo(() => mode === 'simulation'
    ? robotIds
    : managedRobots.filter(robot => robot.connected).map(robot => robot.id),
  [managedRobots, mode, robotIds])

  const mapRobotIds = useMemo(() => mode === 'simulation'
    ? robotIds
    : managedRobots.filter(robot => robot.hasPose).map(robot => robot.id),
  [managedRobots, mode, robotIds])

  const availableDevices = useMemo(() => {
    return devices.filter(device =>
      backendToUiId(device.name) !== null
      && (device.connected || device.blocked)
    )
  }, [devices])

  return {
    availableDevices,
    managedIds,
    mapRobotIds,
    managedRobots,
    mode,
    modeSwitching,
    loading,
    error,
    refreshConnections,
    changeMode,
    disconnectRobot,
    allowRobot,
  }
}
