import { useCallback, useEffect, useState } from 'react'

import { getOmxDevices, type OmxDevice } from '../api/omxApi'

export function useOmxFleet() {
  const [devices, setDevices] = useState<OmxDevice[]>([])
  const [brokerConnected, setBrokerConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const result = await getOmxDevices()
      setDevices(result.devices)
      setBrokerConnected(result.mqtt.broker_connected)
      setError(result.mqtt.last_error)
    } catch (reason) {
      setBrokerConnected(false)
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }, [])

  useEffect(() => {
    let stopped = false
    let timer: number | null = null

    const poll = async () => {
      await refresh()
      if (!stopped) timer = window.setTimeout(poll, 1000)
    }
    void poll()

    return () => {
      stopped = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [refresh])

  return { devices, brokerConnected, error, refresh }
}
