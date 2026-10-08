import { useEffect, useId, useMemo, useState } from 'react'

import { createOrder, type OrderItems } from '../api/orderApi'
import type { RouteModelDto, RouteModelGroupsDto } from '../api/fmsApi'
import { C, MONO } from '../constants/theme'

type Props = {
  robotId: string
  disabled?: boolean
  routeModels: RouteModelGroupsDto
  routeModelError: string | null
}

const INITIAL_ITEMS: OrderItems = {
  A: 0,
  B: 0,
  C: 0,
  D: 0,
}

export default function RobotOrderForm({ robotId, disabled = false, routeModels, routeModelError }: Props) {
  const [items, setItems] = useState<OrderItems>(INITIAL_ITEMS)
  const [workstationNode, setWorkstationNode] = useState<'3' | '4'>('3')
  const [expanded, setExpanded] = useState(true)
  const [drivingMode, setDrivingMode] = useState<'standard' | 'llm'>('standard')
  const [selectedModelKey, setSelectedModelKey] = useState('')
  const fieldsId = useId()
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<{
    tone: 'success' | 'danger'
    text: string
  } | null>(null)

  const totalQuantity = useMemo(
    () => Object.values(items).reduce((sum, quantity) => sum + quantity, 0),
    [items],
  )
  const validQuantity = totalQuantity >= 1 && totalQuantity <= 5
  const formDisabled = disabled || submitting
  const availableModels = useMemo(
    () => [...routeModels.ollama, ...routeModels.decision_model],
    [routeModels],
  )
  const selectedModel: RouteModelDto | undefined = availableModels.find(
    item => item.selector + ':' + item.model === selectedModelKey,
  )
  const canSubmit = validQuantity && (drivingMode === 'standard' || Boolean(selectedModel))

  useEffect(() => {
    setItems(INITIAL_ITEMS)
    setWorkstationNode('3')
    setDrivingMode('standard')
    setSelectedModelKey('')
    setMessage(null)
  }, [robotId])

  const updateQuantity = (item: keyof OrderItems, rawValue: string) => {
    const parsed = Number(rawValue)
    const quantity = Number.isFinite(parsed)
      ? Math.max(0, Math.min(5, Math.trunc(parsed)))
      : 0

    setItems(current => ({ ...current, [item]: quantity }))
    setMessage(null)
  }

  const submit = async () => {
    if (!canSubmit || formDisabled) return

    try {
      setSubmitting(true)
      setMessage(null)

      const order = await createOrder({
        robot_id: robotId,
        items,
        total_quantity: totalQuantity,
        workstation_node: workstationNode,
        driving_mode: drivingMode,
        selector: drivingMode === 'llm' ? selectedModel?.selector : undefined,
        model: drivingMode === 'llm' ? selectedModel?.model : undefined,
      })

      setMessage({
        tone: 'success',
        text: `주문 ${order.order_id}이 등록되었습니다.`,
      })
      setItems(INITIAL_ITEMS)
    } catch (error) {
      setMessage({
        tone: 'danger',
        text: error instanceof Error ? error.message : '주문을 등록하지 못했습니다.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section
      aria-label={`${robotId} 주문 입력`}
      style={{
        padding: 11,
        border: `1px solid ${C.line}`,
        borderRadius: 10,
        background: 'rgba(255,255,255,.97)',
        boxShadow: '0 6px 20px rgba(31,45,61,.14)',
      }}
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={fieldsId}
        onClick={() => setExpanded(current => !current)}
        style={{
          display: 'flex',
          width: '100%',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          padding: 0,
          border: 0,
          background: 'transparent',
          color: C.text,
          fontSize: 11,
          fontWeight: 800,
          textAlign: 'left',
          cursor: 'pointer',
        }}
      >
        <span>주문 입력 · {robotId}</span>
        <span style={{ color: C.muted, fontSize: 9, fontWeight: 600 }}>
          {expanded ? '접기 ▲' : '펼치기 ▼'}
        </span>
      </button>

      <div
        id={fieldsId}
        hidden={!expanded}
        style={{
          marginTop: 9,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
            gap: 6,
          }}
        >
          {(Object.keys(items) as (keyof OrderItems)[]).map(item => (
            <label
              key={item}
              style={{
                display: 'block',
                color: C.text,
                fontSize: 9,
                fontWeight: 800,
              }}
            >
              <span style={{ display: 'block', marginBottom: 4 }}>
                {item} · N{item === 'A' || item === 'B' ? '5' : '6'}
              </span>
              <input
                type="number"
                min={0}
                max={5}
                step={1}
                value={items[item]}
                disabled={formDisabled}
                onChange={event => updateQuantity(item, event.target.value)}
                aria-label={`${item} 수량`}
                style={{
                  width: '100%',
                  minWidth: 0,
                  height: 29,
                  boxSizing: 'border-box',
                  border: `1px solid ${C.line}`,
                  borderRadius: 6,
                  padding: '0 8px',
                  background: formDisabled ? '#EEF1F5' : '#fff',
                  color: C.text,
                  font: `600 10px ${MONO}`,
                }}
              />
            </label>
          ))}
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
            marginTop: 9,
          }}
        >
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              color: C.muted,
              fontSize: 9,
            }}
          >
            작업대
            <select
              value={workstationNode}
              disabled={formDisabled}
              onChange={event => setWorkstationNode(event.target.value as '3' | '4')}
              style={{
                width: 66,
                height: 29,
                border: `1px solid ${C.line}`,
                borderRadius: 6,
                padding: '0 6px',
                background: formDisabled ? '#EEF1F5' : '#fff',
                color: C.text,
                font: `600 9px ${MONO}`,
              }}
            >
              <option value="3">N3</option>
              <option value="4">N4</option>
            </select>
          </label>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              color: totalQuantity > 5 ? C.danger : validQuantity ? C.success : C.muted,
              fontSize: 9,
              fontWeight: 800,
            }}
          >
            <span>적재량</span>
            <span>{totalQuantity} / 5</span>
          </div>
        </div>

        <div style={{ marginTop: 10, display: 'flex', gap: 6 }}>
          {(['standard', 'llm'] as const).map(mode => (
            <button
              key={mode}
              type="button"
              aria-pressed={drivingMode === mode}
              disabled={formDisabled}
              onClick={() => { setDrivingMode(mode); setMessage(null) }}
              style={{
                flex: 1,
                padding: '7px 5px',
                borderRadius: 6,
                border: '1px solid ' + (drivingMode === mode ? C.primary : C.line),
                background: drivingMode === mode ? '#EDF6FF' : '#fff',
                color: drivingMode === mode ? C.primary : C.muted,
                fontSize: 9,
                fontWeight: 700,
                cursor: formDisabled ? 'not-allowed' : 'pointer',
              }}
            >
              {mode === 'standard' ? '기본 경로' : 'LLM 경로'}
            </button>
          ))}
        </div>
        {drivingMode === 'llm' && (
          <div style={{ marginTop: 8 }}>
            <label htmlFor={fieldsId + '-model'} style={{ display: 'block', marginBottom: 4, color: C.muted, fontSize: 9 }}>
              주문 경로 모델
            </label>
            <select
              id={fieldsId + '-model'}
              value={selectedModelKey}
              disabled={formDisabled}
              onChange={event => { setSelectedModelKey(event.target.value); setMessage(null) }}
              style={{
                width: '100%',
                height: 29,
                border: '1px solid ' + C.line,
                borderRadius: 6,
                background: '#fff',
                color: C.text,
                fontSize: 9,
              }}
            >
              <option value="">모델 선택</option>
              <optgroup label="Ollama">
                {routeModels.ollama.map(item => (
                  <option key={'ollama:' + item.model} value={'ollama:' + item.model}>{item.model}</option>
                ))}
              </optgroup>
              <optgroup label="Decision Model">
                {routeModels.decision_model.map(item => (
                  <option key={item.selector + ':' + item.model} value={item.selector + ':' + item.model}>
                    {item.selector.toUpperCase()} · {item.model}
                  </option>
                ))}
              </optgroup>
            </select>
            {routeModelError && <div role="alert" style={{ color: C.danger, fontSize: 8.5, marginTop: 4 }}>{routeModelError}</div>}
          </div>
        )}

        {totalQuantity > 5 && (
          <div style={{ marginTop: 5, color: C.danger, fontSize: 8.5 }}>
            최대 적재량을 초과했습니다.
          </div>
        )}

        {message && (
          <div
            role="status"
            style={{
              marginTop: 7,
              padding: '6px 7px',
              borderRadius: 6,
              background: message.tone === 'success' ? '#E9F8F3' : '#FFF0F2',
              color: message.tone === 'success' ? C.success : C.danger,
              fontSize: 8.5,
              lineHeight: 1.4,
            }}
          >
            {message.text}
          </div>
        )}

        <button
          type="button"
          onClick={submit}
          disabled={formDisabled || !canSubmit}
          style={{
            width: '100%',
            height: 34,
            marginTop: 8,
            border: 0,
            borderRadius: 7,
            background: !formDisabled && canSubmit ? C.primary : '#DDE3EC',
            color: !formDisabled && canSubmit ? '#fff' : '#9AA4B0',
            fontSize: 9.5,
            fontWeight: 800,
            cursor: !formDisabled && canSubmit ? 'pointer' : 'not-allowed',
          }}
        >
          {submitting ? '주문 등록 중…' : '주문 등록'}
        </button>
      </div>
    </section>
  )
}
