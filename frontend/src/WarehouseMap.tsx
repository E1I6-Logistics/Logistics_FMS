import { useEffect, useId, useRef, useState } from 'react'
import mapImage from './imports/map.png'
import { STRUCTURES, WarehouseGeometry } from './WarehouseGeometry'
import './warehouse-map.css'

type RobotId = 'R-01' | 'R-02' | 'R-03'
type Point = { x: number; y: number }
type Props = {
  nodes: Record<string, Point>
  layers: { nodeEdge: boolean; route: boolean; station: boolean; robotId: boolean }
  selectedRobot: RobotId | null
  onSelect: (id: RobotId) => void
  picking: boolean
  targetNode?: string
  onPick: (id: string) => void
}

// Existing dashboard's example topology, not a surveyed navigation graph.
const EDGES = [
  ['N1', 'N2'], ['N1', 'N8'], ['N1', 'N9'], ['N2', 'N3'], ['N2', 'N11'],
  ['N3', 'N4'], ['N3', 'N12'], ['N4', 'N5'], ['N4', 'N8'], ['N5', 'N6'],
  ['N6', 'N7'], ['N7', 'N8'], ['N9', 'N10'], ['N10', 'N13'], ['N11', 'N12'],
  ['N11', 'N13'], ['N12', 'N14'], ['N13', 'N14'],
]
const ROBOTS: { id: RobotId; x: number; y: number; color: string; heading: number; route: string[] }[] = [
  { id: 'R-01', x: 76, y: 61, color: '#2589F5', heading: 270, route: ['N9', 'N1', 'N2', 'N3'] },
  { id: 'R-02', x: 37, y: 61, color: '#E5A53A', heading: 0, route: ['N3', 'N2', 'N11', 'N13'] },
  { id: 'R-03', x: 86, y: 111, color: '#36BD8A', heading: 90, route: ['N10', 'N13', 'N14'] },
]

