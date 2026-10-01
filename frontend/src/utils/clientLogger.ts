type ClientLogLevel = 'warning' | 'error'
type ClientLogDetails = Record<string, string | number | boolean | null>

const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`
const API_BASE = (import.meta.env.VITE_FMS_API_BASE ?? DEFAULT_API_BASE).replace(/\/$/, '')
const recent = new Map<string, number>()

function errorMessage(value: unknown) {
  if (value instanceof Error) return `${value.name}: ${value.message}`
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function reportClientIssue(
  level: ClientLogLevel,
  event: string,
  error: unknown,
  details: ClientLogDetails = {},
) {
  const message = errorMessage(error).slice(0, 2000)
  const fingerprint = `${level}:${event}:${message}`
  const now = Date.now()
  const previous = recent.get(fingerprint) ?? 0
  if (now - previous < 5000) return
  recent.set(fingerprint, now)

  const output = level === 'error' ? console.error : console.warn
  output(`[${event}]`, message, details)

  // Use raw fetch to avoid a logging failure recursively entering the normal
  // API error reporter. Logging must never affect dashboard behavior.
  void fetch(`${API_BASE}/api/client-logs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level,
      event,
      message,
      url: window.location.href,
      client_time: new Date().toISOString(),
      details,
    }),
    keepalive: true,
  }).catch(() => undefined)
}

export function installGlobalErrorLogging() {
  window.addEventListener('error', event => {
    reportClientIssue('error', 'window_error', event.error ?? event.message, {
      filename: event.filename || '',
      line: event.lineno,
      column: event.colno,
    })
  })

  window.addEventListener('unhandledrejection', event => {
    reportClientIssue('error', 'unhandled_rejection', event.reason)
  })

  window.addEventListener('offline', () => {
    reportClientIssue('warning', 'browser_offline', 'Browser network connection is offline')
  })
}

