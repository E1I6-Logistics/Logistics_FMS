import { useEffect, useState } from 'react'
import { getScenarios, getScenarioStatus, runScenario, type ScenarioItem, type ScenarioStatus } from '../api/fmsApi'
import { C } from '../constants/theme'

export default function ScenarioControls({ modeSwitching, onActiveChange }: {
  modeSwitching: boolean
  onActiveChange: (active: boolean) => void
}) {
  const [items, setItems] = useState<ScenarioItem[]>([])
  const [selected, setSelected] = useState('')
  const [status, setStatus] = useState<ScenarioStatus | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const active = status?.state === 'running' || status?.state === 'stopping'

  const refreshList = async () => {
    try {
      const list = await getScenarios()
      setItems(list)
      setSelected(current => list.some(item => item.name === current) ? current : list[0]?.name ?? '')
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '시나리오 목록 조회 실패')
    }
  }

  useEffect(() => { void refreshList() }, [])
  useEffect(() => {
    let closed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const next = await getScenarioStatus()
        if (!closed) { setStatus(next); setConnectionError('') }
      } catch (e) {
        if (!closed) setConnectionError(e instanceof Error ? e.message : '실행 상태 조회 실패')
      } finally {
        if (!closed) timer = setTimeout(() => { void poll() }, 500)
      }
    }
    void poll()
    return () => { closed = true; clearTimeout(timer) }
  }, [])
  useEffect(() => { onActiveChange(active || submitting) }, [active, submitting, onActiveChange])

  const execute = async () => {
    setSubmitting(true)
    setError('')
    try { setStatus(await runScenario(selected)) }
    catch (e) { setError(e instanceof Error ? e.message : '시나리오 실행 실패') }
    finally { setSubmitting(false) }
  }
  const disabled = active || submitting || modeSwitching || !status || Boolean(connectionError)
  const message = error || connectionError || (status?.name ? `${status.description} · ${status.message}` : '')

  return (
    <div style={{ position: 'absolute', top: 14, left: 56, zIndex: 21, maxWidth: 'calc(100% - 76px)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <select aria-label="테스트 시나리오" value={selected} disabled={disabled}
          onFocus={() => { void refreshList() }} onChange={e => setSelected(e.target.value)}
          style={{ width: 250, maxWidth: '55vw', height: 32, border: `1px solid ${C.line}`, borderRadius: 6, background: '#fff', color: C.text, fontSize: 11, padding: '0 8px' }}>
          {!items.length && <option value="">시나리오 없음</option>}
          {items.map(item => <option key={item.name} value={item.name}>{item.description}</option>)}
        </select>
        <button disabled={disabled || !selected} onClick={() => { void execute() }}
          style={{ height: 32, padding: '0 12px', border: 0, borderRadius: 6, background: disabled || !selected ? '#DDE3EC' : C.primary, color: disabled ? C.muted : '#fff', fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap', cursor: disabled ? 'not-allowed' : 'pointer' }}>
          {active || submitting ? '실행 중…' : '테스트 실행'}
        </button>
      </div>
      {message && <div role="status" style={{ marginTop: 6, maxWidth: 440, maxHeight: 150, overflowY: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', padding: '7px 9px', borderRadius: 6, background: '#fff', color: error || connectionError || status?.state === 'failed' ? C.danger : C.text, fontSize: 11, boxShadow: '0 2px 6px #0001' }}>{message}</div>}
    </div>
  )
}
