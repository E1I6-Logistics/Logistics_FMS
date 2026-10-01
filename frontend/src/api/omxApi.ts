const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`
const API_BASE = (import.meta.env.VITE_FMS_API_BASE ?? DEFAULT_API_BASE).replace(/\/$/, '')

export type OmxDevice = {
  omx_id: string
  connected: boolean
  state: string
  job_id: string | null
  items: Record<string, number>
  current_count: number
  total_count: number
  message: string
  last_seen_seconds_ago: number
}

export type OmxResponse = {
  mqtt: {
    enabled: boolean
    running: boolean
    broker_connected: boolean
    last_error: string | null
  }
  devices: OmxDevice[]
}

export async function getOmxDevices(): Promise<OmxResponse> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 3000)
  try {
    const response = await fetch(`${API_BASE}/api/omx`, { signal: controller.signal })
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
    return response.json() as Promise<OmxResponse>
  } finally {
    window.clearTimeout(timeout)
  }
}