export default function WarehouseMap({ nodes, layers, selectedRobot, onSelect, picking, targetNode, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; x: number; y: number; pan: Point } | null>(null)
  const [size, setSize] = useState({ width: 600, height: 600 })
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 })
  const [raw, setRaw] = useState(false)
  const [dragging, setDragging] = useState(false)
  const gridId = useId().replace(/:/g, '')
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    if (host.current) observer.observe(host.current)
    return () => observer.disconnect()
  }, [])
  const span = 151 / zoom
  const scale = Math.max(0.1, Math.min(size.width, size.height) / span)
  const px = (n: number) => n / scale
  const adjustZoom = (factor: number) => setZoom(value => Math.max(0.75, Math.min(4, value * factor)))
  const reset = () => { setZoom(1); setPan({ x: 0, y: 0 }) }

  return (
    <div className="warehouse-map" ref={host}>
      <svg className="warehouse-map__canvas" aria-label="실제 공간 기반 관제 지도" role="group"
        viewBox={`${67.5 - span / 2 + pan.x} ${67.5 - span / 2 + pan.y} ${span} ${span}`}
        preserveAspectRatio="xMidYMid meet" style={{ cursor: dragging ? 'grabbing' : 'grab' }}
        onPointerDown={event => {
          if (event.button !== 0) return
          drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, pan }
          event.currentTarget.setPointerCapture(event.pointerId)
          setDragging(true)
        }}
        onPointerMove={event => {
          const start = drag.current
          if (!start) return
          setPan({ x: start.pan.x - (event.clientX - start.x) / scale, y: start.pan.y - (event.clientY - start.y) / scale })
        }}
        onPointerUp={() => { drag.current = null; setDragging(false) }}
        onPointerCancel={() => { drag.current = null; setDragging(false) }}
        onWheel={event => adjustZoom(event.deltaY < 0 ? 1.12 : 1 / 1.12)}>
        <defs>
          <pattern id={gridId} width="4" height="4" patternUnits="userSpaceOnUse">
            <path d="M4 0H0V4" fill="none" stroke="#BBC6D2" strokeWidth="0.08" opacity="0.45" />
          </pattern>
        </defs>
        {raw ? <image href={mapImage} x="0" y="0" width="135" height="135" imageRendering="pixelated" /> : <WarehouseGeometry />}
        {!raw && <rect x="7" y="7" width="119" height="120" fill={`url(#${gridId})`} pointerEvents="none" />}

        {!raw && layers.nodeEdge && <g data-testid="navigation-edges" fill="none" stroke="#B9C3CF" strokeWidth={px(2)} strokeLinecap="round">
          {EDGES.map(([from, to]) => <path key={`${from}-${to}`} d={`M${nodes[from].x} ${nodes[from].y}L${nodes[to].x} ${nodes[to].y}`} />)}
        </g>}
        {!raw && layers.route && <g data-testid="robot-routes" fill="none" strokeLinecap="round" strokeLinejoin="round">
          {ROBOTS.map(robot => {
            const selected = selectedRobot === robot.id
            return <polyline key={robot.id} points={robot.route.map(id => `${nodes[id].x},${nodes[id].y}`).join(' ')}
              stroke={robot.id === 'R-02' ? '#8B6BE8' : '#2589F5'} strokeWidth={px(selected ? 4 : 3)}
              opacity={selected ? 0.95 : selectedRobot ? 0.15 : 0.45} />
          })}
          {!selectedRobot && <path d={`M${nodes.N2.x} ${nodes.N2.y}L${nodes.N3.x} ${nodes.N3.y}`} stroke="#8B6BE8" strokeWidth={px(4)} strokeDasharray={`${px(5)} ${px(4)}`} />}
        </g>}
        {!raw && (layers.nodeEdge || picking) && <g data-testid="navigation-nodes">
          {Object.entries(nodes).map(([id, node]) => (
            <g key={id} role={picking ? 'button' : undefined} tabIndex={picking ? 0 : undefined}
              aria-label={picking ? `${id} 목표 선택` : undefined}
              style={{ cursor: picking ? 'crosshair' : 'inherit' }}
              onPointerDown={event => { if (picking) event.stopPropagation() }}
              onClick={() => { if (picking) onPick(id) }}
              onKeyDown={event => { if (picking && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onPick(id) } }}>
              <circle cx={node.x} cy={node.y} r={px(picking ? 13 : 9)} fill="transparent" />
              {targetNode === id && picking && <circle cx={node.x} cy={node.y} r={px(11)} fill="#2589F5" opacity="0.18" />}
              <circle cx={node.x} cy={node.y} r={px(3.8)} fill={targetNode === id && picking ? '#2589F5' : '#FFF'} stroke="#8192A5" strokeWidth={px(1.3)} />
              {(!layers.robotId || !ROBOTS.some(robot => Math.hypot(robot.x - node.x, robot.y - node.y) < px(20))) && <text x={node.x + px(7)} y={node.y - px(6)} fontSize={px(9)} fill="#718194" paintOrder="stroke" stroke="#F1F4F7" strokeWidth={px(2)}>{id}</text>}
            </g>
          ))}
        </g>}
        {!raw && layers.station && <g data-testid="structure-labels" fill="#697582" fontSize={px(10)} fontWeight="600">
          {STRUCTURES.map(s => <text key={s.id} x={s.x + s.w + px(6)} y={s.y + s.h / 2} dominantBaseline="middle">{s.id}</text>)}
        </g>}
        {!raw && layers.robotId && <g data-testid="robot-markers">
          {ROBOTS.map(robot => {
            const selected = selectedRobot === robot.id
            return <g key={robot.id} role="button" tabIndex={0} aria-label={`${robot.id} 로봇 선택`}
              style={{ cursor: 'pointer' }} onPointerDown={event => event.stopPropagation()} onClick={() => onSelect(robot.id)}
              onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(robot.id) } }}>
              {selected && <circle cx={robot.x} cy={robot.y} r={px(21)} fill="#2589F5" opacity="0.12" />}
              <circle cx={robot.x} cy={robot.y + px(2)} r={px(13)} fill="#263545" opacity="0.12" />
              <circle cx={robot.x} cy={robot.y} r={px(13)} fill={selected ? '#E8F4FF' : '#FFF'} stroke={selected ? '#2589F5' : robot.color} strokeWidth={px(selected ? 3 : 2.3)} />
              <path d={`M${robot.x} ${robot.y - px(9)}v${-px(8)}`} transform={`rotate(${robot.heading} ${robot.x} ${robot.y})`} stroke="#273444" strokeWidth={px(2)} strokeLinecap="round" />
              <text x={robot.x} y={robot.y + px(0.5)} textAnchor="middle" dominantBaseline="middle" fontSize={px(8.5)} fontWeight="800" fill="#263545">{robot.id}</text>
            </g>
          })}
        </g>}
      </svg>
      <div className="warehouse-map__tools" aria-label="지도 도구">
        <button title="확대" aria-label="지도 확대" onClick={() => adjustZoom(1.25)}>+</button>
        <button title="축소" aria-label="지도 축소" onClick={() => adjustZoom(0.8)}>−</button>
        <button title="전체 보기" aria-label="지도 전체 보기" onClick={reset}>⊡</button>
        <span>{Math.round(zoom * 100)}%</span>
      </div>
      <button className="warehouse-map__compare" aria-pressed={raw} onClick={() => setRaw(value => !value)}>{raw ? '디자인 지도 보기' : '원본 비교'}</button>
      {picking && <div className="warehouse-map__hint">{raw ? '목표를 선택하려면 디자인 지도로 전환하세요' : '지도에서 이동 목표 노드를 선택하세요'}</div>}
      <div className="warehouse-map__legend">
        <span><i style={{ background: '#8192A5' }} />실제 구조</span>
        <span><i style={{ background: '#B9C3CF' }} />노드·엣지</span>
        <span><i style={{ background: '#2589F5' }} />로봇 경로</span>
        <span><i style={{ background: '#8B6BE8' }} />중첩 경로</span>
      </div>
      <div className="warehouse-map__note">실제 맵 기반 · 로봇/경로는 데모 데이터</div>
    </div>
  )
}

