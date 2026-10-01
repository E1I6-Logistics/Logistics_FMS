import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
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
import { reportClientIssue } from '../utils/clientLogger'

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
  const [dashboardStatus, setDashboardStatus] = useState<'connecting' | 'ready' | 'degraded'>('connecting')
  const reconnectTimer = useRef<number | null>(null)
  const reconnectAttempt = useRef(0)

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
    let bootComplete = false
    let connectionTimer: number | null = null
    let robotTimer: number | null = null
    const realMode = mode === 'real'
    const connectionPollMs = realMode ? 5000 : 2000
    const robotPollMs = realMode ? 300 : 200
    const initialRobotPollMs = realMode ? 300 : 1000
    const pollingPaused = () => realMode && document.hidden

    const boot = async () => {
      setLoading(true)
      await Promise.allSettled([refreshMode(), refreshConnections(), refreshRobots()])
      if (!cancelled) setLoading(false)
    }

    const pollConnections = async () => {
      connectionTimer = null
      if (pollingPaused()) return
      await refreshConnections()
      if (!cancelled && !pollingPaused()) {
        connectionTimer = window.setTimeout(pollConnections, connectionPollMs)
      }
    }

    const pollRobots = async () => {
      robotTimer = null
      if (pollingPaused()) return
      await refreshRobots()
      if (!cancelled && !pollingPaused()) {
        robotTimer = window.setTimeout(pollRobots, robotPollMs)
      }
    }

    const clearPollingTimers = () => {
      if (connectionTimer !== null) window.clearTimeout(connectionTimer)
      if (robotTimer !== null) window.clearTimeout(robotTimer)
      connectionTimer = null
      robotTimer = null
    }

    const handleVisibilityChange = () => {
      if (!realMode || cancelled) return
      clearPollingTimers()
      if (document.hidden || !bootComplete) return
      void pollConnections()
      void pollRobots()
    }

    void boot().then(() => {
      if (cancelled) return
      bootComplete = true
      if (pollingPaused()) return
      connectionTimer = window.setTimeout(pollConnections, connectionPollMs)
      robotTimer = window.setTimeout(pollRobots, initialRobotPollMs)
    })

    if (realMode) document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cancelled = true
      if (realMode) document.removeEventListener('visibilitychange', handleVisibilityChange)
      clearPollingTimers()
    }
  }, [mode, refreshConnections, refreshMode, refreshRobots])

  useEffect(() => {
    let socket: WebSocket | null = null
    let closedByEffect = false

    const connect = () => {
      setDashboardStatus('connecting')
      socket = new WebSocket(dashboardWsUrl())

      socket.onopen = () => {
        reconnectAttempt.current = 0
        setDashboardStatus('ready')
      }

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
          reportClientIssue('warning', 'dashboard_message_invalid', e)
        }
      }

      socket.onclose = () => {
        if (closedByEffect) return
        setDashboardStatus('degraded')
        const attempt = reconnectAttempt.current++
        const delay = Math.min(15000, 1000 * 2 ** attempt) + Math.round(Math.random() * 500)
        reportClientIssue('warning', 'dashboard_ws_closed', 'Dashboard WebSocket closed', {
          reconnect_delay_ms: delay,
        })
        reconnectTimer.current = window.setTimeout(connect, delay)
      }

      socket.onerror = () => {
        reportClientIssue('warning', 'dashboard_ws_error', 'Dashboard WebSocket error')
        socket?.close()
      }
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

  const robotIds = useMemo(() => {
    if (mode === 'real') {
      return devices
        .map(device => backendToUiId(device.name))
        .filter((id): id is RobotId => id !== null)
    }

    return Object.values(robotStates)
      .filter(state => state.mode === mode)
      .map(state => backendToUiId(state.robot_id))
      .filter((id): id is RobotId => id !== null)
  }, [devices, mode, robotStates])

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
          : Boolean(device?.connected),

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
        connectionState: mode === 'real' ? (device?.state ?? 'OFFLINE') : (state?.connection_state ?? 'OFFLINE'),
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

  return {
    managedIds,
    mapRobotIds,
    managedRobots,
    mode,
    modeSwitching,
    loading,
    error,
    dashboardStatus,
    refreshConnections,
    changeMode,
  }
}
