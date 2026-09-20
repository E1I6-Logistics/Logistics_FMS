import { useCallback, useEffect, useRef, useState } from 'react'
import { cmdVelWsUrl } from '../api/fmsApi'

type RemoteConn = 'off' | 'connecting' | 'ready'

type Options = {
  robotId: string | null
  enabled: boolean
  linearSpeed?: number
  angularSpeed?: number
}

const CONTROL_KEYS = new Set(['q', 'w', 'e', 'a', 's', 'd', ' '])

function isTypingTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName?.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable
}

export function useCmdVel({
  robotId,
  enabled,
  linearSpeed = 0.20,
  angularSpeed = 0.80,
}: Options) {
  const wsRef = useRef<WebSocket | null>(null)
  const pressedRef = useRef<Set<string>>(new Set())
  const [status, setStatus] = useState<RemoteConn>('off')
  const [activeKeys, setActiveKeys] = useState<Set<string>>(new Set())

  const computeTwist = useCallback(() => {
    const keys = pressedRef.current
    let linearX = 0
    let angularZ = 0

    if (keys.has('w')) linearX += linearSpeed
    if (keys.has('s')) linearX -= linearSpeed

    // TurtleBot 계열 차동구동은 lateral y 이동이 불가능하므로
    // Q/A는 좌회전, E/D는 우회전으로 동일하게 처리한다.
    if (keys.has('q') || keys.has('a')) angularZ += angularSpeed
    if (keys.has('e') || keys.has('d')) angularZ -= angularSpeed

    return { linearX, angularZ }
  }, [linearSpeed, angularSpeed])

  const sendCurrent = useCallback(() => {
    const ws = wsRef.current
    if (!robotId || !ws || ws.readyState !== WebSocket.OPEN) return
    const { linearX, angularZ } = computeTwist()
    ws.send(JSON.stringify({
      robot_id: robotId,
      linear_x: linearX,
      angular_z: angularZ,
    }))
  }, [robotId, computeTwist])

  const stop = useCallback(() => {
    pressedRef.current.clear()
    setActiveKeys(new Set())
    const ws = wsRef.current
    if (!robotId || !ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ robot_id: robotId, linear_x: 0, angular_z: 0 }))
  }, [robotId])

  const pressKey = useCallback((key: string) => {
    const normalized = key === 'Space' ? ' ' : key.toLowerCase()
    if (!CONTROL_KEYS.has(normalized) || normalized === ' ') return
    if (pressedRef.current.has(normalized)) return
    pressedRef.current.add(normalized)
    setActiveKeys(new Set(pressedRef.current))
    sendCurrent()
  }, [sendCurrent])

  const releaseKey = useCallback((key: string) => {
    const normalized = key === 'Space' ? ' ' : key.toLowerCase()
    if (!CONTROL_KEYS.has(normalized) || normalized === ' ') return
    pressedRef.current.delete(normalized)
    setActiveKeys(new Set(pressedRef.current))
    sendCurrent()
  }, [sendCurrent])

  useEffect(() => {
    if (!enabled || !robotId) {
      stop()
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      setStatus('off')
      return
    }

    setStatus('connecting')
    const ws = new WebSocket(cmdVelWsUrl())
    wsRef.current = ws

    ws.onopen = () => setStatus('ready')
    ws.onerror = () => setStatus('off')
    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      setStatus('off')
    }

    return () => {
      try {
        if (ws.readyState === WebSocket.OPEN && robotId) {
          ws.send(JSON.stringify({ robot_id: robotId, linear_x: 0, angular_z: 0 }))
        }
      } catch { /* ignore */ }
      ws.close()
      if (wsRef.current === ws) wsRef.current = null
      pressedRef.current.clear()
      setActiveKeys(new Set())
    }
  }, [enabled, robotId, stop])

  useEffect(() => {
    if (!enabled || status !== 'ready') return

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return
      const key = event.key.toLowerCase()
      if (!CONTROL_KEYS.has(key)) return
      event.preventDefault()

      if (key === ' ') {
        stop()
        return
      }
      if (event.repeat) return
      pressKey(key)
    }

    const onKeyUp = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return
      const key = event.key.toLowerCase()
      if (!CONTROL_KEYS.has(key)) return
      event.preventDefault()
      if (key !== ' ') releaseKey(key)
    }

    const onBlur = () => stop()

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onBlur)

    // 키를 누른 채로 유지할 때 10 Hz로 현재 cmd_vel을 재전송
    const timer = window.setInterval(() => {
      if (pressedRef.current.size > 0) sendCurrent()
    }, 100)

    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onBlur)
      window.clearInterval(timer)
      stop()
    }
  }, [enabled, status, pressKey, releaseKey, sendCurrent, stop])

  return {
    status,
    activeKeys,
    pressKey,
    releaseKey,
    stop,
  }
}
