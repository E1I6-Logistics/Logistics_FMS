import { useState, useEffect, useRef } from 'react'
import WarehouseMap from './WarehouseMap'
import { WarehouseGeometry } from './WarehouseGeometry'

// ── Design tokens ──
const C = {
  bg:      '#EDF1F6',   // page ground — cool gray
  surface: '#FFFFFF',   // cards, panels
  subtle:  '#F4F7FA',   // secondary surfaces: table headers, input bg
  line:    '#DDE3EC',   // hairline borders
  text:    '#191E2B',   // primary text
  muted:   '#677080',   // secondary / label text
  nav:     '#191D24',   // sidebar charcoal
  primary: '#1A6FD8',   // interactive blue — selection + primary action ONLY
  success: '#1FA466',   // operational normal
  warning: '#CC8215',   // caution / wait
  danger:  '#CC2E47',   // error / comms lost
  purple:  '#7255CB',   // ARM-specific accent
  mapBase: '#E4EBF2',   // map canvas
}
// Elevation shadows
const E1 = '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)'      // card
const E2 = '0 3px 10px rgba(0,0,0,0.08), 0 1px 4px rgba(0,0,0,0.05)'     // elevated panel
const E3 = '0 8px 28px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.07)'     // dialog / dropdown
const FONT = "'Noto Sans KR','Malgun Gothic',Arial,sans-serif"
const MONO = "'JetBrains Mono','Courier New',monospace"

const NAV_ITEMS = [
  { id: 'dashboard',   label: '통합 관제',     icon: '⊞' },
  { id: 'robots',      label: '로봇·로봇팔',   icon: '🤖' },
  { id: 'orders',      label: '주문·작업',     icon: '📋' },
  { id: 'alarms',      label: '알람',          icon: '🔔' },
  { id: 'logs',        label: '로그·작업 이력', icon: '📄' },
  { id: 'analytics',   label: '이동시간 분석', icon: '📊' },
]

type LayerKey         = 'nodeEdge' | 'route' | 'station' | 'robotId'
type RobotId          = 'R-01' | 'R-02' | 'R-03'
type TabId            = 'status' | 'task' | 'control'
type CmdState         = 'requesting' | 'approved' | 'rejected' | 'confirmed' | null
type RemoteConn       = 'off' | 'connecting' | 'ready'
type OrderStatus      = '진행 중' | '배차 대기' | '완료' | '실행 불가'
type OrderFilterStatus = 'all' | OrderStatus
type ExecState        = null | 'requesting' | 'waiting' | 'dispatched' | 'rejected'
type AlarmSeverity    = '긴급' | '경고' | '주의' | '정보'
type AlarmState       = '발생 중' | '확인 필요' | '해결됨'
type AlarmFilterType  = 'all' | AlarmState
type AckState         = null | 'requesting' | 'acknowledged'
type HistoryEventType = '배차' | '이동' | '도킹' | '피킹' | '상태 변경' | '주문'
type LogEvType = '배차' | '경로' | '피킹' | '인계' | '제어' | '알람'
interface SLogEntry {
  id: string; ts: string; seq: number
  type: LogEvType; target: string; targetType: 'robot'|'arm'|'task'|'system'
  message: string; isNew?: boolean
  detail: {
    taskId?: string; orderId?: string; robotId?: string
    armId?: string; stationId?: string; route?: string
    duration?: string; ref?: string; operator?: string
  }
}

const LAYERS: { key: LayerKey; label: string }[] = [
  { key: 'nodeEdge', label: '노드·엣지' },
  { key: 'route',    label: '경로' },
  { key: 'station',  label: '구조물 이름' },
  { key: 'robotId',  label: '로봇 ID' },
]

const ROBOT_DATA: Record<RobotId, {
  serial: string; status: string; statusColor: string; statusBg: string
  battery: number; load: string; mode: string; comms: string
  position: string; nextNode: string
  taskId: string; taskStep: string; progress: number
  palettes: string; startTime: string; estOrig: string; estCurr: string; delay: string
}> = {
  'R-01': {
    serial: 'TBM-001', status: '이동 중', statusColor: '#27966e', statusBg: '#E9F8F3',
    battery: 82, load: '적재 중', mode: '자동', comms: '연결됨',
    position: '—', nextNode: '—',
    taskId: 'TK-260913-001', taskStep: '팔레트 1 피킹 중', progress: 45,
    palettes: '팔레트 1', startTime: '09:28:02', estOrig: '09:47:30', estCurr: '09:47:30', delay: '없음',
  },
  'R-02': {
    serial: 'TBM-002', status: '대기', statusColor: '#c98720', statusBg: '#FFF5DF',
    battery: 65, load: '미적재', mode: '자동', comms: '연결됨',
    position: '—', nextNode: '—',
    taskId: '—', taskStep: '배차 대기', progress: 0,
    palettes: '—', startTime: '—', estOrig: '—', estCurr: '—', delay: '—',
  },
  'R-03': {
    serial: 'TBM-003', status: '충전 중', statusColor: '#1675d4', statusBg: '#EDF6FF',
    battery: 23, load: '미적재', mode: '자동', comms: '연결됨',
    position: '충전 CH-1 (위치 미확정)', nextNode: '—',
    taskId: '—', taskStep: '충전 중', progress: 0,
    palettes: '—', startTime: '—', estOrig: '—', estCurr: '—', delay: '—',
  },
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'status',  label: '상태' },
  { id: 'task',    label: '작업' },
  { id: 'control', label: '제어' },
]

// Control commands — ready:false = 준비 중 (not yet implemented in backend)
const CTRL_CMDS = [
  { id: 'assign',   label: '작업 배정',        variant: 'primary',  ready: true,  confirm: false },
  { id: 'nodeMove', label: '특정 노드 이동',   variant: 'default',  ready: true,  confirm: false },
  { id: 'charge',   label: '충전 스테이션 이동', variant: 'default', ready: true,  confirm: false },
  { id: 'stop',     label: '선택 로봇 정지',   variant: 'danger',   ready: true,  confirm: true  },
  { id: 'manual',   label: '수동 모드 전환',   variant: 'warning',  ready: false, confirm: true  },
]

const KEY_ROWS = [
  [{ k: 'Q', l: '좌회전' }, { k: 'W', l: '전진' },  { k: 'E', l: '우회전' }],
  [{ k: 'A', l: '좌이동' }, { k: 'S', l: '후진' },  { k: 'D', l: '우이동' }],
]

// ── Stage 4 data ──
type ArmId = 'ARM-1' | 'ARM-2'
type PackingStatus = '가용' | '예약' | '사용 중'

const ARM_DATA: Record<ArmId, {
  name: string; comms: string; status: string
  statusColor: string; statusBg: string
  palettes: string[]
  currentStep: string; stepProgress: string
  activeTurtleBot: RobotId | null
  doneCount: number; failCount: number
  lastUpdate: string; stale: boolean
}> = {
  'ARM-1': {
    name: '로봇팔 1', comms: '연결됨', status: '작업 중',
    statusColor: '#27966e', statusBg: '#E9F8F3',
    palettes: ['팔레트 1', '팔레트 2'],
    currentStep: '팔레트 1 → R-01 바구니 적재',
    stepProgress: '3 / 6 피킹',
    activeTurtleBot: 'R-01',
    doneCount: 5, failCount: 0,
    lastUpdate: '09:31:22', stale: false,
  },
  'ARM-2': {
    name: '로봇팔 2', comms: '연결됨', status: '대기',
    statusColor: '#c98720', statusBg: '#FFF5DF',
    palettes: ['팔레트 3', '팔레트 4'],
    currentStep: '배차 대기',
    stepProgress: '—',
    activeTurtleBot: null,
    doneCount: 3, failCount: 0,
    lastUpdate: '09:28:44', stale: false,
  },
}

const PACKING_STATIONS: {
  id: string; status: PackingStatus
  statusColor: string; statusBg: string; statusBd: string
  relatedRobot: RobotId | null; taskRef: string | null
  routeCandidate: string | null
}[] = [
  {
    id: 'ST-1', status: '예약',
    statusColor: '#c98720', statusBg: '#FFF5DF', statusBd: '#ECD5AA',
    relatedRobot: 'R-01', taskRef: 'TK-260913-001',
    routeCandidate: null,
  },
  {
    id: 'ST-2', status: '가용',
    statusColor: '#27966e', statusBg: '#E9F8F3', statusBd: '#A8DECE',
    relatedRobot: null, taskRef: null,
    routeCandidate: 'TK-260913-002 경로 후보 (미확정)',
  },
]

const CHARGING_STATIONS = [
  { id: 'CH-1', note: '배치 미확정' },
  { id: 'CH-2', note: '배치 미확정' },
  { id: 'CH-3', note: '배치 미확정' },
]

// ── Stage 5: Orders ──
const TASK_STEPS = ['배차', '팔레트 방문·피킹', '패킹 ST 이동', '물품 인계', '완료']

interface PaletteVisitEntry {
  paletteId: string; armId: ArmId; itemSummary: string
  visitOrder: number; stepStatus: 'done' | 'active' | 'pending'
}
interface OrderEntry {
  id: string; itemSummary: string; qtyTotal: string
  status: OrderStatus; statusColor: string; statusBg: string
  feasible: boolean; blockReason: string | null
  assignedRobot: RobotId | null; currentStepLabel: string
  paletteVisits: PaletteVisitEntry[]
  estimatedPacking: string
  estCompOrig: string; estCompCurr: string; actualComp?: string
  progressStep: number; palettesTotal: number; palettesVisited: number
}

const ORDER_DATA: OrderEntry[] = [
  {
    id: 'ORD-260913-001', itemSummary: '부품 A, 부품 B', qtyTotal: '8개',
    status: '진행 중', statusColor: '#27966e', statusBg: '#E9F8F3',
    feasible: true, blockReason: null, assignedRobot: 'R-01',
    currentStepLabel: '팔레트 1 피킹 중',
    paletteVisits: [
      { paletteId: '팔레트 1', armId: 'ARM-1', itemSummary: '부품 A × 4', visitOrder: 1, stepStatus: 'active'  },
      { paletteId: '팔레트 2', armId: 'ARM-1', itemSummary: '부품 B × 4', visitOrder: 2, stepStatus: 'pending' },
    ],
    estimatedPacking: 'ST-1 (경로 후보 — 미확정)',
    estCompOrig: '09:47:30', estCompCurr: '09:47:30',
    progressStep: 1, palettesTotal: 2, palettesVisited: 0,
  },
  {
    id: 'ORD-260913-002', itemSummary: '부품 C', qtyTotal: '6개',
    status: '배차 대기', statusColor: '#c98720', statusBg: '#FFF5DF',
    feasible: true, blockReason: null, assignedRobot: null,
    currentStepLabel: '배차 대기',
    paletteVisits: [
      { paletteId: '팔레트 3', armId: 'ARM-2', itemSummary: '부품 C × 6', visitOrder: 1, stepStatus: 'pending' },
    ],
    estimatedPacking: '계산 전',
    estCompOrig: '계산 전', estCompCurr: '계산 전',
    progressStep: 0, palettesTotal: 1, palettesVisited: 0,
  },
  {
    id: 'ORD-260913-003', itemSummary: '부품 D, 부품 E', qtyTotal: '4개',
    status: '완료', statusColor: '#1675d4', statusBg: '#EDF6FF',
    feasible: true, blockReason: null, assignedRobot: 'R-01',
    currentStepLabel: '완료',
    paletteVisits: [
      { paletteId: '팔레트 1', armId: 'ARM-1', itemSummary: '부품 D × 2', visitOrder: 1, stepStatus: 'done' },
      { paletteId: '팔레트 2', armId: 'ARM-1', itemSummary: '부품 E × 2', visitOrder: 2, stepStatus: 'done' },
    ],
    estimatedPacking: 'ST-2',
    estCompOrig: '09:20:00', estCompCurr: '09:22:15', actualComp: '09:21:48',
    progressStep: 4, palettesTotal: 2, palettesVisited: 2,
  },
  {
    id: 'ORD-260913-004', itemSummary: '부품 F, 부품 G, 부품 H', qtyTotal: '15개',
    status: '실행 불가', statusColor: '#b52735', statusBg: '#FFF0F2',
    feasible: false,
    blockReason: '단일 TurtleBot 적재 한도(12개) 초과 — 1차에서 주문 분할 미지원',
    assignedRobot: null, currentStepLabel: '실행 불가',
    paletteVisits: [
      { paletteId: '팔레트 1', armId: 'ARM-1', itemSummary: '부품 F × 5', visitOrder: 1, stepStatus: 'pending' },
      { paletteId: '팔레트 2', armId: 'ARM-1', itemSummary: '부품 G × 5', visitOrder: 2, stepStatus: 'pending' },
      { paletteId: '팔레트 4', armId: 'ARM-2', itemSummary: '부품 H × 5', visitOrder: 3, stepStatus: 'pending' },
    ],
    estimatedPacking: '데이터 연결 예정',
    estCompOrig: '—', estCompCurr: '—',
    progressStep: -1, palettesTotal: 3, palettesVisited: 0,
  },
]

// ── Stage 7: Travel-Time Analytics ──
interface ATNode {
  id: string; label: string
  x: number; y: number  // 0–100 percent
  type: 'start' | 'palette' | 'arm' | 'packing' | 'charging' | 'junction'
}
interface ATEdge {
  id: string; seq: number
  fromNode: string; toNode: string
  distM: number
  planMoveSec: number
  actualMoveSec: number | null
  waitBeforeSec: number | null
  status: '완료' | '진행 중' | '대기'
  routeVersion: string   // 'V1', 'V2', 'V1→V2'
  routeChanged: boolean
  delayReason: string | null  // null = 정상, string = cause or '원인 미확인'
}
interface ATTask {
  taskId: string; orderId: string; robotId: RobotId
  taskStatus: '완료' | '진행 중' | '기록 없음'
  planRouteDistM: number
  planMoveTotalSec: number
  actualMoveTotalSec: number | null
  taskStart: string
  estCompOrig: string; estCompCurr: string; actualComp: string | null
  edges: ATEdge[]
  note: string | null
}

// x/y are image-pixel coordinates matching the 135×135 map.png
const AT_NODES: ATNode[] = [
  { id: 'N-HOME',  label: '출발·귀환',   x: 90,  y: 105, type: 'start'    },
  { id: 'N-JCT1',  label: '교차점 J1',  x: 62,  y: 72,  type: 'junction'  },
  { id: 'N-ARM1',  label: 'ARM-1 구역', x: 17,  y: 27,  type: 'arm'       },
  { id: 'N-PAL1',  label: '팔레트 1',   x: 17,  y: 14,  type: 'palette'   },
  { id: 'N-PAL2',  label: '팔레트 2',   x: 17,  y: 40,  type: 'palette'   },
  { id: 'N-ARM2',  label: 'ARM-2 구역', x: 43,  y: 27,  type: 'arm'       },
  { id: 'N-PAL3',  label: '팔레트 3',   x: 43,  y: 14,  type: 'palette'   },
  { id: 'N-PAL4',  label: '팔레트 4',   x: 43,  y: 40,  type: 'palette'   },
  { id: 'N-ST1',   label: '패킹 ST-1',  x: 15,  y: 77,  type: 'packing'   },
  { id: 'N-ST2',   label: '패킹 ST-2',  x: 15,  y: 92,  type: 'packing'   },
  { id: 'N-CH1',   label: '충전 CH-1',  x: 117, y: 65,  type: 'charging'  },
]

const AT_NODE_COLOR: Record<ATNode['type'], string> = {
  start: '#1A6FD8', junction: '#7A8999', arm: '#7255CB',
  palette: '#1FA466', packing: '#CC8215', charging: '#1FA466',
}

const AT_TASKS: ATTask[] = [
  {
    taskId: 'TK-260913-001', orderId: 'ORD-260913-001', robotId: 'R-01',
    taskStatus: '진행 중',
    planRouteDistM: 47.4, planMoveTotalSec: 63,
    actualMoveTotalSec: null,
    taskStart: '09:28:02', estCompOrig: '09:47:30', estCompCurr: '09:48:15', actualComp: null,
    note: '실제 완료 시각은 진행 중 — 전체 작업 시간(이동+피킹+대기)과 이동 시간만의 예상치를 직접 비교할 수 없습니다',
    edges: [
      { id: 'E-01-1', seq: 1, fromNode: 'N-HOME', toNode: 'N-JCT1',
        distM: 9.8, planMoveSec: 12, actualMoveSec: 11,
        waitBeforeSec: 0, status: '완료', routeVersion: 'V1', routeChanged: false, delayReason: null },
      { id: 'E-01-2', seq: 2, fromNode: 'N-JCT1', toNode: 'N-ARM1',
        distM: 17.2, planMoveSec: 18, actualMoveSec: 27,
        waitBeforeSec: 0, status: '완료', routeVersion: 'V1→V2', routeChanged: true,
        delayReason: '경로 편차 감지 후 자동 재계산 (V1 계획 대비 V2로 우회)' },
      { id: 'E-01-3', seq: 3, fromNode: 'N-ARM1', toNode: 'N-PAL1',
        distM: 3.8, planMoveSec: 5, actualMoveSec: 4,
        waitBeforeSec: 2, status: '완료', routeVersion: 'V2', routeChanged: false, delayReason: null },
      { id: 'E-01-4', seq: 4, fromNode: 'N-PAL1', toNode: 'N-PAL2',
        distM: 4.1, planMoveSec: 6, actualMoveSec: null,
        waitBeforeSec: null, status: '진행 중', routeVersion: 'V2', routeChanged: false, delayReason: null },
      { id: 'E-01-5', seq: 5, fromNode: 'N-PAL2', toNode: 'N-ST1',
        distM: 15.2, planMoveSec: 22, actualMoveSec: null,
        waitBeforeSec: null, status: '대기', routeVersion: 'V2', routeChanged: false, delayReason: null },
    ],
  },
  {
    taskId: 'TK-260913-003', orderId: 'ORD-260913-003', robotId: 'R-01',
    taskStatus: '완료',
    planRouteDistM: 47.0, planMoveTotalSec: 61,
    actualMoveTotalSec: 60,
    taskStart: '09:10:00', estCompOrig: '09:20:00', estCompCurr: '09:22:15', actualComp: '09:21:48',
    note: '이동 시간(60s)은 이동 구간만의 합산이며, 작업 완료 시각(09:21:48)은 이동 외 피킹·대기·도킹을 포함합니다',
    edges: [
      { id: 'E-03-1', seq: 1, fromNode: 'N-HOME', toNode: 'N-JCT1',
        distM: 9.8, planMoveSec: 12, actualMoveSec: 12,
        waitBeforeSec: 0, status: '완료', routeVersion: 'V1', routeChanged: false, delayReason: null },
      { id: 'E-03-2', seq: 2, fromNode: 'N-JCT1', toNode: 'N-ARM1',
        distM: 14.5, planMoveSec: 18, actualMoveSec: 17,
        waitBeforeSec: 0, status: '완료', routeVersion: 'V1', routeChanged: false, delayReason: null },
      { id: 'E-03-3', seq: 3, fromNode: 'N-ARM1', toNode: 'N-PAL1',
        distM: 3.8, planMoveSec: 5, actualMoveSec: 5,
        waitBeforeSec: 1, status: '완료', routeVersion: 'V1', routeChanged: false, delayReason: null },
      { id: 'E-03-4', seq: 4, fromNode: 'N-PAL1', toNode: 'N-PAL2',
        distM: 4.1, planMoveSec: 6, actualMoveSec: 6,
        waitBeforeSec: 1, status: '완료', routeVersion: 'V1', routeChanged: false, delayReason: null },
      { id: 'E-03-5', seq: 5, fromNode: 'N-PAL2', toNode: 'N-ST2',
        distM: 14.8, planMoveSec: 20, actualMoveSec: 20,
        waitBeforeSec: 0, status: '완료', routeVersion: 'V1', routeChanged: false, delayReason: null },
    ],
  },
  {
    taskId: '—', orderId: 'ORD-260913-002', robotId: 'R-02',
    taskStatus: '기록 없음',
    planRouteDistM: 0, planMoveTotalSec: 0, actualMoveTotalSec: null,
    taskStart: '—', estCompOrig: '계산 전', estCompCurr: '계산 전', actualComp: null,
    note: null, edges: [],
  },
]

// ── Stage 6: Alarms & History ──
interface AlarmEntry {
  id: string; severity: AlarmSeverity
  target: string; targetId: string | null; targetType: 'robot' | 'arm' | 'system'
  location: string; content: string; state: AlarmState
  occurredAt: string; updatedAt: string
  relatedTaskId: string | null; relatedOrderId: string | null
  deviceStateAtTime: string; description: string
}
interface HistoryEntry {
  id: string; time: string
  target: string; targetId: string | null; targetType: 'robot' | 'arm' | 'system'
  eventType: HistoryEventType; description: string
  relatedRobotId: string | null; relatedOrderId: string | null
}

const SEVERITY_CFG: Record<AlarmSeverity, { color: string; bg: string; bd: string }> = {
  '긴급': { color: '#B02038', bg: '#FEF0F3', bd: '#EDAAB6' },
  '경고': { color: '#8C5A0A', bg: '#FEF4E1', bd: '#E4C070' },
  '주의': { color: '#1155A8', bg: '#E8F1FF', bd: '#9DC4F0' },
  '정보': { color: '#50606F', bg: '#F2F5F9', bd: '#CDD5DF' },
}
const STATE_CFG: Record<AlarmState, { color: string; bg: string; bd: string }> = {
  '발생 중':  { color: '#B02038', bg: '#FEF0F3', bd: '#EDAAB6' },
  '확인 필요': { color: '#8C5A0A', bg: '#FEF4E1', bd: '#E4C070' },
  '해결됨':   { color: '#50606F', bg: '#F2F5F9', bd: '#CDD5DF' },
}
const EVT_CFG: Partial<Record<HistoryEventType, { color: string; bg: string }>> = {
  '배차':    { color: '#1155A8', bg: '#E8F1FF' },
  '이동':    { color: '#147A4E', bg: '#E4F6EF' },
  '피킹':    { color: '#5E3FB3', bg: '#EDE8FF' },
  '도킹':    { color: '#8C5A0A', bg: '#FEF4E1' },
  '상태 변경': { color: '#B02038', bg: '#FEF0F3' },
  '주문':    { color: '#50606F', bg: '#F2F5F9' },
}
const HIST_TYPES: string[]   = ['all', '배차', '이동', '피킹', '도킹', '상태 변경', '주문']
const HIST_TARGETS: string[] = ['all', 'R-01', 'R-02', 'R-03', 'ARM-1', 'ARM-2', '시스템']

const ALARM_DATA: AlarmEntry[] = [
  {
    id: 'ALM-001', severity: '긴급',
    target: 'R-03', targetId: 'R-03', targetType: 'robot',
    location: '충전 구역 (위치 미확정)',
    content: '배터리 저하 경고 — 23%',
    state: '확인 필요',
    occurredAt: '09:31:14', updatedAt: '09:31:14',
    relatedTaskId: null, relatedOrderId: null,
    deviceStateAtTime: '충전 중',
    description: 'R-03의 배터리 잔량이 임계값(25%) 이하로 감소했습니다. 현재 충전 중이나 충전 속도 이상이 의심됩니다. 충전 케이블 및 CH-1 장비 상태 현장 확인을 권장합니다.',
  },
  {
    id: 'ALM-002', severity: '경고',
    target: 'ARM-1', targetId: 'ARM-1', targetType: 'arm',
    location: '팔레트 1 구역',
    content: '피킹 동작 지연 — 4번째 물품 피킹 후 응답 없음',
    state: '발생 중',
    occurredAt: '09:33:05', updatedAt: '09:33:05',
    relatedTaskId: 'TK-260913-001', relatedOrderId: 'ORD-260913-001',
    deviceStateAtTime: '상태 확인 불가 (피킹 일시 정지 후 응답 없음)',
    description: 'ARM-1이 팔레트 1의 4번째 물품 피킹 중 예상 시간을 초과했으며 응답이 없습니다. 물품 위치 편차 또는 ARM-1 제어기 일시 오류가 원인으로 추정됩니다. 통신이 끊긴 장치의 상태는 단정할 수 없으며 백엔드 확인 및 현장 점검이 필요합니다.',
  },
  {
    id: 'ALM-003', severity: '주의',
    target: 'R-01', targetId: 'R-01', targetType: 'robot',
    location: '정보 없음',
    content: '경로 편차 감지 — 자동 복구 완료',
    state: '해결됨',
    occurredAt: '09:29:52', updatedAt: '09:30:11',
    relatedTaskId: 'TK-260913-001', relatedOrderId: 'ORD-260913-001',
    deviceStateAtTime: '이동 중',
    description: 'R-01이 예정 경로에서 편차를 감지했습니다. 로봇이 자동으로 경로를 재계산하여 09:30:11에 복구 완료했습니다. 동일 상황 반복 시 경로 재검토가 필요합니다.',
  },
  {
    id: 'ALM-004', severity: '정보',
    target: '시스템', targetId: null, targetType: 'system',
    location: '—',
    content: 'TK-260913-001 배차 완료',
    state: '해결됨',
    occurredAt: '09:28:02', updatedAt: '09:28:02',
    relatedTaskId: 'TK-260913-001', relatedOrderId: 'ORD-260913-001',
    deviceStateAtTime: '정보 없음',
    description: '작업 TK-260913-001이 R-01에 성공적으로 배차되었습니다. 이후 진행 이력은 이벤트 이력 탭에서 확인할 수 있습니다.',
  },
]

const HISTORY_DATA: HistoryEntry[] = [
  { id:'EVT-001', time:'09:28:02', target:'R-01',   targetId:'R-01',   targetType:'robot',  eventType:'배차',    description:'TK-260913-001 배차 완료 — R-01 출발 준비',           relatedRobotId:'R-01',   relatedOrderId:'ORD-260913-001' },
  { id:'EVT-002', time:'09:28:15', target:'R-01',   targetId:'R-01',   targetType:'robot',  eventType:'이동',    description:'팔레트 1 구역으로 이동 시작 (경로 미확정)',          relatedRobotId:'R-01',   relatedOrderId:null },
  { id:'EVT-003', time:'09:29:40', target:'ARM-1',  targetId:'ARM-1',  targetType:'arm',    eventType:'피킹',    description:'팔레트 1 피킹 시작 — 부품 A × 4',                   relatedRobotId:'R-01',   relatedOrderId:'ORD-260913-001' },
  { id:'EVT-004', time:'09:29:52', target:'R-01',   targetId:'R-01',   targetType:'robot',  eventType:'이동',    description:'경로 편차 감지 → 자동 재계산 시작',                 relatedRobotId:'R-01',   relatedOrderId:null },
  { id:'EVT-005', time:'09:30:11', target:'R-01',   targetId:'R-01',   targetType:'robot',  eventType:'이동',    description:'경로 복구 완료 — 팔레트 1 구역 이동 재개',           relatedRobotId:'R-01',   relatedOrderId:null },
  { id:'EVT-006', time:'09:31:14', target:'R-03',   targetId:'R-03',   targetType:'robot',  eventType:'상태 변경', description:'배터리 23% — 저하 경고 발생',                      relatedRobotId:'R-03',   relatedOrderId:null },
  { id:'EVT-007', time:'09:31:22', target:'ARM-1',  targetId:'ARM-1',  targetType:'arm',    eventType:'피킹',    description:'팔레트 1 · 3/6 피킹 완료',                         relatedRobotId:'R-01',   relatedOrderId:'ORD-260913-001' },
  { id:'EVT-008', time:'09:33:05', target:'ARM-1',  targetId:'ARM-1',  targetType:'arm',    eventType:'피킹',    description:'4번째 물품 피킹 지연 — 응답 없음 (알람 ALM-002 발생)', relatedRobotId:null,    relatedOrderId:'ORD-260913-001' },
]

// ══════════════════════════════════════
// LogsScreen data + config
// ══════════════════════════════════════
const LOG_EVT_CFG: Record<LogEvType, { label:string; color:string; bg:string; bd:string }> = {
  '배차': { label:'배차', color:'#1A6FD8', bg:'#EBF3FF', bd:'#91C0F8' },
  '경로': { label:'경로', color:'#0B5FAD', bg:'#E0EEFF', bd:'#7DB5F0' },
  '피킹': { label:'피킹', color:'#1A7A55', bg:'#E4F6EF', bd:'#88D5B3' },
  '인계': { label:'인계', color:'#167B52', bg:'#E8FBF2', bd:'#8AD5B5' },
  '제어': { label:'제어', color:'#5E3FB3', bg:'#F0ECFF', bd:'#C4B0F0' },
  '알람': { label:'알람', color:'#B02038', bg:'#FEF0F3', bd:'#EDAAB6' },
}

const LOG_ICONS: Record<LogEvType, React.ReactNode> = {
  '배차': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M1.5 4.5H7M4.8 2.5L7 4.5 4.8 6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>),
  '경로': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><circle cx="2" cy="7" r="1.1" stroke="currentColor" strokeWidth="1"/><circle cx="7" cy="2" r="1.1" stroke="currentColor" strokeWidth="1"/><path d="M2.8 6.4 Q2.8 3.5 6 2.8" stroke="currentColor" strokeWidth="1" fill="none"/></svg>),
  '피킹': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M4.5 1V5.5M2.5 3.5L4.5 5.5 6.5 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/><line x1="1.5" y1="7.5" x2="7.5" y2="7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>),
  '인계': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M1.5 5H5M4 3.5L5.5 5 4 6.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 4H7.5M6 2.5L7.5 4 6 5.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round"/></svg>),
  '제어': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><circle cx="4.5" cy="4.5" r="1.4" stroke="currentColor" strokeWidth="1"/><path d="M4.5 1.3v1.1M4.5 6.6v1.1M1.3 4.5h1.1M6.6 4.5h1.1" stroke="currentColor" strokeWidth="1" strokeLinecap="round"/></svg>),
  '알람': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M4.5 1L8 7.5H1L4.5 1Z" stroke="currentColor" strokeWidth="1" fill="none" strokeLinejoin="round"/><line x1="4.5" y1="4" x2="4.5" y2="5.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/><circle cx="4.5" cy="6.5" r="0.4" fill="currentColor"/></svg>),
}

const SESSION_LOG: SLogEntry[] = [
  { id:'L025', ts:'09:33:22', seq:25, type:'제어',  target:'ARM-1',         targetType:'arm',    message:'관리자 ARM-1 피킹 재개 명령 — 수동 재시도',                 detail:{ armId:'ARM-1', operator:'관리자', ref:'ALM-002' } },
  { id:'L024', ts:'09:33:05', seq:24, type:'알람',  target:'ARM-1',         targetType:'arm',    message:'피킹 동작 지연 — 4번째 물품 응답 없음 · ALM-002 발생',       detail:{ armId:'ARM-1', taskId:'TK-260913-001', orderId:'ORD-260913-001', ref:'ALM-002' } },
  { id:'L023', ts:'09:32:51', seq:23, type:'인계',  target:'R-01',          targetType:'robot',  message:'R-01 → ST-1 인계 대기 중 · TK-260913-001',                  detail:{ robotId:'R-01', stationId:'ST-1', taskId:'TK-260913-001' } },
  { id:'L022', ts:'09:32:38', seq:22, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 · 3/6 피킹 완료',                                   detail:{ armId:'ARM-1', taskId:'TK-260913-001', orderId:'ORD-260913-001', duration:'68 s' } },
  { id:'L021', ts:'09:32:21', seq:21, type:'제어',  target:'R-02',          targetType:'robot',  message:'수동 → 자동 모드 전환 승인',                                 detail:{ robotId:'R-02', operator:'관리자' } },
  { id:'L020', ts:'09:32:08', seq:20, type:'경로',  target:'R-02',          targetType:'robot',  message:'TK-260913-002 · R-02 초기 경로 계산 시작',                   detail:{ robotId:'R-02', taskId:'TK-260913-002', route:'HOME → J12 → J5 → J4 → PA2' } },
  { id:'L019', ts:'09:31:55', seq:19, type:'배차',  target:'TK-260913-002', targetType:'task',   message:'TK-260913-002 → R-02 배차 예약 (확정 대기)',                  detail:{ robotId:'R-02', taskId:'TK-260913-002', orderId:'ORD-260913-002' } },
  { id:'L018', ts:'09:31:44', seq:18, type:'인계',  target:'R-03',          targetType:'robot',  message:'R-03 CH-1 도착 확인 — 충전 시작',                             detail:{ robotId:'R-03', stationId:'CH-1', duration:'연결 확인 중' } },
  { id:'L017', ts:'09:31:29', seq:17, type:'경로',  target:'R-03',          targetType:'robot',  message:'R-03 → CH-1 충전 경로 확정',                                  detail:{ robotId:'R-03', route:'J12 → J6 → J7 → C1', duration:'18 s 예상' } },
  { id:'L016', ts:'09:31:14', seq:16, type:'알람',  target:'R-03',          targetType:'robot',  message:'배터리 23% 저하 경고 · ALM-001 발생',                         detail:{ robotId:'R-03', ref:'ALM-001' } },
  { id:'L015', ts:'09:31:02', seq:15, type:'제어',  target:'R-03',          targetType:'robot',  message:'충전 스테이션 이동 명령 (배터리 임계값 도달)',                  detail:{ robotId:'R-03', stationId:'CH-1', operator:'시스템 자동' } },
  { id:'L014', ts:'09:30:48', seq:14, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 · 2/6 피킹 완료',                                    detail:{ armId:'ARM-1', taskId:'TK-260913-001', orderId:'ORD-260913-001', duration:'47 s' } },
  { id:'L013', ts:'09:30:33', seq:13, type:'경로',  target:'R-01',          targetType:'robot',  message:'경로 재계산 완료 — 편차 복구 후 팔레트 1 이동 재개',             detail:{ robotId:'R-01', route:'J5 → J4 → PA2', duration:'11 s 복구' } },
  { id:'L012', ts:'09:30:11', seq:12, type:'알람',  target:'R-01',          targetType:'robot',  message:'경로 편차 자동 복구 완료 · ALM-003 해결됨',                    detail:{ robotId:'R-01', ref:'ALM-003', duration:'19 s 소요' } },
  { id:'L011', ts:'09:29:52', seq:11, type:'알람',  target:'R-01',          targetType:'robot',  message:'경로 편차 감지 — 자동 재계산 시작 · ALM-003 발생',              detail:{ robotId:'R-01', ref:'ALM-003' } },
  { id:'L010', ts:'09:29:40', seq:10, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 피킹 시작 — 부품 A × 6',                              detail:{ armId:'ARM-1', taskId:'TK-260913-001', orderId:'ORD-260913-001' } },
  { id:'L009', ts:'09:29:22', seq:9,  type:'경로',  target:'R-01',          targetType:'robot',  message:'팔레트 1 구역 진입 경로 확정',                                  detail:{ robotId:'R-01', route:'J5 → J4 → J2 → PA1', duration:'24 s 예상' } },
  { id:'L008', ts:'09:29:08', seq:8,  type:'인계',  target:'R-01',          targetType:'robot',  message:'R-01 ARM-1 구역 도착 · 피킹 대기',                             detail:{ robotId:'R-01', armId:'ARM-1', taskId:'TK-260913-001' } },
  { id:'L007', ts:'09:28:55', seq:7,  type:'제어',  target:'시스템',         targetType:'system', message:'관리자 관제 모드 진입 (권한 레벨 2)',                           detail:{ operator:'관리자' } },
  { id:'L006', ts:'09:28:44', seq:6,  type:'배차',  target:'TK-260913-001', targetType:'task',   message:'TK-260913-001 → R-01 배차 확정',                               detail:{ robotId:'R-01', taskId:'TK-260913-001', orderId:'ORD-260913-001' } },
  { id:'L005', ts:'09:28:31', seq:5,  type:'경로',  target:'R-01',          targetType:'robot',  message:'TK-260913-001 · R-01 초기 경로 생성',                           detail:{ robotId:'R-01', taskId:'TK-260913-001', route:'HOME → J12 → J5 → PA1', duration:'31 s 예상' } },
  { id:'L004', ts:'09:28:18', seq:4,  type:'배차',  target:'TK-260913-001', targetType:'task',   message:'작업 TK-260913-001 생성 (주문 ORD-260913-001)',                  detail:{ taskId:'TK-260913-001', orderId:'ORD-260913-001' } },
  { id:'L003', ts:'09:28:10', seq:3,  type:'제어',  target:'ARM-2',         targetType:'arm',    message:'ARM-2 준비 완료 — 배차 대기',                                   detail:{ armId:'ARM-2' } },
  { id:'L002', ts:'09:28:07', seq:2,  type:'제어',  target:'ARM-1',         targetType:'arm',    message:'ARM-1 준비 완료 — 배차 대기',                                   detail:{ armId:'ARM-1' } },
  { id:'L001', ts:'09:28:05', seq:1,  type:'제어',  target:'시스템',         targetType:'system', message:'FMS 세션 시작 (v3.2.1) · 로봇 3대 연결됨',                     detail:{ operator:'시스템' } },
]

const LIVE_LOG_QUEUE: SLogEntry[] = [
  { id:'L026', ts:'09:33:37', seq:26, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 · ARM-1 피킹 재시작 — 4번째 물품',               detail:{ armId:'ARM-1', taskId:'TK-260913-001', ref:'ALM-002' } },
  { id:'L027', ts:'09:33:52', seq:27, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 · 4/6 피킹 완료',                               detail:{ armId:'ARM-1', taskId:'TK-260913-001', duration:'91 s' } },
  { id:'L028', ts:'09:34:08', seq:28, type:'경로',  target:'R-02',          targetType:'robot',  message:'TK-260913-002 · R-02 경로 확정 완료',                     detail:{ robotId:'R-02', taskId:'TK-260913-002', route:'HOME → J12 → J5 → J4 → PA2', duration:'26 s 예상' } },
  { id:'L029', ts:'09:34:21', seq:29, type:'배차',  target:'TK-260913-002', targetType:'task',   message:'TK-260913-002 배차 확정 · R-02 출발',                     detail:{ robotId:'R-02', taskId:'TK-260913-002', orderId:'ORD-260913-002' } },
]

// ── Node picker (shared between map canvas and ControlTab) ──
type MapNodeId = 'N1'|'N2'|'N3'|'N4'|'N5'|'N6'|'N7'|'N8'|'N9'|'N10'|'N11'|'N12'|'N13'|'N14'
const MAP_NODES: Record<MapNodeId, {x:number;y:number}> = {
  N1: {x:86,  y:61},  N2:  {x:65,  y:61},  N3:  {x:37,  y:61},
  N4: {x:37,  y:43},  N5:  {x:37,  y:14},  N6:  {x:65,  y:14},
  N7: {x:86,  y:14},  N8:  {x:86,  y:43},  N9:  {x:86,  y:86},
  N10:{x:86,  y:111}, N11: {x:65,  y:82},  N12: {x:37,  y:82},
  N13:{x:65,  y:111}, N14: {x:37,  y:111},
}
interface NodePickerItem { id: string; label: string; mapNodeId: MapNodeId }
const NODE_PICKER_GROUPS: { title: string; items: NodePickerItem[] }[] = [
  {
    title: '경로 노드',
    items: (Object.keys(MAP_NODES) as MapNodeId[]).map(id => ({ id, label: id, mapNodeId: id })),
  },
  {
    title: '설비 접근 노드',
    items: [
      { id: 'FAC_PAL1', label: '팔레트 1',  mapNodeId: 'N4'  },
      { id: 'FAC_PAL2', label: '팔레트 2',  mapNodeId: 'N6'  },
      { id: 'FAC_PAL3', label: '팔레트 3',  mapNodeId: 'N3'  },
      { id: 'FAC_PAL4', label: '팔레트 4',  mapNodeId: 'N2'  },
      { id: 'FAC_ARM1', label: '로봇팔 1',  mapNodeId: 'N4'  },
      { id: 'FAC_ARM2', label: '로봇팔 2',  mapNodeId: 'N4'  },
      { id: 'FAC_CH1',  label: '충전 CH-1', mapNodeId: 'N1'  },
      { id: 'FAC_CH2',  label: '충전 CH-2', mapNodeId: 'N9'  },
      { id: 'FAC_CH3',  label: '충전 CH-3', mapNodeId: 'N10' },
      { id: 'FAC_ST1',  label: '패킹 ST-1', mapNodeId: 'N12' },
      { id: 'FAC_ST2',  label: '패킹 ST-2', mapNodeId: 'N14' },
    ],
  },
]

function useWindowWidth() {
  const [w, setW] = useState(window.innerWidth)
  useEffect(() => {
    const fn = () => setW(window.innerWidth)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return w
}

// ─────────────────────────────────────────────
export default function App() {
  const [time, setTime]                 = useState(new Date())
  const [activeNav, setActiveNav]       = useState('dashboard')
  const vw = useWindowWidth()
  const [layers, setLayers]             = useState<Record<LayerKey, boolean>>({ nodeEdge: true, route: true, station: true, robotId: true })
  const [selectedRobot, setSelected]    = useState<RobotId | null>(null)
  const [activeTab, setActiveTab]       = useState<TabId>('status')
  const [remoteExpanded, setRemoteEx]   = useState(true)
  const [remoteOn, setRemoteOn]         = useState(false)
  const [isAdmin, setIsAdmin]           = useState(false)
  const [isMapEdit, setIsMapEdit]       = useState(false)
  const [bottomH, setBottomH]           = useState(118)
  const [bottomVisible, setBottomVis]   = useState(false)
  // ── Step 3 additions ──
  const [remoteConn, setRemoteConn]     = useState<RemoteConn>('off')
  const [cmdState, setCmdState]         = useState<CmdState>(null)
  const [pendingCmd, setPendingCmd]     = useState<string | null>(null)
  const [confirmDlg, setConfirmDlg]     = useState<string | null>(null)
  const [simCommsLost, setSimLost]      = useState(false)
  const [analyticsTaskId, setAnalyticsTaskId] = useState<string | undefined>(undefined)
  const [nodeMoveTarget, setNodeMoveTarget]   = useState<NodePickerItem | null>(null)
  const [nodeMovePickerOpen, setNodeMovePickerOpen] = useState(false)

  const cmdTimers = useRef<number[]>([])
  const clearCmdTimers = () => { cmdTimers.current.forEach(clearTimeout); cmdTimers.current = [] }

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  // Remote connection simulation
  useEffect(() => {
    if (remoteOn && isAdmin && !simCommsLost) {
      setRemoteConn('connecting')
      const t = window.setTimeout(() => setRemoteConn('ready'), 1500)
      return () => clearTimeout(t)
    } else {
      setRemoteConn('off')
    }
  }, [remoteOn, isAdmin, simCommsLost])

  // Auto-reset when leaving admin mode
  useEffect(() => {
    if (!isAdmin) {
      setRemoteOn(false); setRemoteConn('off')
      setCmdState(null); setPendingCmd(null); setConfirmDlg(null)
      clearCmdTimers()
    }
  }, [isAdmin])

  // Auto-reset when comms lost
  useEffect(() => {
    if (simCommsLost) {
      setRemoteOn(false); setRemoteConn('off')
      setCmdState(null); setPendingCmd(null); setConfirmDlg(null)
      clearCmdTimers()
    }
  }, [simCommsLost])

  const clock = time.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  const toggleLayer = (k: LayerKey) => setLayers(p => ({ ...p, [k]: !p[k] }))

  const resetCmdState = () => {
    setCmdState(null); setPendingCmd(null); setConfirmDlg(null); clearCmdTimers()
    setNodeMoveTarget(null); setNodeMovePickerOpen(false)
  }

  const handleSelect = (id: RobotId) => {
    if (id !== selectedRobot) {
      setRemoteOn(false); setRemoteConn('off'); setSimLost(false)
      resetCmdState()
    }
    setSelected(id); setActiveTab('status')
  }
  const handleClose = () => {
    setSelected(null); setRemoteOn(false); setRemoteConn('off')
    setSimLost(false); resetCmdState()
  }

  const executeCmd = (id: string) => {
    setConfirmDlg(null); setPendingCmd(id); setCmdState('requesting')
    clearCmdTimers()
    const t1 = window.setTimeout(() => {
      // simulate backend: reject if comms lost, else approve
      if (simCommsLost) { setCmdState('rejected'); return }
      setCmdState('approved')
      const t2 = window.setTimeout(() => setCmdState('confirmed'), 900)
      cmdTimers.current.push(t2)
    }, 1400)
    cmdTimers.current.push(t1)
  }

  const handleCmd = (id: string, confirm: boolean) => {
    if (simCommsLost) { setPendingCmd(id); setCmdState('rejected'); return }
    if (confirm) { setConfirmDlg(id) } else { executeCmd(id) }
  }

  const listWidth  = selectedRobot ? 64 : 215
  const keysActive = isAdmin && remoteOn && remoteConn === 'ready' && !simCommsLost

  const isMobile  = vw < 480
  const isNarrow  = vw < 1024   // icon-rail nav
  const isSmall   = vw < 768    // stack map+detail, hide bottom panel by default
  const navW      = isMobile ? 0 : isNarrow ? 52 : 188

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: C.bg, fontFamily: FONT, fontSize: 13, color: C.text }}>

      {/* ══ LEFT NAV (hidden on mobile, icon-rail on tablet) ══ */}
      {!isMobile && (
      <aside className="fms-left-nav" style={{ width: navW, background: C.nav, flexDirection: 'column', flexShrink: 0, boxShadow: '2px 0 8px rgba(0,0,0,0.18)', transition: 'width 0.2s' }}>
        {/* Logo / wordmark */}
        <div style={{ padding: isNarrow ? '12px 0' : '14px 16px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: isNarrow ? 'center' : 'flex-start' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(140deg,#1A6FD8 0%,#3FA3F5 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 9.5, color: '#fff', flexShrink: 0, boxShadow: '0 2px 6px rgba(26,111,216,0.4)', letterSpacing: '0.02em' }}>FMS</div>
            {!isNarrow && <div>
              <div style={{ color: '#E8EDF4', fontWeight: 700, fontSize: 12, lineHeight: 1.25, letterSpacing: '-0.01em' }}>E1I6 FMS</div>
              <div style={{ color: '#4C5563', fontSize: 9, marginTop: 2, fontWeight: 500 }}>물류센터 관제</div>
            </div>}
          </div>
        </div>
        {/* Navigation */}
        <nav style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
          {NAV_ITEMS.map(item => {
            const a = activeNav === item.id
            return (
              <button key={item.id} onClick={() => setActiveNav(item.id)} title={isNarrow ? item.label : undefined}
                style={{ display: 'flex', alignItems: 'center', justifyContent: isNarrow ? 'center' : 'flex-start', width: '100%', padding: isNarrow ? '10px 0' : '8px 16px', marginBottom: 1, border: 'none', cursor: 'pointer', textAlign: 'left', background: a ? 'rgba(26,111,216,0.16)' : 'transparent', borderLeft: isNarrow ? 'none' : `3px solid ${a ? '#1A6FD8' : 'transparent'}`, borderRight: isNarrow ? `3px solid ${a ? '#3FA3F5' : 'transparent'}` : 'none', color: a ? '#6DB8FF' : '#7A8799', fontSize: isNarrow ? 16 : 12, fontWeight: a ? 700 : 400, outline: 'none' }}>
                {isNarrow
                  ? <span title={item.label}>{item.icon}</span>
                  : <><span style={{ width: 5, height: 5, borderRadius: '50%', background: a ? '#3FA3F5' : 'rgba(255,255,255,0.14)', display: 'inline-block', marginRight: 10, flexShrink: 0, boxShadow: a ? '0 0 0 3px rgba(63,163,245,0.2)' : 'none' }} />{item.label}</>
                }
              </button>
            )
          })}
        </nav>
        {!isNarrow && <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(255,255,255,0.05)', color: '#343B46', fontSize: 8.5, fontFamily: MONO, letterSpacing: '0.02em' }}>v1.0.0-alpha · 1차</div>}
      </aside>
      )}

      {/* ══ MAIN ══ */}
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', minWidth: 0 }}>

        {/* ── HEADER ── */}
        <header style={{ height: 46, background: isAdmin ? '#FFFCF2' : C.surface, borderBottom: `1px solid ${isAdmin ? '#EBD49C' : C.line}`, padding: '0 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, transition: 'background 0.2s, border-color 0.2s', boxShadow: isAdmin ? '0 1px 0 rgba(212,136,30,0.12)' : '0 1px 0 rgba(0,0,0,0.04)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontWeight: 900, fontSize: 13.5, letterSpacing: '-0.03em', color: C.text }}>E1I6 물류센터 FMS</span>
            <span style={{ width: 1, height: 14, background: C.line, display: 'inline-block' }} />
            <span style={{ fontFamily: MONO, fontSize: 11, color: C.muted, letterSpacing: '0.03em', fontWeight: 500 }}>{clock}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.success, display: 'inline-block', animation: 'pulse-dot 2.4s ease-in-out infinite' }} />
              <span style={{ fontSize: 10.5, color: C.success, fontWeight: 600 }}>데모 · 서버 미연결</span>
            </div>
            <Div />
            <button onClick={() => setIsAdmin(p => !p)} title="데모: 관리자 모드 전환"
              style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 11px', borderRadius: 6, background: isAdmin ? '#FEF3DC' : C.subtle, border: `1px solid ${isAdmin ? '#D4A842' : C.line}`, fontSize: 10, fontWeight: 700, color: isAdmin ? '#8C5E0A' : C.muted, cursor: 'pointer', outline: 'none', boxShadow: isAdmin ? '0 0 0 2px rgba(212,136,30,0.15)' : E1 }}>
              <span style={{ fontSize: 10 }}>{isAdmin ? '⚙' : '○'}</span>
              {isAdmin ? '관리자 모드' : '일반 모드'}
            </button>
          </div>
        </header>

        {/* ── STATUS CHIPS ── */}
        <div style={{ height: 36, background: isAdmin ? '#FDF8EE' : C.subtle, borderBottom: `1px solid ${isAdmin ? '#E8CF98' : C.line}`, padding: '0 20px', display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, transition: 'background 0.2s' }}>
          <SChip label="전체 로봇" value="3" />
          <Div />
          <SChip label="작업 중" value="2" dot={C.success} vc={{ color: '#147A4E', fontWeight: 800 }} bg="#E5F8EF" bd="#9ED9BD" />
          <SChip label="대기" value="1" dot={C.warning} vc={{ color: '#8C5A0A', fontWeight: 800 }} bg="#FEF5E0" bd="#E5C87E" />
          <SChip label="충전 중" value="0" dot={C.primary} vc={{ color: '#11509E', fontWeight: 800 }} bg="#EAF3FF" bd="#A8CAEF" />
          <Div />
          <SChip label="미처리 알람" value="1" dot={C.danger} vc={{ color: '#991E35', fontWeight: 800 }} bg="#FEF0F2" bd="#EDADB8" />
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 9.5, color: C.muted, fontWeight: 500 }}>로봇팔</span>
            <ArmChip id="ARM-1" status="작업 중" color={C.success} />
            <ArmChip id="ARM-2" status="대기" color={C.warning} />
          </div>
        </div>

        {/* ── BODY ── */}
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0, flexDirection: isSmall && activeNav === 'dashboard' ? 'column' : 'row' }}>

          {activeNav === 'robots' ? (
            <RobotsArmsScreen onSelectRobot={(id) => { handleSelect(id); setActiveNav('dashboard') }} />
          ) : activeNav === 'orders' ? (
            <OrdersScreen
              isAdmin={isAdmin}
              onNavigateToRobot={(id) => { handleSelect(id); setActiveNav('dashboard') }}
              onNavigateToAnalytics={(taskId) => { setAnalyticsTaskId(taskId); setActiveNav('analytics') }}
            />
          ) : activeNav === 'alarms' ? (
            <AlarmsScreen
              isAdmin={isAdmin}
              onNavigateToRobot={(id) => { handleSelect(id); setActiveNav('dashboard') }}
              onNavigateToOrder={() => setActiveNav('orders')}
            />
          ) : activeNav === 'analytics' ? (
            <AnalyticsScreen initialTaskId={analyticsTaskId} />
          ) : activeNav === 'logs' ? (
            <LogsScreen />
          ) : (<>
          {/* Robot list */}
          <aside style={{ width: listWidth, background: C.surface, borderRight: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden', transition: 'width 0.22s ease' }}>
            {selectedRobot ? (
              <div style={{ flex: 1, overflowY: 'auto', padding: '10px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7 }}>
                <div style={{ fontSize: 8, color: '#C0C8D0', textAlign: 'center', marginBottom: 2, lineHeight: 1.4 }}>로봇<br />목록</div>
                {(['R-01', 'R-02', 'R-03'] as RobotId[]).map(id => {
                  const r = ROBOT_DATA[id]; const sel = selectedRobot === id
                  return (
                    <button key={id} onClick={() => handleSelect(id)} title={`${id} · ${r.status}`}
                      style={{ width: 40, height: 40, borderRadius: '50%', background: sel ? '#EDF6FF' : '#F8FAFC', border: `2.5px solid ${sel ? C.primary : r.statusColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 10, color: sel ? C.primary : C.text, cursor: 'pointer', outline: 'none', boxShadow: sel ? '0 0 0 3px rgba(37,137,245,0.15)' : 'none', transition: 'all 0.12s', flexShrink: 0 }}>
                      {id.replace('R-', '')}
                    </button>
                  )
                })}
              </div>
            ) : (
              <>
                <div style={{ padding: '10px 12px 8px', borderBottom: '1px solid #EDF0F3', flexShrink: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 7 }}>
                    <span style={{ fontWeight: 800, fontSize: 12 }}>TurtleBot 목록</span>
                    <span style={{ fontSize: 9, color: C.muted, fontWeight: 600 }}>3 / 3 대</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', background: '#F7F9FB', border: '1px solid #E4E8ED', borderRadius: 7 }}>
                    <SearchIcon />
                    <span style={{ fontSize: 10, color: '#C0C8D0' }}>ID 또는 상태 검색</span>
                  </div>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
                  {(['R-01', 'R-02', 'R-03'] as RobotId[]).map(id => {
                    const r = ROBOT_DATA[id]
                    return <RobotCard key={id} id={id} serial={r.serial} status={r.status} statusColor={r.statusColor} statusBg={r.statusBg} battery={r.battery} task={r.taskId} selected={selectedRobot === id} onClick={() => handleSelect(id)} />
                  })}
                </div>
              </>
            )}
          </aside>

          {/* ── MAP — Topology Canvas ── */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#E7EBF0', minWidth: 0 }}>

            {/* ── Layer header ── */}
            <div style={{ height: 38, background: C.surface, borderBottom: `1px solid ${C.line}`, padding: '0 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 800, color: C.text, marginRight: 4 }}>센터 A · 1층</span>
                <span style={{ fontSize: 8, fontWeight: 700, background: '#E6F9F3', color: '#1A8A60', border: '1px solid #9DE5CB', borderRadius: 4, padding: '1px 6px' }}>데모</span>
                <span style={{ width: 1, height: 16, background: C.line, margin: '0 8px' }} />
                <span style={{ fontSize: 9, color: C.muted, fontWeight: 600, marginRight: 4, letterSpacing: '0.04em' }}>레이어</span>
                {LAYERS.map(({ key, label }) => {
                  const on = layers[key as LayerKey]
                  return (
                    <button key={key} onClick={() => toggleLayer(key as LayerKey)}
                      style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px 3px 7px', border: '1px solid', borderRadius: 20, fontSize: 9, fontWeight: 600, cursor: 'pointer', outline: 'none', transition: 'all 0.12s', background: on ? '#EAF3FF' : C.subtle, borderColor: on ? '#91C0F8' : C.line, color: on ? '#1258B8' : C.muted }}>
                      {/* pill toggle */}
                      <span style={{ width: 22, height: 12, borderRadius: 6, background: on ? '#2589F5' : '#C5CDD8', position: 'relative', display: 'inline-block', flexShrink: 0, transition: 'background 0.12s' }}>
                        <span style={{ position: 'absolute', top: 2, left: on ? 12 : 2, width: 8, height: 8, borderRadius: '50%', background: '#fff', transition: 'left 0.12s', boxShadow: '0 1px 2px rgba(0,0,0,0.18)' }} />
                      </span>
                      {label}
                    </button>
                  )
                })}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <button style={{ padding: '3px 10px', background: '#2589F5', border: 'none', borderRadius: 5, cursor: 'pointer', fontSize: 9.5, fontWeight: 800, color: '#fff', outline: 'none', letterSpacing: '0.06em' }}>2D</button>
                {isAdmin && (
                  <button
                    title="3차 개발 범위의 기능을 관리자 전용으로 미리 제공합니다 (미저장)"
                    onClick={() => setIsMapEdit(p => !p)}
                    style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 9px', background: isMapEdit ? '#F0EBF8' : '#F6F4FA', border: `1px solid ${isMapEdit ? '#9B72CF' : '#C5BADC'}`, borderRadius: 5, cursor: 'pointer', fontSize: 9.5, fontWeight: 700, color: isMapEdit ? '#5B2D99' : '#7A6BA0', outline: 'none' }}>
                    🛠 맵 편집
                    <span style={{ fontSize: 8, fontWeight: 700, background: isMapEdit ? '#DDD5F0' : '#EAE5F5', color: isMapEdit ? '#5B2D99' : '#8070AA', border: `1px solid ${isMapEdit ? '#B8A6E0' : '#C8BFE0'}`, borderRadius: 20, padding: '0px 5px', lineHeight: '14px', whiteSpace: 'nowrap' }}>3차 기능 · 조기 반영</span>
                  </button>
                )}
              </div>
            </div>

            {isMapEdit && <div style={{ padding: '7px 14px', background: '#F4F0FF', color: '#7255CB', fontSize: 10 }}>지도 편집 미리보기 · 이 데모에서는 구조물 및 경로 변경을 저장하지 않습니다.</div>}
            <WarehouseMap
              nodes={MAP_NODES}
              layers={layers}
              selectedRobot={selectedRobot}
              onSelect={handleSelect}
              picking={nodeMovePickerOpen}
              targetNode={nodeMoveTarget?.mapNodeId}
              onPick={id => setNodeMoveTarget({ id, label: id, mapNodeId: id as MapNodeId })}
            />
          </div>
          {/* ── DETAIL PANEL ── */}
          {selectedRobot && (
            <DetailPanel
              robotId={selectedRobot}
              updateTime={clock}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              onClose={handleClose}
              remoteExpanded={remoteExpanded}
              onToggleExpand={() => setRemoteEx(p => !p)}
              remoteOn={remoteOn}
              onToggleRemoteOn={() => { if (isAdmin && !simCommsLost) setRemoteOn(p => !p) }}
              keysActive={keysActive}
              isAdmin={isAdmin}
              remoteConn={remoteConn}
              cmdState={cmdState}
              pendingCmd={pendingCmd}
              confirmDlg={confirmDlg}
              onCmd={handleCmd}
              onConfirm={executeCmd}
              onCancelDlg={() => setConfirmDlg(null)}
              onDismissResult={resetCmdState}
              simCommsLost={simCommsLost}
              onSimCommsLost={() => setSimLost(p => !p)}
              nodeMoveTarget={nodeMoveTarget}
              nodeMovePickerOpen={nodeMovePickerOpen}
              onNodeMoveTargetChange={setNodeMoveTarget}
              onNodeMovePickerOpenChange={setNodeMovePickerOpen}
            />
          )}
          </>)}
        </div>

        {/* ── BOTTOM ── */}
        {isSmall && activeNav !== 'robots' && activeNav !== 'orders' && activeNav !== 'alarms' && activeNav !== 'analytics' && activeNav !== 'logs' && (
          <div className="fms-bottom-toggle" style={{ height: 32, background: C.surface, borderTop: `1px solid ${C.line}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, cursor: 'pointer' }} onClick={() => setBottomVis(p => !p)}>
            <span style={{ fontSize: 9.5, fontWeight: 700, color: C.muted }}>{bottomVisible ? '▼ 작업·알람 숨기기' : '▲ 진행 중인 작업·알람 보기'}</span>
          </div>
        )}
        {activeNav !== 'robots' && activeNav !== 'orders' && activeNav !== 'alarms' && activeNav !== 'analytics' && activeNav !== 'logs' && (!isSmall || bottomVisible) && (<div style={{ height: bottomH, background: C.surface, borderTop: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', flexShrink: 0, boxShadow: '0 -1px 0 rgba(0,0,0,0.03)' }}>
          {/* drag handle */}
          <div
            onMouseDown={(e) => {
              e.preventDefault()
              const startY = e.clientY
              const startH = bottomH
              const onMove = (ev: MouseEvent) => {
                const delta = startY - ev.clientY
                setBottomH(Math.min(Math.round(window.innerHeight * 0.45), Math.max(40, startH + delta)))
              }
              const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
              window.addEventListener('mousemove', onMove)
              window.addEventListener('mouseup', onUp)
            }}
            style={{ height: 10, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'row-resize', background: C.subtle, borderBottom: `1px solid ${C.line}`, userSelect: 'none' }}>
            <span style={{ width: 28, height: 2, borderRadius: 2, background: '#C5CDD8', display: 'block' }} />
          </div>
          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <div style={{ flex: 1, padding: '8px 16px', borderRight: `1px solid ${C.line}`, overflow: 'hidden' }}>
            <div style={{ fontWeight: 800, fontSize: 11, marginBottom: 6, color: C.text }}>진행 중인 작업</div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>{['작업 ID', '로봇', '상태', '현재 단계', '현재 예상 완료'].map(h => <th key={h} style={{ textAlign: 'left', padding: '0 10px 4px 0', fontSize: 9, color: '#697687', fontWeight: 700 }}>{h}</th>)}</tr></thead>
              <tbody>
                <tr style={{ borderTop: '1px solid #F0F3F7' }}>
                  <td style={{ padding: '4px 10px 4px 0', fontFamily: MONO, fontSize: 9 }}>TK-260913-001</td>
                  <td style={{ padding: '4px 10px 4px 0', fontSize: 10, fontWeight: 700 }}>R-01</td>
                  <td style={{ padding: '4px 10px 4px 0' }}><span style={{ padding: '2px 6px', background: '#E9F8F3', color: '#27966e', borderRadius: 4, fontWeight: 800, fontSize: 9 }}>진행 중</span></td>
                  <td style={{ padding: '4px 10px 4px 0', fontSize: 9, color: C.muted }}>팔레트 1 → 패킹 ST-1</td>
                  <td style={{ padding: '4px 0', fontFamily: MONO, fontSize: 9 }}>09:47:30</td>
                </tr>
                <tr style={{ borderTop: '1px solid #F0F3F7' }}>
                  <td style={{ padding: '4px 10px 4px 0', fontFamily: MONO, fontSize: 9 }}>TK-260913-002</td>
                  <td style={{ padding: '4px 10px 4px 0', fontSize: 10, fontWeight: 700 }}>R-02</td>
                  <td style={{ padding: '4px 10px 4px 0' }}><span style={{ padding: '2px 6px', background: '#FFF5DF', color: '#c98720', borderRadius: 4, fontWeight: 800, fontSize: 9 }}>배차 대기</span></td>
                  <td style={{ padding: '4px 10px 4px 0', fontSize: 9, color: '#C0C8D0' }}>—</td>
                  <td style={{ padding: '4px 0', fontFamily: MONO, fontSize: 9, color: '#C0C8D0' }}>—</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div style={{ width: 290, padding: '8px 14px', flexShrink: 0 }}>
            <div style={{ fontWeight: 800, fontSize: 11, marginBottom: 6 }}>최신 알람</div>
            <AlarmRow dot={C.danger} label="R-03 배터리 저하 경고" time="09:31:14" target="R-03" state="미확인" />
            <AlarmRow dot="#B0B8C4" label="TK-260913-001 작업 시작" time="09:28:02" target="R-01" state="확인됨" muted />
          </div>
          </div>
        </div>)}

        {/* ── MOBILE BOTTOM TAB BAR (<480px) ── */}
        {isMobile && (
          <nav className="fms-bottom-tabbar" style={{ height: 56, background: C.nav, borderTop: '1px solid rgba(255,255,255,0.08)', flexShrink: 0, display: 'flex', alignItems: 'stretch' }}>
            {NAV_ITEMS.map(item => {
              const a = activeNav === item.id
              return (
                <button key={item.id} onClick={() => setActiveNav(item.id)}
                  style={{ flex: 1, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2, color: a ? '#6DB8FF' : '#5A6677', outline: 'none', borderTop: `2px solid ${a ? '#3FA3F5' : 'transparent'}`, padding: '4px 0 2px' }}>
                  <span style={{ fontSize: 18, lineHeight: 1 }}>{item.icon}</span>
                  <span style={{ fontSize: 8, fontWeight: a ? 700 : 500, letterSpacing: '0.02em', lineHeight: 1 }}>{item.label.split('·')[0].trim()}</span>
                </button>
              )
            })}
          </nav>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// DetailPanel
// ══════════════════════════════════════
interface DPProps {
  robotId: RobotId; updateTime: string
  activeTab: TabId; onTabChange: (t: TabId) => void; onClose: () => void
  remoteExpanded: boolean; onToggleExpand: () => void
  remoteOn: boolean; onToggleRemoteOn: () => void
  keysActive: boolean; isAdmin: boolean; remoteConn: RemoteConn
  cmdState: CmdState; pendingCmd: string | null
  confirmDlg: string | null
  onCmd: (id: string, confirm: boolean) => void
  onConfirm: (id: string) => void
  onCancelDlg: () => void
  onDismissResult: () => void
  simCommsLost: boolean; onSimCommsLost: () => void
  nodeMoveTarget: NodePickerItem | null
  nodeMovePickerOpen: boolean
  onNodeMoveTargetChange: (item: NodePickerItem | null) => void
  onNodeMovePickerOpenChange: (open: boolean) => void
}

function DetailPanel(p: DPProps) {
  const r = ROBOT_DATA[p.robotId]
  const commsOk = !p.simCommsLost
  const switchOn = p.remoteOn && p.isAdmin && commsOk

  // Remote area title label
  const remoteLabel = !p.isAdmin
    ? '관리자 ON 후 사용'
    : !commsOk
      ? '통신 끊김 — 사용 불가'
      : p.remoteConn === 'connecting'
        ? '연결 요청 중…'
        : p.remoteConn === 'ready'
          ? 'ON'
          : '원격제어 OFF'
  const remoteLabelColor = !p.isAdmin
    ? '#97A0AB'
    : !commsOk
      ? C.danger
      : p.remoteConn === 'connecting'
        ? C.warning
        : p.remoteConn === 'ready'
          ? C.success
          : C.muted

  return (
    <div style={{ width: 360, background: C.surface, borderLeft: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden', position: 'relative', boxShadow: '-2px 0 8px rgba(0,0,0,0.05)', animation: 'slide-in-right 0.18s ease-out' }}>

      {/* Confirmation dialog overlay — scoped to panel only */}
      {p.confirmDlg && (
        <ConfirmDialog
          cmdId={p.confirmDlg}
          robotId={p.robotId}
          onConfirm={() => p.onConfirm(p.confirmDlg!)}
          onCancel={p.onCancelDlg}
        />
      )}

      {/* ── Panel header ── */}
      <div style={{ padding: '10px 14px 0', flexShrink: 0, borderBottom: `1px solid ${C.line}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 9 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <div style={{ width: 34, height: 34, borderRadius: 9, background: '#EDF6FF', border: `2px solid ${C.primary}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 13, color: '#167BEA', flexShrink: 0 }}>
              {p.robotId.replace('R-', '')}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                <span style={{ fontWeight: 800, fontSize: 15, letterSpacing: '-0.02em' }}>{p.robotId}</span>
                {p.simCommsLost
                  ? <span style={{ padding: '2px 6px', background: '#FFF0F2', color: C.danger, borderRadius: 4, fontSize: 9, fontWeight: 800 }}>통신 끊김</span>
                  : <span style={{ padding: '2px 6px', background: r.statusBg, color: r.statusColor, borderRadius: 4, fontSize: 9, fontWeight: 800 }}>{r.status}</span>
                }
              </div>
              <div style={{ fontSize: 9, color: '#97A0AB', marginTop: 2, fontFamily: MONO }}>갱신: {p.updateTime}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            {/* Comms lost simulation toggle */}
            <button onClick={p.onSimCommsLost} title="통신 끊김 시뮬레이션 (데모)"
              style={{ padding: '3px 7px', borderRadius: 5, border: `1px solid ${p.simCommsLost ? '#F1C8CD' : C.line}`, background: p.simCommsLost ? '#FFF0F2' : '#F7F9FB', fontSize: 8, fontWeight: 700, color: p.simCommsLost ? C.danger : '#B0B8C4', cursor: 'pointer', outline: 'none' }}>
              {p.simCommsLost ? '↺ 재연결' : '통신 끊김 ▸'}
            </button>
            <button onClick={p.onClose} style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: `1px solid ${C.line}`, borderRadius: 6, cursor: 'pointer', color: C.muted, fontSize: 12, outline: 'none' }}>✕</button>
          </div>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', borderTop: `1px solid ${C.line}` }}>
          {TABS.map(({ id, label }) => (
            <button key={id} onClick={() => p.onTabChange(id)}
              style={{ flex: 1, padding: '7px 0', fontSize: 11, fontWeight: p.activeTab === id ? 700 : 500, color: p.activeTab === id ? C.primary : C.muted, background: p.activeTab === id ? '#F4F8FF' : 'transparent', border: 'none', borderBottom: `2px solid ${p.activeTab === id ? C.primary : 'transparent'}`, cursor: 'pointer', outline: 'none', transition: 'all 0.12s', letterSpacing: p.activeTab === id ? '-0.01em' : 'normal' }}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab content — scrollable ── */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {p.activeTab === 'status'  && <StatusTab  robot={r} commsLost={p.simCommsLost} />}
        {p.activeTab === 'task'    && <TaskTab    robot={r} />}
        {p.activeTab === 'control' && (
          <ControlTab
            isAdmin={p.isAdmin}
            commsOk={commsOk}
            cmdState={p.cmdState}
            pendingCmd={p.pendingCmd}
            onCmd={p.onCmd}
            onDismiss={p.onDismissResult}
            nodeMoveTarget={p.nodeMoveTarget}
            nodeMovePickerOpen={p.nodeMovePickerOpen}
            onNodeMoveTargetChange={p.onNodeMoveTargetChange}
            onNodeMovePickerOpenChange={p.onNodeMovePickerOpenChange}
          />
        )}
      </div>

      {/* ── Remote control — always-visible fixed bottom ── */}
      <div style={{ flexShrink: 0, borderTop: `1px solid ${C.line}`, background: p.remoteConn === 'ready' ? '#F3FBF7' : C.subtle, transition: 'background 0.3s' }}>
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 12px', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0, overflow: 'hidden' }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: C.text, whiteSpace: 'nowrap' }}>키보드 원격제어</span>
            <span style={{ color: '#D0D5DC', fontSize: 10 }}>·</span>
            <span style={{ fontSize: 10, fontWeight: 700, color: C.primary, whiteSpace: 'nowrap' }}>{p.robotId}</span>
            <span style={{ color: '#D0D5DC', fontSize: 10 }}>·</span>
            <span style={{ fontSize: 9, fontWeight: 700, color: remoteLabelColor, whiteSpace: 'nowrap' }}>
              {p.remoteConn === 'connecting' && <span style={{ display: 'inline-block', marginRight: 3 }}>⟳</span>}
              {remoteLabel}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            {/* Toggle — always visible; only active when admin + comms ok */}
            {(() => {
              const canToggle = p.isAdmin && commsOk
              const tip = !p.isAdmin
                ? '관리자 모드가 필요합니다'
                : !commsOk
                  ? '통신이 끊겨 원격 제어를 사용할 수 없습니다'
                  : undefined
              return (
                <div onClick={canToggle ? p.onToggleRemoteOn : undefined}
                  title={tip}
                  style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: canToggle ? 'pointer' : 'not-allowed', opacity: canToggle ? 1 : 0.4, transition: 'opacity 0.15s' }}>
                  <span style={{ fontSize: 9, fontWeight: 700, color: switchOn ? C.success : C.muted }}>
                    {switchOn ? 'ON' : 'OFF'}
                  </span>
                  <div style={{ position: 'relative', width: 30, height: 15, borderRadius: 8, background: switchOn ? C.success : '#CBD2DA', transition: 'background 0.15s' }}>
                    <div style={{ position: 'absolute', top: 2, left: switchOn ? 15 : 2, width: 11, height: 11, background: '#fff', borderRadius: '50%', boxShadow: '0 1px 3px rgba(0,0,0,0.2)', transition: 'left 0.15s' }} />
                  </div>
                </div>
              )
            })()}
            <button onClick={p.onToggleExpand}
              style={{ padding: '3px 7px', background: '#fff', border: `1px solid ${C.line}`, borderRadius: 5, fontSize: 9, fontWeight: 600, color: C.muted, cursor: 'pointer', outline: 'none' }}>
              {p.remoteExpanded ? '접기' : '펼치기'}
            </button>
          </div>
        </div>

        {/* Key grid */}
        {p.remoteExpanded && (
          <div style={{ padding: '0 12px 10px' }}>
            {/* Connecting / comms lost notice */}
            {(p.remoteConn === 'connecting') && (
              <div style={{ marginBottom: 8, padding: '5px 10px', background: '#FFF9EE', border: '1px solid #ECD5AA', borderRadius: 6, fontSize: 9, color: '#9A6A10', fontWeight: 600 }}>
                백엔드 연결 확인 중 — 완료 전 키 입력은 전달되지 않습니다
              </div>
            )}
            {p.simCommsLost && (
              <div style={{ marginBottom: 8, padding: '5px 10px', background: '#FFF0F2', border: '1px solid #F1C8CD', borderRadius: 6, fontSize: 9, color: C.danger, fontWeight: 600 }}>
                R-02 통신 끊김 — 원격제어 사용 불가
              </div>
            )}
            {(!p.isAdmin && !p.simCommsLost) && (
              <div style={{ marginBottom: 8, padding: '5px 10px', background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 9, color: '#B0B8C4', fontWeight: 600 }}>
                관리자 모드 + 원격제어 ON이 모두 활성화되어야 사용 가능합니다
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 5, marginBottom: 5 }}>
              {KEY_ROWS.map((row, ri) =>
                row.map(({ k, l }) => (
                  <KeyCap key={`${ri}${k}`} keyLabel={k} actionLabel={l} active={p.keysActive} />
                ))
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 34, background: p.keysActive ? '#fff' : '#F3F6FA', border: `1px solid ${p.keysActive ? '#CDD5DE' : '#E4E8ED'}`, borderBottom: `${p.keysActive ? 3 : 2}px solid ${p.keysActive ? '#B5C0CE' : '#DFE4EB'}`, borderRadius: 7, opacity: p.keysActive ? 1 : 0.5, cursor: p.keysActive ? 'pointer' : 'default', userSelect: 'none', transition: 'all 0.15s' }}>
              <span style={{ fontSize: 10, fontWeight: 800, color: p.keysActive ? C.text : '#8A95A0' }}>SPACE · 주행 명령 정지</span>
            </div>
            {p.keysActive && (
              <div style={{ marginTop: 5, fontSize: 8, color: '#B0B8C4', textAlign: 'center', lineHeight: 1.4 }}>
                키 배치는 화면 시안입니다 — 실제 주행 명령 매핑은 로봇 제어 인터페이스 확인 후 확정
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// Confirm Dialog (panel-scoped overlay)
// ══════════════════════════════════════
function ConfirmDialog({ cmdId, robotId, onConfirm, onCancel }: { cmdId: string; robotId: RobotId; onConfirm: () => void; onCancel: () => void }) {
  const cmd = CTRL_CMDS.find(c => c.id === cmdId)
  const isDanger = cmd?.variant === 'danger'
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(32,36,43,0.52)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 300, background: C.surface, borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.18)', overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
            <span style={{ fontSize: 16 }}>{isDanger ? '⚠' : 'ⓘ'}</span>
            <span style={{ fontWeight: 800, fontSize: 13 }}>명령 확인</span>
          </div>
          <p style={{ fontSize: 11, color: C.muted, margin: '0 0 4px', lineHeight: 1.6 }}>
            <strong style={{ color: C.text }}>{robotId}</strong>에 <strong style={{ color: isDanger ? C.danger : C.text }}>{cmd?.label}</strong> 명령을 요청합니다.
          </p>
          <p style={{ fontSize: 10, color: '#B0B8C4', margin: '0 0 14px', lineHeight: 1.5 }}>
            실행 승인은 백엔드의 상태 검증 후 결정됩니다.
          </p>
        </div>
        <div style={{ display: 'flex', borderTop: `1px solid ${C.line}` }}>
          <button onClick={onCancel} style={{ flex: 1, padding: '10px 0', background: '#F7F9FB', border: 'none', borderRight: `1px solid ${C.line}`, fontSize: 11, fontWeight: 700, color: C.muted, cursor: 'pointer', outline: 'none' }}>취소</button>
          <button onClick={onConfirm}
            style={{ flex: 1, padding: '10px 0', background: isDanger ? '#FFF5F6' : '#EDF6FF', border: 'none', fontSize: 11, fontWeight: 800, color: isDanger ? C.danger : C.primary, cursor: 'pointer', outline: 'none' }}>
            요청 전송
          </button>
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// Tab content components
// ══════════════════════════════════════
type RData = typeof ROBOT_DATA[RobotId]

function InfoRow({ label, value, mono = false, vs }: { label: string; value: string; mono?: boolean; vs?: React.CSSProperties }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: `1px solid ${C.line}` }}>
      <span style={{ fontSize: 10, color: C.muted, fontWeight: 500 }}>{label}</span>
      <span style={{ fontSize: 10, fontWeight: 600, fontFamily: mono ? MONO : undefined, color: C.text, ...vs }}>{value}</span>
    </div>
  )
}
function SHead({ label }: { label: string }) {
  return <div style={{ fontSize: 8.5, fontWeight: 700, color: '#98A3B0', letterSpacing: '0.09em', marginTop: 14, marginBottom: 5, textTransform: 'uppercase' as const }}>{label}</div>
}
function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={{ width: 64, height: 4, background: '#DDE3EC', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2, transition: 'width 0.3s' }} />
    </div>
  )
}

function StatusTab({ robot, commsLost }: { robot: RData; commsLost: boolean }) {
  const bc = robot.battery < 30 ? C.danger : robot.battery < 50 ? C.warning : C.success
  return (
    <div style={{ padding: '10px 14px' }}>
      <SHead label="위치" />
      <InfoRow label="현재 위치" value={robot.position} />
      <InfoRow label="다음 노드" value={robot.nextNode} />
      <SHead label="시스템" />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #F0F3F7' }}>
        <span style={{ fontSize: 10, color: C.muted }}>배터리</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Bar pct={robot.battery} color={bc} />
          <span style={{ fontSize: 10, fontWeight: 700, color: bc, fontFamily: MONO, minWidth: 30, textAlign: 'right' }}>{robot.battery}%</span>
        </div>
      </div>
      <InfoRow label="통신 상태" value={commsLost ? '통신 끊김' : robot.comms} vs={{ color: commsLost ? C.danger : C.success }} />
      <InfoRow label="제어 모드" value={robot.mode} />
      <InfoRow label="적재 상태" value={robot.load} />
      <SHead label="식별" />
      <InfoRow label="시리얼 번호" value={robot.serial} mono />
      <InfoRow label="모델" value="TurtleBot 3 Burger" />
    </div>
  )
}

function TaskTab({ robot }: { robot: RData }) {
  return (
    <div style={{ padding: '10px 14px' }}>
      <SHead label="현재 작업" />
      <InfoRow label="작업 ID" value={robot.taskId} mono />
      <InfoRow label="현재 단계" value={robot.taskStep} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #F0F3F7' }}>
        <span style={{ fontSize: 10, color: C.muted }}>진행률</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Bar pct={robot.progress} color={robot.progress > 0 ? C.primary : '#DFE4EB'} />
          <span style={{ fontSize: 10, fontWeight: 700, color: C.muted, fontFamily: MONO, minWidth: 30, textAlign: 'right' }}>{robot.progress}%</span>
        </div>
      </div>
      <InfoRow label="방문 팔레트" value={robot.palettes} />
      <InfoRow label="계획 경로" value={robot.taskId === '—' ? '—' : '데이터 연결 예정'} />
      <SHead label="시간" />
      <InfoRow label="작업 시작" value={robot.startTime} mono />
      <InfoRow label="최초 예상 완료" value={robot.estOrig} mono />
      <InfoRow label="현재 예상 완료" value={robot.estCurr} mono />
      <InfoRow label="예상 지연" value={robot.delay} vs={{ color: robot.delay !== '—' && robot.delay !== '없음' ? C.warning : C.muted }} />
    </div>
  )
}

// Command state display
const CMD_RESULT_CFG: Record<NonNullable<CmdState>, { bg: string; border: string; color: string; icon: string; text: string }> = {
  requesting: { bg: '#EAF2FF', border: '#9DC4F0', color: '#1155A8', icon: '⟳', text: '요청 중 — 백엔드 검증 중' },
  approved:   { bg: '#E4F6EF', border: '#8DCFB2', color: '#147A4E', icon: '✓', text: '승인됨 — 로봇 상태를 확인하세요' },
  rejected:   { bg: '#FEF0F3', border: '#EDAAB6', color: '#B02038', icon: '✕', text: '거절됨 — 실행 조건 미충족 또는 통신 끊김' },
  confirmed:  { bg: '#E4F6EF', border: '#8DCFB2', color: '#0C5E3A', icon: '●', text: '실행 확인 — 로봇이 명령을 수신했습니다' },
}

function ControlTab({ isAdmin, commsOk, cmdState, pendingCmd, onCmd, onDismiss,
  nodeMoveTarget, nodeMovePickerOpen, onNodeMoveTargetChange, onNodeMovePickerOpenChange }: {
  isAdmin: boolean; commsOk: boolean
  cmdState: CmdState; pendingCmd: string | null
  onCmd: (id: string, confirm: boolean) => void
  onDismiss: () => void
  nodeMoveTarget: NodePickerItem | null
  nodeMovePickerOpen: boolean
  onNodeMoveTargetChange: (item: NodePickerItem | null) => void
  onNodeMovePickerOpenChange: (open: boolean) => void
}) {
  const canAct = isAdmin && commsOk
  const [pickerQuery, setPickerQuery] = useState('')

  // Close picker once a command starts executing
  useEffect(() => {
    if (cmdState) { onNodeMovePickerOpenChange(false); setPickerQuery('') }
  }, [cmdState])

  const getBtnStyle = (v: string, ready: boolean) => {
    if (!canAct || !ready) return { bg: C.subtle, bd: C.line, color: '#B8C2CC' }
    if (v === 'primary') return { bg: '#E8F1FF', bd: '#9DC4F0', color: '#1155A8' }
    if (v === 'warning') return { bg: '#FEF4E1', bd: '#E4C070', color: '#8C5A0A' }
    if (v === 'danger')  return { bg: '#FEF1F3', bd: '#EDAAB6', color: '#B02038' }
    return { bg: C.surface, bd: C.line, color: C.text }
  }

  const handlePickerCancel = () => {
    onNodeMovePickerOpenChange(false)
    onNodeMoveTargetChange(null)
    setPickerQuery('')
  }

  const handleExecuteMove = () => {
    if (!nodeMoveTarget) return
    onCmd('nodeMove', false)
    setPickerQuery('')
  }

  const filteredGroups = NODE_PICKER_GROUPS.map(g => ({
    ...g,
    items: g.items.filter(item =>
      pickerQuery === '' ||
      item.label.toLowerCase().includes(pickerQuery.toLowerCase()) ||
      item.id.toLowerCase().includes(pickerQuery.toLowerCase()) ||
      item.mapNodeId.toLowerCase().includes(pickerQuery.toLowerCase())
    ),
  })).filter(g => g.items.length > 0)

  return (
    <div style={{ padding: '10px 14px' }}>
      {/* Context notice */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7, padding: '7px 10px', background: !canAct ? '#F8FAFC' : '#F0FDF6', border: `1px solid ${!canAct ? C.line : '#A8DECE'}`, borderRadius: 7, marginBottom: 12 }}>
        <span style={{ fontSize: 13, marginTop: 1 }}>{!canAct ? (isAdmin && !commsOk ? '🔴' : 'ⓘ') : '✓'}</span>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: !canAct ? C.muted : '#1a6e4f' }}>
            {!isAdmin ? '관리자 모드 전환 후 사용 가능' : !commsOk ? '통신 끊김 — 명령 전송 불가' : '관리자 모드 활성 — 명령 사용 가능'}
          </div>
          <div style={{ fontSize: 9, color: '#B0B8C4', marginTop: 2 }}>
            {!isAdmin ? '헤더 모드 버튼 클릭 시 전환 (프로토타입 데모)' : !commsOk ? 'R-02 통신 연결 복구 후 사용 가능합니다' : '실행 승인은 백엔드 상태 검증 후 결정됩니다 (1차 단일 사용자)'}
          </div>
        </div>
      </div>

      <SHead label="로봇 제어" />

      {/* 2-col grid for ready commands */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 6 }}>
        {CTRL_CMDS.filter(c => c.ready).map(({ id, label, variant, confirm }) => {
          const s = getBtnStyle(variant, true)
          const isCurrent = pendingCmd === id
          const isNodeMove = id === 'nodeMove'
          const nmActive = isNodeMove && nodeMovePickerOpen
          return (
            <button key={id}
              disabled={!canAct}
              onClick={() => {
                if (!canAct) return
                if (isNodeMove) { onNodeMovePickerOpenChange(!nodeMovePickerOpen) }
                else { onCmd(id, confirm) }
              }}
              style={{
                padding: '8px 6px', borderRadius: 7, fontSize: 10, fontWeight: 700,
                background: nmActive ? '#EAF1FB' : s.bg,
                border: `1px solid ${nmActive ? C.primary : s.bd}`,
                color: nmActive ? C.primary : isCurrent && cmdState ? '#97A0AB' : s.color,
                cursor: canAct ? 'pointer' : 'default', outline: 'none',
                transition: 'all 0.12s', position: 'relative' as const,
              }}>
              {label}
              {nmActive && (
                <span style={{
                  position: 'absolute', top: -4, right: -4,
                  width: 8, height: 8, borderRadius: '50%', background: C.primary,
                  boxShadow: '0 0 0 2px #fff',
                }}/>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Node picker panel ── */}
      {nodeMovePickerOpen && (
        <div style={{ marginBottom: 10, border: `1px solid ${C.primary}33`, borderRadius: 8, overflow: 'hidden', boxShadow: E2 }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 10px', background: '#EAF1FB', borderBottom: `1px solid ${C.primary}22` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
                <circle cx="5.5" cy="5.5" r="4.5" stroke={C.primary} strokeWidth="1"/>
                <circle cx="5.5" cy="5.5" r="1.8" fill={C.primary}/>
              </svg>
              <span style={{ fontSize: 10, fontWeight: 700, color: C.primary }}>목표 노드 선택</span>
            </div>
            <button onClick={handlePickerCancel}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.muted, fontSize: 13, lineHeight: 1, padding: 0, outline: 'none', opacity: 0.7 }}>✕</button>
          </div>

          {/* Selected target chip */}
          {nodeMoveTarget ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', background: '#F2F7FF', borderBottom: `1px solid ${C.primary}22` }}>
              <span style={{ fontSize: 8.5, color: C.muted, fontWeight: 700, flexShrink: 0 }}>목표</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '2px 8px 2px 6px', background: '#fff', border: `1px solid ${C.primary}`, borderRadius: 20, minWidth: 0 }}>
                <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                  <circle cx="4" cy="4" r="3.2" fill={C.primary}/>
                  <circle cx="4" cy="4" r="1.3" fill="#fff"/>
                </svg>
                <span style={{ fontSize: 9.5, fontWeight: 800, color: C.primary, fontFamily: MONO }}>{nodeMoveTarget.mapNodeId}</span>
                {nodeMoveTarget.mapNodeId !== nodeMoveTarget.label && (
                  <span style={{ fontSize: 9, color: '#5A6472', fontFamily: FONT }}> · {nodeMoveTarget.label}</span>
                )}
                <button onClick={() => onNodeMoveTargetChange(null)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.muted, fontSize: 12, lineHeight: 1, padding: 0, marginLeft: 1, outline: 'none' }}>✕</button>
              </div>
            </div>
          ) : (
            <div style={{ padding: '5px 10px', background: '#F8FAFC', borderBottom: `1px solid ${C.line}` }}>
              <span style={{ fontSize: 8.5, color: '#B0B8C4', fontStyle: 'italic' }}>목표 노드를 선택하거나 지도에서 클릭하세요</span>
            </div>
          )}

          {/* Search */}
          <div style={{ padding: '6px 10px', borderBottom: `1px solid ${C.line}` }}>
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
              <svg style={{ position: 'absolute', left: 7 }} width="10" height="10" viewBox="0 0 10 10" fill="none">
                <circle cx="4.3" cy="4.3" r="3.2" stroke="#9AA4B0" strokeWidth="1.1"/>
                <line x1="6.7" y1="6.7" x2="9" y2="9" stroke="#9AA4B0" strokeWidth="1.1" strokeLinecap="round"/>
              </svg>
              <input
                value={pickerQuery}
                onChange={e => setPickerQuery(e.currentTarget.value)}
                placeholder="노드 ID 또는 설비명 검색"
                style={{
                  width: '100%', paddingLeft: 22, paddingRight: 8, paddingTop: 4, paddingBottom: 4,
                  background: C.subtle, border: `1px solid ${C.line}`, borderRadius: 5,
                  fontSize: 9.5, color: C.text, outline: 'none', fontFamily: FONT,
                  boxSizing: 'border-box' as const,
                }}
              />
            </div>
          </div>

          {/* Grouped node list */}
          <div style={{ maxHeight: 178, overflowY: 'auto' }}>
            {filteredGroups.length === 0 ? (
              <div style={{ padding: '10px', textAlign: 'center', fontSize: 9.5, color: C.muted }}>검색 결과 없음</div>
            ) : filteredGroups.map(group => (
              <div key={group.title}>
                <div style={{ padding: '5px 10px 3px', fontSize: 7.5, fontWeight: 800, color: '#9AA4B0', letterSpacing: '0.08em', textTransform: 'uppercase', background: C.subtle, position: 'sticky', top: 0 }}>
                  {group.title}
                </div>
                {group.items.map(item => {
                  const isSel = nodeMoveTarget?.id === item.id
                  return (
                    <button key={item.id} onClick={() => onNodeMoveTargetChange(item)}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        width: '100%', padding: '5px 10px', background: isSel ? '#EAF1FB' : 'transparent',
                        border: 'none', borderBottom: `1px solid ${C.line}`,
                        cursor: 'pointer', textAlign: 'left', outline: 'none',
                        transition: 'background 0.08s',
                      }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                          <circle cx="4" cy="4" r="3.2" fill={isSel ? C.primary : '#fff'} stroke={isSel ? C.primary : '#8FA0B3'} strokeWidth="1"/>
                          <circle cx="4" cy="4" r="1.3" fill={isSel ? '#fff' : '#8FA0B3'}/>
                        </svg>
                        <span style={{ fontSize: 9.5, fontFamily: FONT, fontWeight: isSel ? 700 : 400, color: isSel ? C.primary : C.text }}>
                          {item.label}
                        </span>
                        {item.mapNodeId !== item.label && (
                          <span style={{ fontSize: 8.5, fontFamily: MONO, color: '#9AA4B0' }}>→ {item.mapNodeId}</span>
                        )}
                      </div>
                      {isSel && (
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                          <path d="M2 5L4 7.5 8.5 2.5" stroke={C.primary} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>

          {/* Execute footer */}
          <div style={{ padding: '8px 10px', background: C.subtle, borderTop: `1px solid ${C.line}` }}>
            <button onClick={handleExecuteMove} disabled={!nodeMoveTarget}
              style={{
                width: '100%', padding: '7px 0', borderRadius: 6, border: 'none',
                background: nodeMoveTarget ? C.primary : '#DDE3EC',
                fontSize: 10, fontWeight: 800,
                color: nodeMoveTarget ? '#fff' : '#B0B8C4',
                cursor: nodeMoveTarget ? 'pointer' : 'default', outline: 'none',
                transition: 'all 0.12s',
              }}>
              {nodeMoveTarget ? `이동 실행 → ${nodeMoveTarget.mapNodeId}` : '이동 실행'}
            </button>
          </div>
        </div>
      )}

      {/* 준비 중 commands — full width, clearly not-clickable */}
      {CTRL_CMDS.filter(c => !c.ready).map(({ id, label, variant }) => {
        const s = getBtnStyle(variant, false)
        return (
          <div key={id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', background: s.bg, border: `1px solid ${s.bd}`, borderRadius: 7, marginBottom: 6, cursor: 'default' }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: s.color }}>{label}</span>
            <span style={{ padding: '2px 6px', background: '#F0F3F7', border: '1px solid #E4E8ED', borderRadius: 4, fontSize: 8, fontWeight: 800, color: '#97A0AB' }}>준비 중</span>
          </div>
        )
      })}

      {/* Command result area */}
      {cmdState && pendingCmd && (() => {
        const cfg = CMD_RESULT_CFG[cmdState]
        const baseLabel = CTRL_CMDS.find(c => c.id === pendingCmd)?.label ?? pendingCmd
        const cmdLabel = pendingCmd === 'nodeMove' && nodeMoveTarget
          ? `${baseLabel} → ${nodeMoveTarget.mapNodeId}${nodeMoveTarget.mapNodeId !== nodeMoveTarget.label ? ` (${nodeMoveTarget.label})` : ''}`
          : baseLabel
        return (
          <div style={{ marginTop: 10, padding: '8px 10px', background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 3 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ fontSize: 12, color: cfg.color, fontWeight: 900, display: 'inline-block', animation: cmdState === 'requesting' ? 'spin 1s linear infinite' : 'none' }}>{cfg.icon}</span>
                <span style={{ fontSize: 10, fontWeight: 800, color: cfg.color }}>{cfg.text}</span>
              </div>
              {(cmdState === 'confirmed' || cmdState === 'rejected') && (
                <button onClick={onDismiss} style={{ background: 'transparent', border: 'none', fontSize: 11, color: cfg.color, cursor: 'pointer', padding: 0, outline: 'none', opacity: 0.7 }}>✕</button>
              )}
            </div>
            <div style={{ fontSize: 9, color: cfg.color, opacity: 0.75 }}>
              명령: {cmdLabel}
            </div>
          </div>
        )
      })()}
    </div>
  )
}

// ══════════════════════════════════════
// Key cap atom
// ══════════════════════════════════════
function KeyCap({ keyLabel, actionLabel, active }: { keyLabel: string; actionLabel: string; active: boolean }) {
  return (
    <div style={{ height: 44, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: active ? '#fff' : C.subtle, border: `1px solid ${active ? '#BEC8D6' : C.line}`, borderBottom: `${active ? 3 : 2}px solid ${active ? '#A4B0C0' : '#D4DAE5'}`, borderRadius: 7, opacity: active ? 1 : 0.45, cursor: active ? 'pointer' : 'default', userSelect: 'none' as const, transition: 'all 0.15s', boxShadow: active ? E1 : 'none' }}>
      <span style={{ fontSize: 14, fontWeight: 900, color: active ? C.text : '#9097A3', lineHeight: 1, letterSpacing: '-0.01em' }}>{keyLabel}</span>
      <span style={{ fontSize: 8, color: C.muted, marginTop: 2.5, fontWeight: 500 }}>{actionLabel}</span>
    </div>
  )
}

// ══════════════════════════════════════
// Shared atoms
// ══════════════════════════════════════
function Div() { return <div style={{ width: 1, height: 16, background: C.line, flexShrink: 0 }} /> }

function SChip({ label, value, dot, vc, bg = C.surface, bd = C.line }: { label: string; value: string; dot?: string; vc?: React.CSSProperties; bg?: string; bd?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 9px', background: bg, border: `1px solid ${bd}`, borderRadius: 6, boxShadow: E1 }}>
      {dot && <span style={{ width: 5.5, height: 5.5, borderRadius: '50%', background: dot, display: 'inline-block', flexShrink: 0 }} />}
      <span style={{ fontSize: 10, color: C.muted, fontWeight: 500 }}>{label}</span>
      <span style={{ fontWeight: 800, fontSize: 11.5, color: C.text, ...vc }}>{value}</span>
    </div>
  )
}
function ArmChip({ id, status, color }: { id: string; status: string; color: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', background: C.surface, border: `1px solid ${C.line}`, borderRadius: 6, boxShadow: E1 }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: C.text }}>{id}</span>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
      <span style={{ fontSize: 9, color: C.muted, fontWeight: 500 }}>{status}</span>
    </div>
  )
}
function SearchIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
      <circle cx="5" cy="5" r="3.5" stroke="#B0B8C4" strokeWidth="1.3" />
      <path d="M8 8l2 2" stroke="#B0B8C4" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}
function RobotCard({ id, serial, status, statusColor, statusBg, battery, task, selected, onClick }: {
  id: string; serial: string; status: string; statusColor: string; statusBg: string
  battery: number; task: string; selected: boolean; onClick: () => void
}) {
  const bc = battery < 30 ? C.danger : battery < 50 ? C.warning : C.success
  return (
    <div onClick={onClick} style={{ marginBottom: 6, padding: '10px 11px', background: selected ? '#EEF6FF' : C.surface, border: `1px solid ${selected ? '#A8CAEF' : C.line}`, borderLeft: `3px solid ${selected ? C.primary : 'transparent'}`, borderRadius: 9, cursor: 'pointer', transition: 'all 0.12s', boxShadow: selected ? `0 0 0 3px rgba(26,111,216,0.08), ${E1}` : E1 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 7 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: selected ? '#D8ECFF' : C.subtle, border: `1.5px solid ${selected ? '#A8CAEF' : C.line}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 12, color: selected ? C.primary : C.muted, flexShrink: 0 }}>
            {id.replace('R-', '')}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 12, lineHeight: 1.2, color: C.text }}>{id}</div>
            <div style={{ fontSize: 8.5, color: '#AAB4C0', fontFamily: MONO, marginTop: 1 }}>{serial}</div>
          </div>
        </div>
        <span style={{ padding: '2px 7px', background: statusBg, color: statusColor, borderRadius: 4, fontSize: 9, fontWeight: 700 }}>{status}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <div style={{ flex: 1, height: 4, background: '#E2E7EF', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${battery}%`, background: bc, borderRadius: 2, transition: 'width 0.3s' }} />
        </div>
        <span style={{ fontSize: 9, color: bc, fontWeight: 700, minWidth: 30, textAlign: 'right' as const, fontFamily: MONO }}>{battery}%</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.success, display: 'inline-block' }} />
          <span style={{ fontSize: 8.5, color: C.muted, fontWeight: 500 }}>연결</span>
        </div>
      </div>
      <div style={{ fontSize: 9, color: C.muted, borderTop: `1px solid ${C.line}`, paddingTop: 5 }}>
        작업: <span style={{ color: task === '—' ? '#BBC4CE' : C.text, fontWeight: task === '—' ? 400 : 600, fontSize: 9 }}>{task}</span>
      </div>
    </div>
  )
}
function SMark({ x, y, label, color, bg }: { x: string; y: string; label: string; color: string; bg: string }) {
  return (
    <div style={{ position: 'absolute', left: x, top: y, transform: 'translate(-50%,-50%)', zIndex: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 8px 3px 6px', background: bg, border: `1px solid ${color}`, borderRadius: 5, fontSize: 9, fontWeight: 700, color, whiteSpace: 'nowrap' as const, boxShadow: '0 2px 6px rgba(0,0,0,0.10)' }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
        {label}
      </div>
    </div>
  )
}
function RMark({ x, y, id, status, selected, onSelect }: { x: string; y: string; id: string; status: 'move' | 'wait' | 'charge'; selected: boolean; onSelect: () => void }) {
  const color = status === 'move' ? C.success : status === 'wait' ? C.warning : C.primary
  const sz = selected ? 40 : 34
  return (
    <div onClick={onSelect} style={{ position: 'absolute', left: x, top: y, transform: 'translate(-50%,-50%)', zIndex: 20, cursor: 'pointer' }}>
      <div style={{ width: sz, height: sz, borderRadius: '50%', background: selected ? '#E4F0FF' : '#fff', border: `${selected ? 2.5 : 2}px solid ${selected ? C.primary : color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: MONO, fontSize: selected ? 9.5 : 8.5, fontWeight: 700, color: selected ? C.primary : C.text, boxShadow: selected ? `0 0 0 5px rgba(26,111,216,0.18), ${E2}` : `0 0 0 3px ${color}28, 0 2px 8px rgba(0,0,0,0.12)`, transition: 'all 0.15s', letterSpacing: '-0.02em' }}>
        {id}
      </div>
    </div>
  )
}
// ══════════════════════════════════════
// RobotsArmsScreen (Stage 4)
// ══════════════════════════════════════
function RobotsArmsScreen({ onSelectRobot }: { onSelectRobot: (id: RobotId) => void }) {
  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

      {/* ── Main scrollable column ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 20px 20px', minWidth: 0 }}>

        {/* Summary bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, padding: '8px 12px', background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9 }}>
          <span style={{ fontSize: 11, fontWeight: 800 }}>설비 현황</span>
          <span style={{ color: '#D0D5DC', fontSize: 11 }}>·</span>
          <SumChip icon="🤖" label="TurtleBot" value="3 대" color={C.primary} />
          <SumChip icon="🦾" label="로봇팔" value="2 대" color={C.purple} />
          <SumChip icon="📦" label="패킹 스테이션" value="2 곳" color={C.warning} />
          <SumChip icon="🔋" label="충전 스테이션" value="3 곳" color={C.success} />
          <span style={{ marginLeft: 'auto', fontSize: 9, color: '#B0B8C4' }}>※ 시연값 — 실제 측정값 아님</span>
        </div>

        {/* ── TurtleBot 섹션 ── */}
        <RASectionHead label="TurtleBot" count={3} subtitle="이동 로봇 — 팔레트 운반 담당" />
        <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', marginBottom: 20 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#F8FAFC' }}>
                {['로봇', '운행 상태', '현재 위치/노드', '배터리', '통신', '현재 작업', '적재 상태', ''].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '7px 10px', fontSize: 9, color: '#697687', fontWeight: 700, borderBottom: `1px solid ${C.line}`, whiteSpace: 'nowrap' as const }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(['R-01', 'R-02', 'R-03'] as RobotId[]).map((id, i) => {
                const r = ROBOT_DATA[id]
                const bc = r.battery < 30 ? C.danger : r.battery < 50 ? C.warning : C.success
                return (
                  <tr key={id} style={{ borderTop: i > 0 ? `1px solid #F0F3F7` : undefined, cursor: 'pointer', transition: 'background 0.1s' }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#F8FBFF')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    onClick={() => onSelectRobot(id)}>
                    <td style={{ padding: '9px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <div style={{ width: 28, height: 28, borderRadius: 7, background: '#EDF6FF', border: `1.5px solid ${C.primary}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 11, color: '#167BEA', flexShrink: 0 }}>
                          {id.replace('R-', '')}
                        </div>
                        <div>
                          <div style={{ fontWeight: 800, fontSize: 11 }}>{id}</div>
                          <div style={{ fontSize: 9, color: '#B0B8C4', fontFamily: MONO }}>{r.serial}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: '9px 10px' }}>
                      <span style={{ padding: '2px 7px', background: r.statusBg, color: r.statusColor, borderRadius: 4, fontSize: 9, fontWeight: 800, whiteSpace: 'nowrap' as const }}>{r.status}</span>
                    </td>
                    <td style={{ padding: '9px 10px', fontSize: 10, color: r.position === '—' ? '#C0C8D0' : C.text }}>{r.position}</td>
                    <td style={{ padding: '9px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <div style={{ width: 44, height: 5, background: '#E7EBF0', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${r.battery}%`, background: bc, borderRadius: 3 }} />
                        </div>
                        <span style={{ fontSize: 9, fontWeight: 700, color: bc, fontFamily: MONO, minWidth: 26 }}>{r.battery}%</span>
                      </div>
                    </td>
                    <td style={{ padding: '9px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: r.comms === '연결됨' ? C.success : C.danger, display: 'inline-block' }} />
                        <span style={{ fontSize: 9, color: r.comms === '연결됨' ? C.success : C.danger, fontWeight: 600 }}>{r.comms}</span>
                      </div>
                    </td>
                    <td style={{ padding: '9px 10px', fontSize: 10, color: r.taskId === '—' ? '#C0C8D0' : C.text, maxWidth: 160 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{r.taskId === '—' ? '—' : r.taskId}</div>
                      {r.taskId !== '—' && <div style={{ fontSize: 9, color: C.muted, marginTop: 1 }}>{r.taskStep}</div>}
                    </td>
                    <td style={{ padding: '9px 10px', fontSize: 10, color: r.load === '미적재' ? '#C0C8D0' : C.text }}>{r.load}</td>
                    <td style={{ padding: '9px 10px' }}>
                      <button onClick={() => onSelectRobot(id)}
                        style={{ padding: '4px 9px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 5, fontSize: 9, fontWeight: 700, color: '#1675D4', cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
                        상세 →
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* ── 로봇팔 섹션 ── */}
        <RASectionHead label="로봇팔" count={2} subtitle="고정식 — 팔레트에서 물품을 집어 TurtleBot 바구니에 적재" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 8 }}>
          {(['ARM-1', 'ARM-2'] as ArmId[]).map(id => <ArmCard key={id} id={id} />)}
        </div>
      </div>

      {/* ── Right facilities panel ── */}
      <div style={{ width: 256, borderLeft: `1px solid ${C.line}`, background: C.surface, overflowY: 'auto', padding: '14px 14px 20px', flexShrink: 0 }}>

        {/* 패킹 스테이션 */}
        <RASectionHead label="패킹 스테이션" count={2} subtitle="적재 완료 처리 구역" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 18 }}>
          {PACKING_STATIONS.map(st => (
            <div key={st.id} style={{ padding: '10px 11px', background: '#FAFBFC', border: `1px solid ${C.line}`, borderLeft: `3px solid ${st.statusColor}`, borderRadius: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontWeight: 800, fontSize: 12 }}>{st.id}</span>
                <span style={{ padding: '2px 7px', background: st.statusBg, color: st.statusColor, border: `1px solid ${st.statusBd}`, borderRadius: 4, fontSize: 9, fontWeight: 800 }}>{st.status}</span>
              </div>
              {st.relatedRobot && (
                <div style={{ fontSize: 10, color: C.muted, marginBottom: 3 }}>
                  연관 로봇: <span style={{ fontWeight: 700, color: C.text }}>{st.relatedRobot}</span>
                  {st.taskRef && <span style={{ color: '#B0B8C4', marginLeft: 5, fontFamily: MONO, fontSize: 9 }}>{st.taskRef}</span>}
                </div>
              )}
              {st.routeCandidate && (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 5, padding: '4px 7px', background: '#F3F6FA', border: `1px dashed ${C.line}`, borderRadius: 5, marginTop: 4 }}>
                  <span style={{ fontSize: 9, color: '#97A0AB', lineHeight: 1.5, whiteSpace: 'nowrap' as const, paddingTop: 1 }}>경로 후보</span>
                  <span style={{ fontSize: 9, color: C.muted, lineHeight: 1.5 }}>{st.routeCandidate}</span>
                </div>
              )}
              {!st.relatedRobot && !st.routeCandidate && (
                <div style={{ fontSize: 10, color: '#C0C8D0' }}>관련 로봇 없음</div>
              )}
            </div>
          ))}
          <div style={{ padding: '6px 10px', background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 9, color: '#B0B8C4', lineHeight: 1.5 }}>
            경로 후보는 작업 계산 중인 잠정 도착지이며, 예약 상태와 다릅니다. 1차에서는 스테이션 장비 통신을 직접 수신하지 않습니다.
          </div>
        </div>

        {/* 충전 스테이션 */}
        <RASectionHead label="충전 스테이션" count={3} subtitle="배치 미확정 — 목록만 표시" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
          {CHARGING_STATIONS.map(ch => (
            <div key={ch.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 10px', background: '#FAFBFC', border: `1px solid ${C.line}`, borderRadius: 7 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#DFE4EB', display: 'inline-block' }} />
                <span style={{ fontWeight: 700, fontSize: 11 }}>{ch.id}</span>
              </div>
              <span style={{ padding: '2px 6px', background: '#F3F6FA', border: `1px dashed ${C.line}`, borderRadius: 4, fontSize: 8, fontWeight: 700, color: '#B0B8C4' }}>{ch.note}</span>
            </div>
          ))}
          <div style={{ padding: '6px 10px', background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 9, color: '#B0B8C4', lineHeight: 1.5 }}>
            충전 스테이션 위치는 시설 배치 확정 후 등록됩니다.
          </div>
        </div>

      </div>
    </div>
  )
}

// ── RobotsArmsScreen sub-components ──

function RASectionHead({ label, count, subtitle }: { label: string; count: number; subtitle?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 8 }}>
      <span style={{ fontWeight: 900, fontSize: 12 }}>{label}</span>
      <span style={{ background: '#EDF6FF', color: '#1675D4', borderRadius: 4, fontWeight: 800, fontSize: 9, padding: '1px 6px' }}>{count} 대</span>
      {subtitle && <span style={{ fontSize: 9, color: '#B0B8C4' }}>{subtitle}</span>}
    </div>
  )
}

function SumChip({ icon, label, value, color }: { icon: string; label: string; value: string; color: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 9px', background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 6 }}>
      <span style={{ fontSize: 11 }}>{icon}</span>
      <span style={{ fontSize: 9, color: C.muted }}>{label}</span>
      <span style={{ fontWeight: 800, fontSize: 11, color }}>{value}</span>
    </div>
  )
}

function ArmCard({ id }: { id: ArmId }) {
  const a = ARM_DATA[id]
  const stale = a.stale
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 10, overflow: 'hidden' }}>
      {/* Card header */}
      <div style={{ padding: '10px 12px 8px', borderBottom: `1px solid ${C.line}`, background: '#FAFBFC' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: '#F0ECFF', border: `2px solid ${C.purple}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, flexShrink: 0 }}>🦾</div>
            <div>
              <div style={{ fontWeight: 800, fontSize: 12 }}>{a.name} <span style={{ color: '#B0B8C4', fontWeight: 500 }}>({id})</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 2 }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: a.comms === '연결됨' ? C.success : C.danger, display: 'inline-block' }} />
                <span style={{ fontSize: 9, color: a.comms === '연결됨' ? C.success : C.danger, fontWeight: 600 }}>{a.comms}</span>
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
            <span style={{ padding: '2px 7px', background: a.statusBg, color: a.statusColor, borderRadius: 4, fontSize: 9, fontWeight: 800 }}>
              {stale ? '갱신 지연' : a.status}
            </span>
            {stale && <span style={{ fontSize: 8, color: C.warning }}>마지막 갱신 {a.lastUpdate}</span>}
          </div>
        </div>
      </div>

      {/* Card body */}
      <div style={{ padding: '10px 12px' }}>
        {/* Palettes */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: '#97A0AB', marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.07em' }}>담당 팔레트</div>
          <div style={{ display: 'flex', gap: 5 }}>
            {a.palettes.map(p => (
              <span key={p} style={{ padding: '2px 8px', background: '#F3EFFF', border: '1px solid #CEC5F0', borderRadius: 4, fontSize: 9, fontWeight: 700, color: '#5B3ECC' }}>{p}</span>
            ))}
          </div>
        </div>

        {/* Current step */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: '#97A0AB', marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.07em' }}>현재 피킹 단계</div>
          {stale ? (
            <span style={{ fontSize: 10, color: '#B0B8C4', fontStyle: 'italic' }}>갱신 지연 — 상태 미확인</span>
          ) : a.currentStep === '배차 대기' ? (
            <span style={{ fontSize: 10, color: '#C0C8D0' }}>배차 대기</span>
          ) : (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: C.text }}>{a.currentStep}</div>
              <div style={{ fontSize: 9, color: C.muted, marginTop: 2 }}>{a.stepProgress}</div>
            </div>
          )}
        </div>

        {/* Active TurtleBot */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: '#97A0AB', marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.07em' }}>작업 중인 TurtleBot</div>
          {a.activeTurtleBot ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 22, height: 22, borderRadius: 5, background: '#EDF6FF', border: `1.5px solid ${C.primary}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, fontSize: 9, color: '#167BEA' }}>
                {a.activeTurtleBot.replace('R-', '')}
              </div>
              <span style={{ fontSize: 10, fontWeight: 700 }}>{a.activeTurtleBot}</span>
            </div>
          ) : (
            <span style={{ fontSize: 10, color: '#C0C8D0' }}>—</span>
          )}
        </div>

        {/* Results */}
        <div style={{ display: 'flex', gap: 8, padding: '6px 8px', background: '#F8FAFC', borderRadius: 6, border: `1px solid ${C.line}` }}>
          <div style={{ flex: 1, textAlign: 'center' as const }}>
            <div style={{ fontSize: 16, fontWeight: 900, color: a.doneCount > 0 ? C.success : '#C0C8D0', lineHeight: 1, fontFamily: MONO }}>{a.doneCount}</div>
            <div style={{ fontSize: 8, color: '#97A0AB', marginTop: 2 }}>완료</div>
          </div>
          <div style={{ width: 1, background: C.line }} />
          <div style={{ flex: 1, textAlign: 'center' as const }}>
            <div style={{ fontSize: 16, fontWeight: 900, color: a.failCount > 0 ? C.danger : '#C0C8D0', lineHeight: 1, fontFamily: MONO }}>{a.failCount}</div>
            <div style={{ fontSize: 8, color: '#97A0AB', marginTop: 2 }}>실패</div>
          </div>
          <div style={{ width: 1, background: C.line }} />
          <div style={{ flex: 1.5, textAlign: 'center' as const }}>
            <div style={{ fontSize: 8, color: '#97A0AB', marginBottom: 2 }}>마지막 갱신</div>
            <div style={{ fontSize: 9, fontFamily: MONO, color: stale ? C.warning : C.muted, fontWeight: 600 }}>{a.lastUpdate}</div>
          </div>
        </div>

        {!stale && (
          <div style={{ marginTop: 7, fontSize: 8, color: '#C0C8D0', textAlign: 'center' as const }}>
            로봇팔은 지도 위 경로를 이동하지 않습니다 — 담당 팔레트 구역 고정 운용
          </div>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// LogsScreen
// ══════════════════════════════════════
function LogsScreen() {
  const [entries, setEntries]         = useState<SLogEntry[]>(() => [...SESSION_LOG].reverse())
  const [expandedId, setExpandedId]   = useState<string | null>('L024')
  const [filterType, setFilterType]   = useState<'all' | LogEvType>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const liveIdx  = useRef(0)
  const listRef  = useRef<HTMLDivElement>(null)

  // Simulate live stream entries
  useEffect(() => {
    const iv = window.setInterval(() => {
      if (liveIdx.current >= LIVE_LOG_QUEUE.length) { clearInterval(iv); return }
      const next: SLogEntry = { ...LIVE_LOG_QUEUE[liveIdx.current++], isNew: true }
      setEntries(prev => [next, ...prev])
      window.setTimeout(() => {
        setEntries(prev => prev.map(e => e.id === next.id ? { ...e, isNew: false } : e))
      }, 2000)
    }, 5500)
    return () => clearInterval(iv)
  }, [])

  const typeCounts = entries.reduce<Record<string, number>>((acc, e) => {
    acc[e.type] = (acc[e.type] ?? 0) + 1; return acc
  }, {})

  const filtered = entries.filter(e => {
    if (filterType !== 'all' && e.type !== filterType) return false
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      return (
        e.target.toLowerCase().includes(q) ||
        e.message.toLowerCase().includes(q) ||
        (e.detail.taskId ?? '').toLowerCase().includes(q) ||
        (e.detail.robotId ?? '').toLowerCase().includes(q)
      )
    }
    return true
  })

  const tgtColor = (t: SLogEntry['targetType']) =>
    t === 'robot' ? '#1A6FD8' : t === 'arm' ? '#7255CB' : t === 'task' ? '#147A4E' : C.muted

  const filterTypes: { value: 'all' | LogEvType; label: string }[] = [
    { value: 'all',  label: '전체' },
    { value: '배차',  label: '배차' },
    { value: '경로',  label: '경로' },
    { value: '피킹',  label: '피킹' },
    { value: '인계',  label: '인계' },
    { value: '제어',  label: '제어' },
    { value: '알람',  label: '알람' },
  ]

  return (
    <div style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0, background: C.bg }}>

      {/* ── Filter bar ── */}
      <div style={{ padding:'7px 18px', background: C.surface, borderBottom:`1px solid ${C.line}`, flexShrink:0, display:'flex', alignItems:'center', gap:8, flexWrap:'nowrap' }}>

        {/* Type chips */}
        <span style={{ fontSize:9, color:'#9AA4B0', fontWeight:700, letterSpacing:'0.06em', textTransform:'uppercase', flexShrink:0 }}>유형</span>
        <div style={{ display:'flex', gap:3, alignItems:'center' }}>
          {filterTypes.map(({ value, label }) => {
            const cfg = value === 'all' ? null : LOG_EVT_CFG[value]
            const active = filterType === value
            const cnt = value === 'all' ? entries.length : (typeCounts[value] ?? 0)
            return (
              <button key={value} onClick={() => setFilterType(value)}
                style={{
                  display:'flex', alignItems:'center', gap:3,
                  padding:'3px 8px', borderRadius:5, cursor:'pointer', outline:'none',
                  border:`1px solid ${active && cfg ? cfg.bd : active ? C.primary : C.line}`,
                  background: active && cfg ? cfg.bg : active ? '#EAF1FB' : C.subtle,
                  color: active && cfg ? cfg.color : active ? C.primary : C.muted,
                  fontWeight: active ? 800 : 500, fontSize:9.5, fontFamily: FONT,
                  transition:'all 0.1s',
                }}>
                {value !== 'all' && cfg && (
                  <span style={{ display:'flex', color: active ? cfg.color : '#9AA4B0' }}>
                    {LOG_ICONS[value]}
                  </span>
                )}
                {label}
                <span style={{ fontFamily:MONO, fontSize:8.5, fontWeight:700, opacity:0.75 }}>{cnt}</span>
              </button>
            )
          })}
        </div>

        <div style={{ width:1, height:16, background: C.line, flexShrink:0 }} />

        {/* Search */}
        <div style={{ position:'relative', display:'flex', alignItems:'center', flexShrink:0 }}>
          <svg style={{ position:'absolute', left:8 }} width="11" height="11" viewBox="0 0 11 11" fill="none">
            <circle cx="4.8" cy="4.8" r="3.5" stroke="#9AA4B0" strokeWidth="1.2"/>
            <line x1="7.5" y1="7.5" x2="10" y2="10" stroke="#9AA4B0" strokeWidth="1.2" strokeLinecap="round"/>
          </svg>
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.currentTarget.value)}
            placeholder="로봇 ID · 작업 ID · 메시지 검색"
            style={{
              paddingLeft:24, paddingRight:8, paddingTop:4, paddingBottom:4,
              width:220, background: C.subtle, border:`1px solid ${C.line}`,
              borderRadius:6, fontSize:10, color: C.text, outline:'none', fontFamily: FONT,
            }}
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')}
              style={{ position:'absolute', right:6, background:'none', border:'none', cursor:'pointer', color:'#9AA4B0', fontSize:11, lineHeight:1, padding:0 }}>×</button>
          )}
        </div>

        <div style={{ flex:1 }} />

        {/* Count */}
        <span style={{ fontSize:9, color: C.muted, fontFamily:MONO, flexShrink:0 }}>
          <span style={{ fontWeight:700, color: C.text }}>{filtered.length}</span> / {entries.length} 건
        </span>

        <div style={{ width:1, height:16, background: C.line, flexShrink:0 }} />

        {/* Live indicator */}
        <div style={{ display:'flex', alignItems:'center', gap:5, padding:'3px 9px', background:'#E8FBF2', borderRadius:20, border:'1px solid #A8DECE', flexShrink:0 }}>
          <div style={{ width:6, height:6, borderRadius:'50%', background:'#1FA466', animation:'pulse-dot 1.4s ease-in-out infinite' }} />
          <span style={{ fontSize:9, fontWeight:800, color:'#147A4E', letterSpacing:'0.03em' }}>라이브</span>
        </div>
      </div>

      {/* ── Column header ── */}
      <div style={{
        display:'grid', gridTemplateColumns:'78px 86px 108px 1fr 28px',
        padding:'0 18px', height:27, alignItems:'center',
        background: C.subtle, borderBottom:`1px solid ${C.line}`, flexShrink:0,
      }}>
        {['타임스탬프', '유형', '대상', '메시지', ''].map((h, i) => (
          <span key={i} style={{ fontSize:8, fontWeight:700, color:'#9AA4B0', letterSpacing:'0.07em', textTransform:'uppercase', fontFamily: FONT }}>{h}</span>
        ))}
      </div>

      {/* ── Log list ── */}
      <div ref={listRef} style={{ flex:1, overflowY:'auto', minHeight:0 }}>
        {filtered.length === 0 ? (
          <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100%', gap:10, padding:40 }}>
            <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
              <rect x="5" y="5" width="26" height="26" rx="4" stroke="#CDD5DF" strokeWidth="1.5"/>
              <line x1="10" y1="13" x2="26" y2="13" stroke="#CDD5DF" strokeWidth="1.5"/>
              <line x1="10" y1="18" x2="22" y2="18" stroke="#CDD5DF" strokeWidth="1.5"/>
              <line x1="10" y1="23" x2="18" y2="23" stroke="#CDD5DF" strokeWidth="1.5"/>
            </svg>
            <span style={{ color: C.muted, fontSize:12, fontWeight:600, fontFamily: FONT }}>표시할 로그가 없습니다</span>
            <span style={{ color:'#B0B8C4', fontSize:10, fontFamily: FONT }}>필터 또는 검색어를 변경해보세요</span>
          </div>
        ) : (
          <>
            {filtered.map(entry => {
              const cfg     = LOG_EVT_CFG[entry.type]
              const expanded = expandedId === entry.id
              const isAlarm  = entry.type === '알람'

              return (
                <div
                  key={entry.id}
                  className={entry.isNew ? 'log-row-new' : undefined}
                  onClick={() => setExpandedId(expanded ? null : entry.id)}
                  style={{
                    borderBottom: `1px solid ${C.line}`,
                    background: expanded ? '#F2F6FE' : isAlarm ? '#FFFBFB' : C.surface,
                    cursor: 'pointer',
                    borderLeft: isAlarm
                      ? `3px solid ${C.danger}`
                      : expanded
                        ? `3px solid ${C.primary}`
                        : '3px solid transparent',
                    transition: 'background 0.1s',
                  }}
                >
                  {/* ── Main row ── */}
                  <div style={{
                    display:'grid', gridTemplateColumns:'78px 86px 108px 1fr 28px',
                    padding:'7px 18px', alignItems:'center',
                  }}>
                    {/* Timestamp */}
                    <span style={{ fontFamily:MONO, fontSize:9.5, color: C.muted, letterSpacing:'0.03em' }}>{entry.ts}</span>

                    {/* Type badge */}
                    <div style={{ display:'inline-flex', alignItems:'center', gap:3.5, padding:'2px 7px', borderRadius:4,
                      background: cfg.bg, border:`1px solid ${cfg.bd}`, width:'fit-content', color: cfg.color }}>
                      {LOG_ICONS[entry.type]}
                      <span style={{ fontSize:9, fontWeight:800, fontFamily: FONT }}>{cfg.label}</span>
                    </div>

                    {/* Target */}
                    <span style={{
                      fontFamily: entry.targetType === 'task' ? MONO : FONT,
                      fontSize: entry.targetType === 'task' ? 9 : 10,
                      fontWeight: 700, color: tgtColor(entry.targetType),
                      overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                    }}>{entry.target}</span>

                    {/* Message */}
                    <span style={{
                      fontSize: 10.5, fontFamily: FONT,
                      color: isAlarm ? '#8C1C2A' : C.text,
                      fontWeight: isAlarm ? 600 : 400,
                      overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                    }}>{entry.message}</span>

                    {/* Chevron */}
                    <div style={{ display:'flex', justifyContent:'flex-end' }}>
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
                        style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition:'transform 0.15s' }}>
                        <path d="M3.5 5.5L7 9 10.5 5.5" stroke={expanded ? C.primary : '#C0C8D0'} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </div>
                  </div>

                  {/* ── Expanded detail panel ── */}
                  {expanded && (
                    <div style={{
                      padding:'8px 18px 12px 100px',
                      borderTop: `1px dashed ${C.line}`,
                      display:'flex', flexWrap:'wrap', gap:'10px 28px',
                    }}>
                      {([
                        ['작업 ID',   entry.detail.taskId,    MONO,  '#147A4E'],
                        ['주문 ID',   entry.detail.orderId,   MONO,  '#147A4E'],
                        ['로봇',      entry.detail.robotId,   FONT,  '#1A6FD8'],
                        ['로봇팔',    entry.detail.armId,     FONT,  '#7255CB'],
                        ['스테이션',  entry.detail.stationId, FONT,  '#55616E'],
                        ['경로',      entry.detail.route,     MONO,  '#55616E'],
                        ['소요',      entry.detail.duration,  FONT,  '#55616E'],
                        ['참조',      entry.detail.ref,       MONO,  C.danger],
                        ['운영자',    entry.detail.operator,  FONT,  '#55616E'],
                      ] as [string, string|undefined, string, string][])
                        .filter(([, v]) => v !== undefined)
                        .map(([label, value, font, color], i) => (
                          <div key={i} style={{ display:'flex', flexDirection:'column', gap:2, minWidth:72 }}>
                            <span style={{ fontSize:7.5, fontWeight:800, color:'#9AA4B0', letterSpacing:'0.07em', textTransform:'uppercase' }}>{label}</span>
                            <span style={{ fontSize:9.5, fontFamily: font, fontWeight: font === MONO ? 500 : 700, color }}>{value}</span>
                          </div>
                        ))
                      }
                      {(entry.detail.taskId) && (
                        <div style={{ display:'flex', alignItems:'flex-end', marginLeft:'auto' }}>
                          <button style={{ display:'flex', alignItems:'center', gap:4, padding:'3px 9px', background: C.subtle, border:`1px solid ${C.line}`, borderRadius:5, cursor:'pointer', fontSize:9, color: C.primary, fontWeight:700, outline:'none', fontFamily: FONT }}>
                            관련 작업 보기
                            <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5h6M5.5 2.5L8 5 5.5 7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            {/* Bottom end-of-session marker */}
            <div style={{ padding:'12px 18px', borderTop:`1px solid ${C.line}`, display:'flex', alignItems:'center', gap:8 }}>
              <div style={{ flex:1, height:1, background: C.line }} />
              <span style={{ fontSize:8.5, color:'#C0C8D0', fontFamily: FONT, whiteSpace:'nowrap' }}>세션 시작 · 09:28:05 · 이전 이력은 아카이브에 보관됩니다</span>
              <div style={{ flex:1, height:1, background: C.line }} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// OrdersScreen (Stage 5)
// ══════════════════════════════════════
const FILTER_ITEMS: { label: string; value: OrderFilterStatus }[] = [
  { label: '전체',     value: 'all'      },
  { label: '진행 중',  value: '진행 중'  },
  { label: '배차 대기', value: '배차 대기' },
  { label: '완료',     value: '완료'     },
  { label: '실행 불가', value: '실행 불가' },
]

function OrdersScreen({ isAdmin, onNavigateToRobot, onNavigateToAnalytics }: {
  isAdmin: boolean
  onNavigateToRobot?: (id: RobotId) => void
  onNavigateToAnalytics?: (taskId: string) => void
}) {
  const [filterStatus, setFilterStatus] = useState<OrderFilterStatus>('all')
  const [selectedId, setSelectedId]     = useState<string | null>(null)
  const [execState, setExecState]       = useState<ExecState>(null)
  const execTimers = useRef<number[]>([])
  const clearExecTimers = () => { execTimers.current.forEach(clearTimeout); execTimers.current = [] }

  const handleSelectOrder = (id: string) => {
    if (id !== selectedId) { setExecState(null); clearExecTimers() }
    setSelectedId(id)
  }
  const handleExecRequest = () => {
    setExecState('requesting'); clearExecTimers()
    const t1 = window.setTimeout(() => {
      setExecState('waiting')
      const t2 = window.setTimeout(() => setExecState('dispatched'), 1500)
      execTimers.current.push(t2)
    }, 1200)
    execTimers.current.push(t1)
  }

  const filteredOrders = filterStatus === 'all' ? ORDER_DATA : ORDER_DATA.filter(o => o.status === filterStatus)
  const ord = selectedId ? ORDER_DATA.find(o => o.id === selectedId) ?? null : null
  const canExecute = ord?.status === '배차 대기' && ord.feasible && isAdmin && execState === null

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

      {/* ── LEFT: order list ── */}
      <div style={{ width: 420, background: C.surface, borderRight: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div style={{ padding: '10px 14px 8px', borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 7 }}>
            <span style={{ fontWeight: 900, fontSize: 13 }}>주문 목록</span>
            <span style={{ fontSize: 9, color: '#B0B8C4' }}>※ 예시 주문 · 실제 데이터 연결 예정</span>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {FILTER_ITEMS.map(({ label, value }) => {
              const cnt = value === 'all' ? ORDER_DATA.length : ORDER_DATA.filter(o => o.status === value).length
              const a = filterStatus === value
              return (
                <button key={value} onClick={() => setFilterStatus(value)}
                  style={{ flex: 1, padding: '4px 2px', background: a ? '#EDF6FF' : '#F8FAFC', border: `1px solid ${a ? '#B9DAFB' : C.line}`, borderRadius: 5, fontSize: 9, fontWeight: a ? 800 : 500, color: a ? '#1675D4' : C.muted, cursor: 'pointer', outline: 'none' }}>
                  {label} {cnt}
                </button>
              )
            })}
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
          {filteredOrders.length === 0 && (
            <div style={{ textAlign: 'center' as const, padding: '30px 0', color: '#C0C8D0', fontSize: 11 }}>해당 상태의 주문이 없습니다</div>
          )}
          {filteredOrders.map(o => <OrderCard key={o.id} order={o} selected={selectedId === o.id} onClick={() => handleSelectOrder(o.id)} />)}
        </div>
      </div>

      {/* ── RIGHT: order detail ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: C.bg, minWidth: 0 }}>
        {!ord ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' as const, gap: 8 }}>
            <div style={{ fontSize: 22, opacity: 0.25 }}>📋</div>
            <div style={{ fontSize: 11, color: '#C0C8D0', fontWeight: 600 }}>왼쪽 목록에서 주문을 선택하면 상세 정보를 볼 수 있습니다</div>
          </div>
        ) : (
          <>
            {/* Detail header */}
            <div style={{ height: 50, background: C.surface, borderBottom: `1px solid ${C.line}`, padding: '0 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, overflow: 'hidden' }}>
                <span style={{ fontWeight: 900, fontSize: 14, fontFamily: MONO, letterSpacing: '-0.01em', whiteSpace: 'nowrap' as const }}>{ord.id}</span>
                <span style={{ padding: '2px 8px', background: ord.statusBg, color: ord.statusColor, borderRadius: 5, fontSize: 10, fontWeight: 800, whiteSpace: 'nowrap' as const }}>{ord.status}</span>
                {ord.assignedRobot && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '2px 8px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 5, flexShrink: 0 }}>
                    <span style={{ fontSize: 9, color: '#97A0AB' }}>담당</span>
                    <span style={{ fontWeight: 800, fontSize: 10, color: '#1675D4' }}>{ord.assignedRobot}</span>
                  </div>
                )}
                {!ord.feasible && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', background: '#FFF0F2', border: '1px solid #F1C8CD', borderRadius: 5, overflow: 'hidden' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: C.danger, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>⚠ {ord.blockReason}</span>
                  </div>
                )}
              </div>
              <button onClick={() => setSelectedId(null)}
                style={{ width: 28, height: 28, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: `1px solid ${C.line}`, borderRadius: 6, cursor: 'pointer', color: C.muted, fontSize: 12, outline: 'none', marginLeft: 8 }}>✕</button>
            </div>

            {/* Detail body */}
            <div style={{ flex: 1, overflowY: 'auto', minHeight: 0, padding: '14px 18px' }}>
              <div style={{ display: 'flex', gap: 14 }}>

                {/* LEFT col: palette plan + feasibility */}
                <div style={{ width: 310, flexShrink: 0 }}>
                  <div style={{ fontWeight: 900, fontSize: 11, marginBottom: 8 }}>팔레트 방문 계획</div>
                  <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', marginBottom: 12 }}>
                    {ord.paletteVisits.map((pv, i) => (
                      <div key={pv.paletteId} style={{ padding: '9px 12px', borderTop: i > 0 ? `1px solid ${C.line}` : undefined, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                        <div style={{ display: 'flex', flexDirection: 'column' as const, alignItems: 'center', gap: 2, flexShrink: 0 }}>
                          <div style={{ width: 22, height: 22, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: pv.stepStatus === 'done' ? C.success : pv.stepStatus === 'active' ? '#EDF6FF' : '#F3F6FA', border: `2px solid ${pv.stepStatus === 'done' ? C.success : pv.stepStatus === 'active' ? C.primary : '#DFE4EB'}`, fontWeight: 900, fontSize: 9, color: pv.stepStatus === 'done' ? '#fff' : pv.stepStatus === 'active' ? C.primary : '#B0B8C4' }}>
                            {pv.stepStatus === 'done' ? '✓' : pv.visitOrder}
                          </div>
                          {i < ord.paletteVisits.length - 1 && <div style={{ width: 1, height: 8, background: '#DFE4EB' }} />}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 3, flexWrap: 'wrap' as const }}>
                            <span style={{ fontWeight: 800, fontSize: 11 }}>{pv.paletteId}</span>
                            <span style={{ padding: '1px 5px', background: '#F3EFFF', border: '1px solid #CEC5F0', borderRadius: 4, fontSize: 8, fontWeight: 700, color: '#5B3ECC' }}>{pv.armId}</span>
                            {pv.stepStatus === 'active' && <span style={{ fontSize: 8, fontWeight: 800, color: C.primary }}>● 진행 중</span>}
                          </div>
                          <div style={{ fontSize: 10, color: C.muted }}>{pv.itemSummary}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Feasibility + packing */}
                  <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, padding: '10px 12px' }}>
                    <div style={{ fontWeight: 800, fontSize: 10, marginBottom: 7 }}>적재 정보</div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: `1px solid #F0F3F7` }}>
                      <span style={{ fontSize: 10, color: C.muted }}>적재 가능 여부</span>
                      <span style={{ fontSize: 10, fontWeight: 800, color: ord.feasible ? C.success : C.danger }}>{ord.feasible ? '가능' : '불가'}</span>
                    </div>
                    {!ord.feasible && (
                      <div style={{ padding: '6px 0', borderBottom: `1px solid #F0F3F7` }}>
                        <span style={{ fontSize: 9, color: C.danger, lineHeight: 1.5 }}>{ord.blockReason}</span>
                      </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '5px 0', borderBottom: `1px solid #F0F3F7` }}>
                      <span style={{ fontSize: 10, color: C.muted }}>예상 패킹 스테이션</span>
                      <span style={{ fontSize: 10, fontWeight: 600, color: ord.estimatedPacking.includes('계산') || ord.estimatedPacking.includes('예정') ? '#C0C8D0' : C.muted, textAlign: 'right' as const }}>{ord.estimatedPacking}</span>
                    </div>
                    <div style={{ padding: '6px 0 0' }}>
                      <div style={{ padding: '4px 7px', background: '#F8FAFC', border: `1px dashed ${C.line}`, borderRadius: 5, fontSize: 8, color: '#C0C8D0', lineHeight: 1.5 }}>
                        예상 패킹 스테이션은 경로 계획용 후보이며 독점 예약이 아닙니다. 실제 스테이션은 적재 완료 후 가용 여부 확인 후 결정됩니다.
                      </div>
                    </div>
                  </div>
                </div>

                {/* RIGHT col: stepper + time */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 900, fontSize: 11, marginBottom: 8 }}>작업 진행 흐름</div>
                  <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, padding: '14px 16px', marginBottom: 14 }}>
                    {ord.progressStep === -1 ? (
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '4px 0' }}>
                        <div style={{ width: 34, height: 34, borderRadius: '50%', background: '#FFF0F2', border: `2px solid ${C.danger}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, flexShrink: 0 }}>✕</div>
                        <div>
                          <div style={{ fontWeight: 800, fontSize: 12, color: C.danger, marginBottom: 4 }}>실행 불가</div>
                          <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.5 }}>{ord.blockReason}</div>
                        </div>
                      </div>
                    ) : (
                      <>
                        {/* Horizontal stepper */}
                        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 14 }}>
                          {TASK_STEPS.map((step, i) => {
                            const done    = ord.progressStep > i
                            const current = ord.progressStep === i
                            return (
                              <div key={step} style={{ flex: 1, display: 'flex', flexDirection: 'column' as const, alignItems: 'center', position: 'relative' as const }}>
                                {i > 0 && (
                                  <div style={{ position: 'absolute' as const, top: 13, right: '50%', left: '-50%', height: 2, background: done ? C.primary : '#E4E8ED', zIndex: 0 }} />
                                )}
                                <div style={{ position: 'relative' as const, zIndex: 1, width: 26, height: 26, borderRadius: '50%', background: done ? C.primary : current ? '#fff' : '#F3F6FA', border: `2.5px solid ${done ? C.primary : current ? C.primary : '#DFE4EB'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: done ? 11 : 10, fontWeight: 900, color: done ? '#fff' : current ? C.primary : '#C0C8D0' }}>
                                  {done ? '✓' : i + 1}
                                </div>
                                <div style={{ fontSize: 9, fontWeight: current ? 800 : done ? 600 : 400, color: current ? C.text : done ? C.muted : '#C0C8D0', marginTop: 5, textAlign: 'center' as const, lineHeight: 1.3, width: '100%', padding: '0 2px' }}>
                                  {step}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                        {/* Current step detail */}
                        {ord.progressStep < 4 && (
                          <div style={{ padding: '7px 10px', background: '#F0F7FF', border: '1px solid #C5DFFE', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 7 }}>
                            <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.primary, display: 'inline-block', flexShrink: 0 }} />
                            <span style={{ fontSize: 10, fontWeight: 700, color: '#1675D4' }}>현재: {ord.currentStepLabel}</span>
                            {ord.progressStep === 1 && ord.palettesTotal > 0 && (
                              <span style={{ fontSize: 9, color: C.muted }}>· 팔레트 {ord.palettesVisited}/{ord.palettesTotal} 방문 완료</span>
                            )}
                          </div>
                        )}
                        {ord.progressStep === 4 && (
                          <div style={{ padding: '7px 10px', background: '#E9F8F3', border: '1px solid #A8DECE', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 7 }}>
                            <span style={{ fontSize: 13 }}>✓</span>
                            <span style={{ fontSize: 10, fontWeight: 800, color: '#1a6e4f' }}>작업 완료</span>
                            {ord.actualComp && <span style={{ fontSize: 9, color: C.muted, marginLeft: 4, fontFamily: MONO }}>{ord.actualComp}</span>}
                          </div>
                        )}
                        {/* Next step hint (when not complete) */}
                        {ord.progressStep >= 0 && ord.progressStep < 4 && (
                          <div style={{ marginTop: 8, padding: '5px 10px', background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 5, fontSize: 9, color: '#B0B8C4' }}>
                            다음: <span style={{ fontWeight: 600, color: C.muted }}>{TASK_STEPS[ord.progressStep + 1]}</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>

                  {/* Time info */}
                  <div style={{ fontWeight: 900, fontSize: 11, marginBottom: 8 }}>시간 정보</div>
                  <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', marginBottom: 12 }}>
                    {[
                      { label: '최초 예상 완료', sub: '배차 시점 계산', value: ord.estCompOrig },
                      { label: '현재 예상 완료', sub: '진행 중 재계산', value: ord.estCompCurr },
                      ...(ord.actualComp ? [{ label: '실제 완료', sub: '기록됨', value: ord.actualComp }] : []),
                    ].map((row, i) => {
                      const isPlaceholder = row.value === '—' || row.value === '계산 전'
                      const isActual = row.label === '실제 완료'
                      return (
                        <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderTop: i > 0 ? `1px solid #F0F3F7` : undefined }}>
                          <div>
                            <div style={{ fontSize: 10, color: C.muted }}>{row.label}</div>
                            <div style={{ fontSize: 8, color: '#C0C8D0', marginTop: 1 }}>{row.sub}</div>
                          </div>
                          <span style={{ fontFamily: isPlaceholder ? FONT : MONO, fontSize: isPlaceholder ? 10 : 11, fontWeight: 700, color: isActual ? C.success : isPlaceholder ? '#C0C8D0' : C.text, fontStyle: isPlaceholder ? 'italic' as const : 'normal' as const }}>
                            {row.value}
                          </span>
                        </div>
                      )
                    })}
                    <div style={{ padding: '5px 12px 7px', background: '#F8FAFC', borderTop: `1px solid #F0F3F7`, fontSize: 8, color: '#C0C8D0', lineHeight: 1.5 }}>
                      ※ 시간 값은 계산 기준이 다를 수 있어 직접 비교하지 마세요. 상세 기준은 시스템 로그에서 확인할 수 있습니다.
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Action bar */}
            <div style={{ height: 58, background: C.surface, borderTop: `1px solid ${C.line}`, padding: '0 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
              {/* Left: status messages */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {execState === 'requesting' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 6 }}>
                    <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block', fontSize: 11, color: C.primary }}>⟳</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#1675D4' }}>요청 전송 중…</span>
                  </div>
                )}
                {execState === 'waiting' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', background: '#FFF9EE', border: '1px solid #ECD5AA', borderRadius: 6 }}>
                    <span style={{ animation: 'spin 1.5s linear infinite', display: 'inline-block', fontSize: 11, color: C.warning }}>⟳</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#9A6A10' }}>서버 배차 확인 대기 중…</span>
                    <span style={{ fontSize: 9, color: '#C0C8D0' }}>백엔드에서 로봇 배정 중</span>
                  </div>
                )}
                {execState === 'dispatched' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', background: '#E9F8F3', border: '1px solid #A8DECE', borderRadius: 6 }}>
                    <span style={{ fontSize: 12, color: C.success }}>✓</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#27966e' }}>배차 확인됨 — 로봇 배정 대기</span>
                  </div>
                )}
                {execState === 'rejected' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', background: '#FFF0F2', border: '1px solid #F1C8CD', borderRadius: 6 }}>
                    <span style={{ fontSize: 11, color: C.danger }}>✕</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: C.danger }}>요청 거절됨 — 서버에서 거부</span>
                  </div>
                )}
                {execState === null && !isAdmin && (
                  <span style={{ fontSize: 9, color: '#B0B8C4' }}>관리자 모드 전환 시 작업 실행 버튼이 활성화됩니다</span>
                )}
                {execState === null && isAdmin && !ord.feasible && (
                  <span style={{ fontSize: 9, color: C.danger, fontWeight: 600 }}>⚠ 실행 불가 — {ord.blockReason}</span>
                )}
                {execState === null && isAdmin && ord.feasible && ord.status !== '배차 대기' && (
                  <span style={{ fontSize: 9, color: '#B0B8C4' }}>
                    {ord.status === '진행 중' ? '이미 진행 중인 작업입니다' : ord.status === '완료' ? '이미 완료된 작업입니다' : '배차 대기 상태가 아닙니다'}
                  </span>
                )}
              </div>
              {/* Right: navigation + execute */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                {/* Robot detail link */}
                {ord.assignedRobot && onNavigateToRobot && (
                  <button onClick={() => onNavigateToRobot!(ord.assignedRobot!)}
                    style={{ padding: '7px 12px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 7, fontSize: 10, fontWeight: 700, color: '#1675D4', cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
                    {ord.assignedRobot} 로봇 상세 →
                  </button>
                )}
                {/* Analytics link — only for completed orders that have a recorded task */}
                {ord.status === '완료' && onNavigateToAnalytics && (() => {
                  const at = AT_TASKS.find(t => t.orderId === ord.id && t.taskStatus !== '기록 없음')
                  return at ? (
                    <button onClick={() => onNavigateToAnalytics!(at.taskId)}
                      style={{ padding: '7px 12px', background: '#F3F6FA', border: `1px solid ${C.line}`, borderRadius: 7, fontSize: 10, fontWeight: 700, color: C.muted, cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
                      이동시간 분석 →
                    </button>
                  ) : null
                })()}
                {(execState === 'dispatched' || execState === 'rejected') && (
                  <button onClick={() => setExecState(null)} style={{ padding: '7px 14px', background: '#F3F6FA', border: `1px solid ${C.line}`, borderRadius: 7, fontSize: 10, fontWeight: 600, color: C.muted, cursor: 'pointer', outline: 'none' }}>
                    닫기
                  </button>
                )}
                <button
                  disabled={!canExecute}
                  onClick={canExecute ? handleExecRequest : undefined}
                  title={!isAdmin ? '관리자 모드 필요' : !ord.feasible ? ord.blockReason ?? '실행 불가' : undefined}
                  style={{ padding: '8px 22px', borderRadius: 7, border: 'none', background: canExecute ? C.primary : '#E8ECF1', color: canExecute ? '#fff' : '#C0C8D0', fontSize: 11, fontWeight: 800, cursor: canExecute ? 'pointer' : 'default', outline: 'none', transition: 'background 0.15s' }}>
                  작업 실행
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function OrderCard({ order, selected, onClick }: { order: OrderEntry; selected: boolean; onClick: () => void }) {
  const pct = order.palettesTotal > 0 ? (order.palettesVisited / order.palettesTotal) * 100 : 0
  return (
    <div onClick={onClick} style={{ marginBottom: 6, padding: '10px 12px', background: selected ? '#EEF6FF' : C.surface, border: `1px solid ${selected ? '#A8CAEF' : C.line}`, borderLeft: `3px solid ${selected ? C.primary : order.statusColor}`, borderRadius: 9, cursor: 'pointer', transition: 'all 0.12s', boxShadow: selected ? `0 0 0 3px rgba(26,111,216,0.07), ${E1}` : E1 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
        <span style={{ fontWeight: 900, fontSize: 11, fontFamily: MONO }}>{order.id}</span>
        <span style={{ padding: '2px 7px', background: order.statusBg, color: order.statusColor, borderRadius: 4, fontSize: 9, fontWeight: 800 }}>{order.status}</span>
      </div>
      <div style={{ fontSize: 10, color: C.muted, marginBottom: 5 }}>{order.itemSummary} · {order.qtyTotal}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
        {order.assignedRobot ? (
          <span style={{ fontSize: 9, fontWeight: 700, color: '#1675D4', background: '#EDF6FF', padding: '1px 5px', borderRadius: 3 }}>{order.assignedRobot}</span>
        ) : (
          <span style={{ fontSize: 9, color: '#C0C8D0' }}>미배정</span>
        )}
        <span style={{ fontSize: 9, color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{order.currentStepLabel}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ flex: 1, height: 4, background: '#E7EBF0', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: order.status === '완료' ? C.success : order.status === '실행 불가' ? C.danger : C.primary, borderRadius: 2 }} />
        </div>
        <span style={{ fontSize: 8, color: '#B0B8C4', whiteSpace: 'nowrap' as const, fontFamily: MONO }}>{order.palettesVisited}/{order.palettesTotal}</span>
        {order.actualComp ? (
          <span style={{ fontSize: 8, color: C.success, fontWeight: 700, fontFamily: MONO, whiteSpace: 'nowrap' as const }}>완료 {order.actualComp}</span>
        ) : order.estCompCurr !== '계산 전' && order.estCompCurr !== '—' ? (
          <span style={{ fontSize: 8, color: '#B0B8C4', whiteSpace: 'nowrap' as const }}>예상 {order.estCompCurr}</span>
        ) : null}
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// AlarmsScreen (Stage 6)
// ══════════════════════════════════════
function AlarmsScreen({ isAdmin, onNavigateToRobot, onNavigateToOrder }: {
  isAdmin: boolean
  onNavigateToRobot: (id: RobotId) => void
  onNavigateToOrder: () => void
}) {
  const [leftTab, setLeftTab]           = useState<'alarms' | 'history'>('alarms')
  const [alarmFilter, setAlarmFilter]   = useState<AlarmFilterType>('all')
  const [selectedAlarmId, setAlarmId]   = useState<string | null>(null)
  const [selectedHistId, setHistId]     = useState<string | null>(null)
  const [histType, setHistType]         = useState('all')
  const [histTarget, setHistTarget]     = useState('all')
  const [ackState, setAckState]         = useState<AckState>(null)
  const ackTimers = useRef<number[]>([])

  useEffect(() => { ackTimers.current.forEach(clearTimeout); setAckState(null) }, [selectedAlarmId])

  const handleAck = () => {
    setAckState('requesting'); ackTimers.current.forEach(clearTimeout)
    const t = window.setTimeout(() => setAckState('acknowledged'), 1400)
    ackTimers.current = [t]
  }

  const filteredAlarms = alarmFilter === 'all' ? ALARM_DATA : ALARM_DATA.filter(a => a.state === alarmFilter)
  const filteredHistory = HISTORY_DATA.filter(h =>
    (histType === 'all' || h.eventType === histType) &&
    (histTarget === 'all' || h.target === histTarget)
  )
  const selectedAlarm = selectedAlarmId ? ALARM_DATA.find(a => a.id === selectedAlarmId) ?? null : null
  const selectedHist  = selectedHistId  ? HISTORY_DATA.find(h => h.id === selectedHistId) ?? null : null

  const counts = {
    active:   ALARM_DATA.filter(a => a.state === '발생 중').length,
    needsAck: ALARM_DATA.filter(a => a.state === '확인 필요').length,
    resolved: ALARM_DATA.filter(a => a.state === '해결됨').length,
  }

  const ALARM_FILTERS: { v: AlarmFilterType; label: string; cnt: number; color: string; bg: string; bd: string }[] = [
    { v: 'all',     label: '전체',    cnt: ALARM_DATA.length, color: C.muted,    bg: '#F3F6FA', bd: C.line     },
    { v: '발생 중',  label: '발생 중',  cnt: counts.active,    color: C.danger,   bg: '#FFF0F2', bd: '#F1C8CD'  },
    { v: '확인 필요', label: '확인 필요', cnt: counts.needsAck, color: '#9A6A10',  bg: '#FFF5DF', bd: '#ECD5AA' },
    { v: '해결됨',   label: '해결됨',   cnt: counts.resolved,  color: '#55616E',  bg: '#F3F6FA', bd: '#DFE4EB'  },
  ]

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

      {/* ── LEFT: list panel ── */}
      <div style={{ width: 510, background: C.surface, borderRight: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>

        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
          {(['alarms', 'history'] as const).map(tab => (
            <button key={tab} onClick={() => setLeftTab(tab)}
              style={{ flex: 1, padding: '9px 0', background: 'transparent', border: 'none', borderBottom: `2px solid ${leftTab === tab ? C.primary : 'transparent'}`, fontSize: 11, fontWeight: leftTab === tab ? 800 : 500, color: leftTab === tab ? C.primary : C.muted, cursor: 'pointer', outline: 'none' }}>
              {tab === 'alarms' ? `알람 목록 (${ALARM_DATA.length})` : `이벤트 이력 (${HISTORY_DATA.length})`}
            </button>
          ))}
        </div>

        {leftTab === 'alarms' ? (<>
          {/* Filter row */}
          <div style={{ padding: '7px 12px 6px', borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 5 }}>
              <span style={{ fontSize: 8, color: '#B0B8C4', marginRight: 2 }}>필터</span>
              {ALARM_FILTERS.map(({ v, label, cnt, color, bg, bd }) => {
                const a = alarmFilter === v
                return (
                  <button key={v} onClick={() => setAlarmFilter(v)}
                    style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 8px', background: a ? bg : '#F8FAFC', border: `1px solid ${a ? bd : C.line}`, borderRadius: 5, fontSize: 9, fontWeight: a ? 800 : 500, color: a ? color : C.muted, cursor: 'pointer', outline: 'none' }}>
                    {label} <span style={{ fontFamily: MONO, fontWeight: 900 }}>{cnt}</span>
                  </button>
                )
              })}
            </div>
            <div style={{ fontSize: 8, color: '#C0C8D0' }}>※ 예시 알람 · 실제 데이터 연결 예정</div>
          </div>

          {/* Alarm list */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredAlarms.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column' as const, alignItems: 'center', justifyContent: 'center', padding: '48px 20px', gap: 8 }}>
                <div style={{ fontSize: 26, opacity: 0.25 }}>🔔</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#C0C8D0' }}>알람 없음</div>
                <div style={{ fontSize: 9, color: '#D0D5DC', textAlign: 'center' as const, lineHeight: 1.5 }}>해당 상태의 알람이 없습니다<br/>필터를 변경하거나 전체 보기를 선택해주세요</div>
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#F8FAFC' }}>
                    {['심각도', '발생 시각', '대상', '내용', '상태'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '6px 8px 6px 10px', fontSize: 8, color: '#697687', fontWeight: 700, borderBottom: `1px solid ${C.line}`, whiteSpace: 'nowrap' as const }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredAlarms.map((alarm, i) => {
                    const sev = SEVERITY_CFG[alarm.severity]
                    const st  = STATE_CFG[alarm.state]
                    const sel = selectedAlarmId === alarm.id
                    return (
                      <tr key={alarm.id}
                        onClick={() => { setAlarmId(alarm.id); setHistId(null) }}
                        style={{ borderTop: i > 0 ? `1px solid #F0F3F7` : undefined, background: sel ? '#F0F7FF' : 'transparent', cursor: 'pointer', transition: 'background 0.1s', borderLeft: `3px solid ${sel ? C.primary : sev.color}` }}
                        onMouseEnter={e => { if (!sel) e.currentTarget.style.background = '#F8FBFF' }}
                        onMouseLeave={e => { if (!sel) e.currentTarget.style.background = 'transparent' }}>
                        <td style={{ padding: '8px 8px 8px 10px', whiteSpace: 'nowrap' as const }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            <span style={{ width: 7, height: 7, borderRadius: '50%', background: sev.color, display: 'inline-block', flexShrink: 0, boxShadow: alarm.state === '발생 중' ? `0 0 0 3px ${sev.bg}` : 'none' }} />
                            <span style={{ padding: '1px 5px', background: sev.bg, border: `1px solid ${sev.bd}`, borderRadius: 3, fontSize: 8, fontWeight: 800, color: sev.color }}>{alarm.severity}</span>
                          </div>
                        </td>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontSize: 9, color: C.muted, whiteSpace: 'nowrap' as const }}>{alarm.occurredAt}</td>
                        <td style={{ padding: '8px 10px', fontWeight: 800, fontSize: 10, whiteSpace: 'nowrap' as const }}>{alarm.target}</td>
                        <td style={{ padding: '8px 10px', fontSize: 10, color: C.text, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{alarm.content}</td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' as const }}>
                          <span style={{ padding: '2px 6px', background: st.bg, border: `1px solid ${st.bd}`, borderRadius: 4, fontSize: 8, fontWeight: 800, color: st.color }}>{alarm.state}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>) : (<>
          {/* History filter row */}
          <div style={{ padding: '7px 12px', borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
            <div style={{ fontSize: 8, color: '#B0B8C4', marginBottom: 5 }}>
              현재 세션 수집 이력 · {HISTORY_DATA.length}건 · 세션 종료 시 초기화 ※ 예시 데이터
            </div>
            <div style={{ marginBottom: 5 }}>
              <div style={{ fontSize: 8, color: '#97A0AB', fontWeight: 700, marginBottom: 3 }}>유형</div>
              <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 3 }}>
                {HIST_TYPES.map(t => (
                  <button key={t} onClick={() => setHistType(t)}
                    style={{ padding: '2px 7px', background: histType === t ? '#EDF6FF' : '#F8FAFC', border: `1px solid ${histType === t ? '#B9DAFB' : C.line}`, borderRadius: 4, fontSize: 8, fontWeight: histType === t ? 800 : 400, color: histType === t ? '#1675D4' : C.muted, cursor: 'pointer', outline: 'none' }}>
                    {t === 'all' ? '전체' : t}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 8, color: '#97A0AB', fontWeight: 700, marginBottom: 3 }}>대상</div>
              <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 3 }}>
                {HIST_TARGETS.map(t => (
                  <button key={t} onClick={() => setHistTarget(t)}
                    style={{ padding: '2px 7px', background: histTarget === t ? '#EDF6FF' : '#F8FAFC', border: `1px solid ${histTarget === t ? '#B9DAFB' : C.line}`, borderRadius: 4, fontSize: 8, fontWeight: histTarget === t ? 800 : 400, color: histTarget === t ? '#1675D4' : C.muted, cursor: 'pointer', outline: 'none' }}>
                    {t === 'all' ? '전체' : t}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* History list */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredHistory.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column' as const, alignItems: 'center', justifyContent: 'center', padding: '48px 20px', gap: 8 }}>
                <div style={{ fontSize: 26, opacity: 0.2 }}>📋</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#C0C8D0' }}>이력 데이터 없음</div>
                <div style={{ fontSize: 9, color: '#D0D5DC', textAlign: 'center' as const, lineHeight: 1.5 }}>현재 세션에서 수집된 이력이 없거나<br/>필터 조건에 맞는 이벤트가 없습니다</div>
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#F8FAFC' }}>
                    {['시각', '대상', '유형', '내용'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '6px 8px 6px 10px', fontSize: 8, color: '#697687', fontWeight: 700, borderBottom: `1px solid ${C.line}`, whiteSpace: 'nowrap' as const }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...filteredHistory].reverse().map((evt, i) => {
                    const ec  = EVT_CFG[evt.eventType] ?? { color: C.muted, bg: '#F3F6FA' }
                    const sel = selectedHistId === evt.id
                    return (
                      <tr key={evt.id}
                        onClick={() => { setHistId(evt.id); setAlarmId(null) }}
                        style={{ borderTop: i > 0 ? `1px solid #F0F3F7` : undefined, background: sel ? '#F0F7FF' : 'transparent', cursor: 'pointer', transition: 'background 0.1s', borderLeft: `3px solid ${sel ? C.primary : ec.color}` }}
                        onMouseEnter={e => { if (!sel) e.currentTarget.style.background = '#F8FBFF' }}
                        onMouseLeave={e => { if (!sel) e.currentTarget.style.background = 'transparent' }}>
                        <td style={{ padding: '7px 10px', fontFamily: MONO, fontSize: 9, color: C.muted, whiteSpace: 'nowrap' as const }}>{evt.time}</td>
                        <td style={{ padding: '7px 10px', fontWeight: 800, fontSize: 10, whiteSpace: 'nowrap' as const }}>{evt.target}</td>
                        <td style={{ padding: '7px 10px', whiteSpace: 'nowrap' as const }}>
                          <span style={{ padding: '1px 5px', background: ec.bg, borderRadius: 4, fontSize: 8, fontWeight: 700, color: ec.color }}>{evt.eventType}</span>
                        </td>
                        <td style={{ padding: '7px 10px', fontSize: 10, color: C.text, maxWidth: 190, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{evt.description}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>)}
      </div>

      {/* ── RIGHT: detail panel ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: C.bg, minWidth: 0, overflow: 'hidden' }}>
        {selectedAlarm ? (
          <AlarmDetailView alarm={selectedAlarm} isAdmin={isAdmin} ackState={ackState} onAck={handleAck} onNavigateToRobot={onNavigateToRobot} onNavigateToOrder={onNavigateToOrder} />
        ) : selectedHist ? (
          <HistoryDetailView event={selectedHist} onNavigateToRobot={onNavigateToRobot} onNavigateToOrder={onNavigateToOrder} />
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' as const, gap: 8 }}>
            <div style={{ fontSize: 24, opacity: 0.2 }}>🔔</div>
            <div style={{ fontSize: 11, color: '#C0C8D0', fontWeight: 600 }}>알람 또는 이벤트를 선택하면 상세 정보를 볼 수 있습니다</div>
          </div>
        )}
      </div>
    </div>
  )
}

function AlarmDetailView({ alarm, isAdmin, ackState, onAck, onNavigateToRobot, onNavigateToOrder }: {
  alarm: AlarmEntry; isAdmin: boolean; ackState: AckState
  onAck: () => void; onNavigateToRobot: (id: RobotId) => void; onNavigateToOrder: () => void
}) {
  const sev = SEVERITY_CFG[alarm.severity]
  const st  = STATE_CFG[alarm.state]
  const canAck = isAdmin && alarm.state !== '해결됨' && ackState === null
  const isRobot = alarm.targetType === 'robot' && alarm.targetId && (['R-01','R-02','R-03'] as string[]).includes(alarm.targetId)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '12px 18px 10px', background: C.surface, borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
              <span style={{ fontWeight: 900, fontSize: 12, fontFamily: MONO }}>{alarm.id}</span>
              <span style={{ padding: '2px 7px', background: sev.bg, border: `1px solid ${sev.bd}`, borderRadius: 4, fontSize: 10, fontWeight: 800, color: sev.color }}>{alarm.severity}</span>
              <span style={{ padding: '2px 7px', background: st.bg, border: `1px solid ${st.bd}`, borderRadius: 4, fontSize: 10, fontWeight: 800, color: st.color }}>{alarm.state}</span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{alarm.content}</div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
            {isRobot && (
              <button onClick={() => onNavigateToRobot(alarm.targetId as RobotId)}
                style={{ padding: '5px 11px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 6, fontSize: 10, fontWeight: 700, color: '#1675D4', cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
                {alarm.targetId} 로봇 상세 →
              </button>
            )}
            {alarm.relatedOrderId && (
              <button onClick={onNavigateToOrder}
                style={{ padding: '5px 11px', background: '#F3F6FA', border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 10, fontWeight: 700, color: C.muted, cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
                주문·작업 →
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
        {/* Info grid */}
        <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', marginBottom: 14 }}>
          <div style={{ padding: '7px 12px', background: '#F8FAFC', borderBottom: `1px solid ${C.line}`, fontSize: 10, fontWeight: 800 }}>기본 정보</div>
          {[
            { label: '발생 시각',    value: alarm.occurredAt, mono: true },
            { label: '마지막 갱신',  value: alarm.updatedAt,  mono: true },
            { label: '대상',        value: `${alarm.target} (${alarm.targetType === 'robot' ? '이동 로봇' : alarm.targetType === 'arm' ? '로봇팔' : '시스템'})` },
            { label: '발생 위치',   value: alarm.location },
            { label: '관련 작업 ID', value: alarm.relatedTaskId  ?? '정보 없음' },
            { label: '관련 주문',   value: alarm.relatedOrderId ?? '정보 없음' },
          ].map((row, i) => (
            <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 12px', borderTop: i > 0 ? `1px solid #F0F3F7` : undefined }}>
              <span style={{ fontSize: 10, color: C.muted }}>{row.label}</span>
              <span style={{ fontSize: 10, fontWeight: 600, fontFamily: row.mono ? MONO : undefined, color: (row.value === '정보 없음') ? '#C0C8D0' : C.text }}>{row.value}</span>
            </div>
          ))}
        </div>

        {/* Device state */}
        <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', marginBottom: 14 }}>
          <div style={{ padding: '7px 12px', background: '#F8FAFC', borderBottom: `1px solid ${C.line}`, fontSize: 10, fontWeight: 800 }}>해당 시점 장치 상태</div>
          <div style={{ padding: '10px 12px' }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: alarm.deviceStateAtTime.includes('확인 불가') ? C.warning : alarm.deviceStateAtTime === '정보 없음' ? '#C0C8D0' : C.text, fontStyle: alarm.deviceStateAtTime === '정보 없음' ? 'italic' as const : 'normal' as const }}>
              {alarm.deviceStateAtTime}
            </div>
            {alarm.deviceStateAtTime.includes('확인 불가') && (
              <div style={{ fontSize: 9, color: '#B0B8C4', marginTop: 5, lineHeight: 1.5, padding: '4px 8px', background: '#FFFBF0', border: '1px solid #ECD5AA', borderRadius: 5 }}>
                통신이 끊긴 장치의 상태는 단정할 수 없습니다. 실제 상태는 현장 확인이 필요합니다.
              </div>
            )}
          </div>
        </div>

        {/* Description */}
        <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden' }}>
          <div style={{ padding: '7px 12px', background: '#F8FAFC', borderBottom: `1px solid ${C.line}`, fontSize: 10, fontWeight: 800 }}>알람 설명</div>
          <div style={{ padding: '12px', fontSize: 11, color: C.text, lineHeight: 1.75 }}>{alarm.description}</div>
        </div>
      </div>

      {/* Action bar */}
      <div style={{ height: 56, background: C.surface, borderTop: `1px solid ${C.line}`, padding: '0 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9, color: '#B0B8C4' }}>
          {ackState === 'requesting' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 6 }}>
              <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block', color: C.primary }}>⟳</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: '#1675D4' }}>요청 처리 중…</span>
            </div>
          )}
          {ackState === 'acknowledged' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: '#E9F8F3', border: '1px solid #A8DECE', borderRadius: 6 }}>
              <span style={{ color: C.success }}>✓</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: '#27966e' }}>알람 확인 처리됨</span>
            </div>
          )}
          {ackState === null && !isAdmin && '관리자 모드 전환 시 알람 확인 버튼이 활성화됩니다'}
          {ackState === null && isAdmin && alarm.state === '해결됨' && '이미 해결된 알람입니다'}
          <span style={{ fontSize: 8, color: '#C0C8D0', marginLeft: 4 }}>원격 제어 및 로봇 이동 명령은 통합 관제 화면에서 수행하세요</span>
        </div>
        <button disabled={!canAck} onClick={canAck ? onAck : undefined}
          style={{ padding: '7px 18px', background: canAck ? '#EDF6FF' : '#F3F6FA', border: `1px solid ${canAck ? '#B9DAFB' : C.line}`, borderRadius: 7, fontSize: 10, fontWeight: 800, color: canAck ? '#1675D4' : '#C0C8D0', cursor: canAck ? 'pointer' : 'default', outline: 'none' }}>
          알람 확인
        </button>
      </div>
    </div>
  )
}

function HistoryDetailView({ event, onNavigateToRobot, onNavigateToOrder }: {
  event: HistoryEntry
  onNavigateToRobot: (id: RobotId) => void
  onNavigateToOrder: () => void
}) {
  const ec = EVT_CFG[event.eventType] ?? { color: C.muted, bg: '#F3F6FA' }
  const isRobotLink = event.relatedRobotId && (['R-01','R-02','R-03'] as string[]).includes(event.relatedRobotId)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '12px 18px 10px', background: C.surface, borderBottom: `1px solid ${C.line}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
          <span style={{ fontWeight: 900, fontSize: 12, fontFamily: MONO }}>{event.id}</span>
          <span style={{ padding: '2px 7px', background: ec.bg, borderRadius: 4, fontSize: 10, fontWeight: 800, color: ec.color }}>{event.eventType}</span>
          <span style={{ fontSize: 10, fontFamily: MONO, color: C.muted }}>{event.time}</span>
        </div>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{event.description}</div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
        <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 9, overflow: 'hidden', marginBottom: 16 }}>
          {[
            { label: '이벤트 시각',  value: event.time,      mono: true },
            { label: '대상',        value: event.target                },
            { label: '유형',        value: event.eventType             },
            { label: '관련 로봇',   value: event.relatedRobotId  ?? '정보 없음' },
            { label: '관련 주문',   value: event.relatedOrderId ?? '정보 없음' },
          ].map((row, i) => (
            <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 12px', background: i === 0 ? '#F8FAFC' : 'transparent', borderTop: i > 0 ? `1px solid #F0F3F7` : undefined, borderBottom: i === 0 ? `1px solid ${C.line}` : undefined }}>
              <span style={{ fontSize: 10, color: i === 0 ? '#697687' : C.muted, fontWeight: i === 0 ? 800 : 400 }}>{row.label}</span>
              <span style={{ fontSize: 10, fontWeight: 600, fontFamily: row.mono ? MONO : undefined, color: row.value === '정보 없음' ? '#C0C8D0' : C.text }}>{row.value}</span>
            </div>
          ))}
        </div>

        {/* Navigation */}
        <div style={{ fontWeight: 900, fontSize: 11, marginBottom: 8 }}>관련 화면 이동</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' as const }}>
          {isRobotLink && (
            <button onClick={() => onNavigateToRobot(event.relatedRobotId as RobotId)}
              style={{ padding: '8px 14px', background: '#EDF6FF', border: '1px solid #B9DAFB', borderRadius: 7, fontSize: 10, fontWeight: 700, color: '#1675D4', cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
              {event.relatedRobotId} 로봇 상세 보기 →
            </button>
          )}
          {event.relatedOrderId && (
            <button onClick={onNavigateToOrder}
              style={{ padding: '8px 14px', background: '#F3F6FA', border: `1px solid ${C.line}`, borderRadius: 7, fontSize: 10, fontWeight: 700, color: C.muted, cursor: 'pointer', outline: 'none', whiteSpace: 'nowrap' as const }}>
              주문·작업 화면으로 이동 →
            </button>
          )}
          {!isRobotLink && !event.relatedOrderId && (
            <span style={{ fontSize: 9, color: '#C0C8D0' }}>연결된 관련 화면이 없습니다</span>
          )}
        </div>
        <div style={{ marginTop: 12, padding: '6px 10px', background: '#F8FAFC', border: `1px dashed ${C.line}`, borderRadius: 6, fontSize: 8, color: '#C0C8D0', lineHeight: 1.5 }}>
          이벤트 이력은 현재 세션에서 수집된 데이터입니다. 1차에서는 PostgreSQL 장기 이력을 제공하지 않습니다.
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// AnalyticsScreen (Stage 7)
// ══════════════════════════════════════
function AnalyticsScreen({ initialTaskId }: { initialTaskId?: string }) {
  const [selectedTaskId, setSelectedTaskId] = useState<string>(initialTaskId ?? AT_TASKS[0].taskId)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  useEffect(() => { if (initialTaskId) { setSelectedTaskId(initialTaskId); setSelectedEdgeId(null) } }, [initialTaskId])
  const edgeRowRefs = useRef<Record<string, HTMLTableRowElement | null>>({})

  const task = AT_TASKS.find(t => t.taskId === selectedTaskId) ?? AT_TASKS[0]

  const handleEdgeSelect = (id: string) => {
    setSelectedEdgeId(prev => prev === id ? null : id)
    if (edgeRowRefs.current[id]) {
      edgeRowRefs.current[id]!.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }

  const handleMapEdgeClick = (id: string) => {
    setSelectedEdgeId(prev => prev === id ? null : id)
    if (edgeRowRefs.current[id]) {
      edgeRowRefs.current[id]!.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }

  const nodeMap = Object.fromEntries(AT_NODES.map(n => [n.id, n]))

  const completedMoveActual = task.taskStatus !== '기록 없음'
    ? task.edges.filter(e => e.status === '완료' && e.actualMoveSec !== null).reduce((s, e) => s + (e.actualMoveSec ?? 0), 0)
    : null

  const delayedEdges = task.edges.filter(e => e.actualMoveSec !== null && e.actualMoveSec > e.planMoveSec)

  const fmtSec = (s: number | null) => s === null ? '—' : s >= 60 ? `${Math.floor(s/60)}m ${s%60}s` : `${s}s`

  const edgeLineColor = (e: ATEdge) => {
    if (e.status === '대기') return '#C8D0DA'
    if (e.status === '진행 중') return C.primary
    if (e.delayReason) return C.warning
    return C.success
  }

  const edgeLineDash = (e: ATEdge) => {
    if (e.status === '대기') return '5,4'
    if (e.status === '진행 중') return '6,4'
    return '0'
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, fontFamily: FONT }}>

      {/* ── TOP: task selector + summary ── */}
      <div style={{ background: C.surface, borderBottom: `1px solid ${C.line}`, flexShrink: 0, padding: '8px 16px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' as const }}>

          {/* Task selector */}
          <div style={{ flexShrink: 0 }}>
            <div style={{ fontSize: 9, color: C.muted, fontWeight: 700, marginBottom: 4 }}>분석할 작업 선택</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {AT_TASKS.map(t => {
                const sel = t.taskId === selectedTaskId
                const stColor = t.taskStatus === '완료' ? '#1675d4' : t.taskStatus === '진행 중' ? '#27966e' : C.muted
                const stBg   = t.taskStatus === '완료' ? '#EDF6FF' : t.taskStatus === '진행 중' ? '#E9F8F3' : '#F3F6FA'
                return (
                  <button key={t.taskId} onClick={() => { setSelectedTaskId(t.taskId); setSelectedEdgeId(null) }}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', background: sel ? '#F0F7FF' : '#F8FAFC', border: `1px solid ${sel ? '#B9DAFB' : C.line}`, borderRadius: 7, cursor: 'pointer', outline: 'none', textAlign: 'left' as const, minWidth: 240 }}>
                    <span style={{ fontFamily: MONO, fontWeight: 900, fontSize: 10, color: sel ? C.primary : C.text }}>{t.taskId}</span>
                    <span style={{ fontSize: 8, color: '#B0B8C4' }}>{t.orderId}</span>
                    <span style={{ marginLeft: 'auto', padding: '1px 5px', background: stBg, borderRadius: 4, fontSize: 8, fontWeight: 800, color: stColor }}>{t.taskStatus}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {task.taskStatus === '기록 없음' ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', padding: '12px 18px', background: '#F8FAFC', border: `1px dashed ${C.line}`, borderRadius: 9, fontSize: 10, color: '#C0C8D0', gap: 10 }}>
              <span style={{ fontSize: 18, opacity: 0.4 }}>📋</span>
              <div>
                <div style={{ fontWeight: 700, fontSize: 11, marginBottom: 2 }}>분석할 기록이 없습니다</div>
                <div style={{ fontSize: 9 }}>이 주문은 아직 배차 대기 중이며 이동 기록이 없습니다. 작업이 시작되면 이 화면에 경로 분석이 표시됩니다.</div>
              </div>
            </div>
          ) : (<>
            {/* Move summary cards */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' as const }}>
              {[
                { label: '계획 경로 거리',   sub: '이동 경로 총 거리',           val: `${task.planRouteDistM} m`,    valColor: C.text },
                { label: '최초 예상 이동시간', sub: '이동 구간만 합산',           val: fmtSec(task.planMoveTotalSec),  valColor: C.text },
                { label: '실제 이동시간',     sub: '완료된 이동 구간만 합산',     val: fmtSec(completedMoveActual),    valColor: completedMoveActual !== null && completedMoveActual > task.planMoveTotalSec ? C.warning : C.success },
                { label: '예상 대비 차이',    sub: '이동 구간 완료분만 기준',
                  val: completedMoveActual === null ? '—' : completedMoveActual === task.planMoveTotalSec ? '±0s' : completedMoveActual > task.planMoveTotalSec ? `+${completedMoveActual - task.planMoveTotalSec}s` : `-${task.planMoveTotalSec - completedMoveActual}s`,
                  valColor: completedMoveActual === null ? C.muted : completedMoveActual > task.planMoveTotalSec ? C.warning : C.success },
              ].map(card => (
                <div key={card.label} style={{ background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 8, padding: '7px 12px', minWidth: 128 }}>
                  <div style={{ fontSize: 8, color: C.muted, fontWeight: 700, marginBottom: 3 }}>{card.label}</div>
                  <div style={{ fontSize: 13, fontWeight: 900, fontFamily: MONO, color: card.valColor, lineHeight: 1 }}>{card.val}</div>
                  <div style={{ fontSize: 8, color: '#C0C8D0', marginTop: 3 }}>{card.sub}</div>
                </div>
              ))}
            </div>

            {/* Completion time block — separated, different scope */}
            <div style={{ background: '#F8FAFC', border: `1px solid ${C.line}`, borderRadius: 8, padding: '7px 12px', minWidth: 200 }}>
              <div style={{ fontSize: 8, color: C.muted, fontWeight: 700, marginBottom: 5 }}>전체 작업 완료 시각 <span style={{ fontWeight: 400, color: '#C0C8D0' }}>(이동+피킹+대기 포함)</span></div>
              {[
                { label: '최초 예상 완료', val: task.estCompOrig },
                { label: '현재 예상 완료', val: task.estCompCurr },
                { label: task.taskStatus === '완료' ? '실제 완료' : '진행 중', val: task.actualComp ?? '진행 중 ···' },
              ].map(row => (
                <div key={row.label} style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 8, color: C.muted, minWidth: 68 }}>{row.label}</span>
                  <span style={{ fontSize: 10, fontWeight: 800, fontFamily: MONO, color: row.val === '진행 중 ···' ? '#27966e' : C.text }}>{row.val}</span>
                </div>
              ))}
              <div style={{ marginTop: 5, fontSize: 7.5, color: '#C0C8D0', lineHeight: 1.4, borderTop: `1px solid #F0F3F7`, paddingTop: 4 }}>
                이동 시간 예상치와 전체 작업 시간은 포함 범위가 달라 직접 비교할 수 없습니다
              </div>
            </div>
          </>)}

        </div>
        <div style={{ marginTop: 6, fontSize: 7.5, color: '#C8D0DA' }}>※ 예시 데이터 · 현재 세션 기록 기반 · 장기 집계 데이터는 1차에서 제공하지 않습니다</div>
      </div>

      {/* ── BODY: map + analysis ── */}
      {task.taskStatus === '기록 없음' ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' as const, gap: 10 }}>
          <div style={{ fontSize: 32, opacity: 0.18 }}>📍</div>
          <div style={{ fontSize: 13, color: '#C0C8D0', fontWeight: 700 }}>경로 데이터 없음</div>
          <div style={{ fontSize: 9, color: '#D0D5DC', textAlign: 'center' as const, lineHeight: 1.6 }}>배차 완료 후 로봇이 이동을 시작하면<br/>경로 시각화 및 엣지 분석을 제공합니다</div>
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

          {/* ── Map panel ── */}
          <div style={{ width: 520, flexShrink: 0, borderRight: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ padding: '6px 12px 5px', borderBottom: `1px solid ${C.line}`, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 10, fontWeight: 800 }}>경로 시각화</span>
              <span style={{ fontSize: 8, color: '#B0B8C4' }}>{task.taskId} · {task.robotId}</span>
            </div>

            {/* Map — single SVG, viewBox matches map.png (135×135 px) */}
            <div style={{ flex: 1, position: 'relative', overflow: 'hidden', background: C.mapBase }}>
              <svg
                viewBox="0 0 135 135"
                preserveAspectRatio="xMidYMid meet"
                style={{ width: '100%', height: '100%' }}
              >
                {/* Grid */}
                <defs>
                  <pattern id="ag" width="10" height="10" patternUnits="userSpaceOnUse">
                    <path d="M 10 0 L 0 0 0 10" fill="none" stroke="#5A6B7A" strokeWidth="0.07" />
                  </pattern>
                </defs>
                <rect width="135" height="135" fill="url(#ag)" />

                {/* Map image */}
                <WarehouseGeometry />

                {/* Edge lines — coordinates are viewBox px (match AT_NODES x/y) */}
                {task.edges.map(e => {
                  const fn = nodeMap[e.fromNode]; const tn = nodeMap[e.toNode]
                  if (!fn || !tn) return null
                  const col = edgeLineColor(e)
                  const dash = edgeLineDash(e)
                  const sel = selectedEdgeId === e.id
                  const mx = (fn.x + tn.x) / 2; const my = (fn.y + tn.y) / 2
                  const angle = Math.atan2(tn.y - fn.y, tn.x - fn.x) * 180 / Math.PI
                  return (
                    <g key={e.id} onClick={() => handleMapEdgeClick(e.id)} style={{ cursor: 'pointer' }}>
                      <line x1={fn.x} y1={fn.y} x2={tn.x} y2={tn.y} stroke="transparent" strokeWidth="4" />
                      {sel && <line x1={fn.x} y1={fn.y} x2={tn.x} y2={tn.y}
                        stroke={col} strokeWidth="3" strokeOpacity="0.22" strokeLinecap="round" />}
                      <line x1={fn.x} y1={fn.y} x2={tn.x} y2={tn.y}
                        stroke={col} strokeWidth={sel ? 1.8 : 1.2} strokeLinecap="round"
                        strokeDasharray={dash} strokeOpacity={sel ? 1 : 0.85} />
                      {e.status === '완료' && (
                        <text x={mx} y={my} fontSize="4.5" fill={col} textAnchor="middle" dominantBaseline="middle"
                          transform={`rotate(${angle},${mx},${my})`} style={{ pointerEvents: 'none' as const }}>›</text>
                      )}
                      <text x={mx + 0.8} y={my - 1.2} fontSize="4" fill={col} fontWeight="700"
                        textAnchor="middle" dominantBaseline="middle" style={{ pointerEvents: 'none' as const }}>{e.seq}</text>
                    </g>
                  )
                })}

                {/* Nodes */}
                {AT_NODES.map(n => {
                  const isOnRoute = task.edges.some(e => e.fromNode === n.id || e.toNode === n.id)
                  if (!isOnRoute) return null
                  const col = AT_NODE_COLOR[n.type]
                  return (
                    <g key={n.id}>
                      <circle cx={n.x} cy={n.y} r="4" fill={col} fillOpacity="0.18" stroke={col} strokeWidth="0.8" />
                      <circle cx={n.x} cy={n.y} r="2" fill={col} />
                      <text x={n.x} y={n.y + 5} fontSize="4" fill={col} textAnchor="middle"
                        dominantBaseline="hanging" fontWeight="700" style={{ pointerEvents: 'none' as const }}>
                        {n.label}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>

            {/* Legend */}
            <div style={{ padding: '6px 12px', background: C.surface, borderTop: `1px solid ${C.line}`, flexShrink: 0, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' as const }}>
              {[
                { label: '정상', color: C.success, dash: false },
                { label: '지연', color: C.warning, dash: false },
                { label: '진행 중', color: C.primary, dash: true },
                { label: '기록 부족/대기', color: '#C8D0DA', dash: true },
              ].map(item => (
                <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <svg width="22" height="6" viewBox="0 0 22 6">
                    <line x1="0" y1="3" x2="22" y2="3" stroke={item.color} strokeWidth="2.5" strokeLinecap="round" strokeDasharray={item.dash ? '5,3' : '0'} />
                  </svg>
                  <span style={{ fontSize: 8, color: C.muted }}>{item.label}</span>
                </div>
              ))}
              <span style={{ marginLeft: 'auto', fontSize: 7.5, color: '#C0C8D0' }}>엣지 클릭 시 하단 표 연동</span>
            </div>
          </div>

          {/* ── Right analysis panel ── */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

            {/* Edge analysis table */}
            <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
              <div style={{ padding: '7px 14px 5px', borderBottom: `1px solid ${C.line}`, display: 'flex', alignItems: 'center', gap: 8, position: 'sticky', top: 0, background: C.surface, zIndex: 2 }}>
                <span style={{ fontWeight: 800, fontSize: 11 }}>엣지별 이동 분석</span>
                <span style={{ fontSize: 8, color: '#B0B8C4' }}>{task.edges.length}개 구간</span>
                {task.edges.some(e => e.routeChanged) && (
                  <span style={{ padding: '1px 6px', background: '#FFF5DF', border: '1px solid #ECD5AA', borderRadius: 4, fontSize: 8, fontWeight: 700, color: '#9A6A10' }}>경로 변경 있음</span>
                )}
              </div>

              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                <thead>
                  <tr style={{ background: '#F8FAFC' }}>
                    {['#', '구간 (출발 → 도착)', '경로 버전', '거리', '계획 이동', '실제 이동', '차이', '진입 전 대기', '상태', '지연 원인'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '6px 10px', fontSize: 8, color: '#697687', fontWeight: 700, borderBottom: `1px solid ${C.line}`, whiteSpace: 'nowrap' as const }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {task.edges.map((e) => {
                    const fn = nodeMap[e.fromNode]; const tn = nodeMap[e.toNode]
                    const sel = selectedEdgeId === e.id
                    const delta = (e.actualMoveSec !== null) ? e.actualMoveSec - e.planMoveSec : null
                    const stColor = e.status === '완료' ? '#1675d4' : e.status === '진행 중' ? '#27966e' : C.muted
                    const stBg   = e.status === '완료' ? '#EDF6FF' : e.status === '진행 중' ? '#E9F8F3' : '#F3F6FA'
                    return (
                      <tr key={e.id}
                        ref={el => { edgeRowRefs.current[e.id] = el }}
                        onClick={() => handleEdgeSelect(e.id)}
                        style={{ borderTop: `1px solid #F0F3F7`, background: sel ? '#F0F7FF' : 'transparent', cursor: 'pointer', borderLeft: `3px solid ${sel ? C.primary : edgeLineColor(e)}`, transition: 'background 0.1s' }}
                        onMouseEnter={el => { if (!sel) el.currentTarget.style.background = '#F8FBFF' }}
                        onMouseLeave={el => { if (!sel) el.currentTarget.style.background = 'transparent' }}>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontWeight: 900, color: C.muted, fontSize: 9 }}>{e.seq}</td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' as const }}>
                          <span style={{ fontSize: 9, color: AT_NODE_COLOR[fn?.type ?? 'junction'], fontWeight: 700 }}>{fn?.label ?? e.fromNode}</span>
                          <span style={{ color: '#B0B8C4', margin: '0 4px' }}>→</span>
                          <span style={{ fontSize: 9, color: AT_NODE_COLOR[tn?.type ?? 'junction'], fontWeight: 700 }}>{tn?.label ?? e.toNode}</span>
                        </td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' as const }}>
                          <span style={{ padding: '1px 5px', background: e.routeChanged ? '#FFF5DF' : '#F3F6FA', border: `1px solid ${e.routeChanged ? '#ECD5AA' : C.line}`, borderRadius: 4, fontSize: 8, fontWeight: 700, color: e.routeChanged ? '#9A6A10' : C.muted }}>{e.routeVersion}</span>
                        </td>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontSize: 9, whiteSpace: 'nowrap' as const }}>{e.distM} m</td>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontSize: 9 }}>{fmtSec(e.planMoveSec)}</td>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontSize: 9, color: e.actualMoveSec === null ? '#C0C8D0' : C.text }}>
                          {e.actualMoveSec !== null ? fmtSec(e.actualMoveSec) : e.status === '진행 중' ? '기록 중…' : '—'}
                        </td>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontSize: 9, fontWeight: 700, color: delta === null ? '#C0C8D0' : delta > 0 ? C.warning : delta < 0 ? C.success : C.muted }}>
                          {delta === null ? '—' : delta === 0 ? '±0s' : delta > 0 ? `+${delta}s` : `${delta}s`}
                        </td>
                        <td style={{ padding: '8px 10px', fontFamily: MONO, fontSize: 9, color: e.waitBeforeSec === null ? '#C0C8D0' : C.text }}>
                          {e.waitBeforeSec === null ? '—' : e.waitBeforeSec === 0 ? '0s' : `${e.waitBeforeSec}s`}
                        </td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' as const }}>
                          <span style={{ padding: '1px 5px', background: stBg, borderRadius: 4, fontSize: 8, fontWeight: 700, color: stColor }}>{e.status}</span>
                        </td>
                        <td style={{ padding: '8px 10px', fontSize: 9, color: e.delayReason ? (e.delayReason === '원인 미확인' ? C.danger : '#9A6A10') : '#C0C8D0', maxWidth: 220, wordBreak: 'break-word' as const }}>
                          {e.delayReason ?? (e.status !== '대기' ? '—' : '')}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>

              {/* Move / full-task note */}
              {task.note && (
                <div style={{ margin: '10px 14px', padding: '7px 10px', background: '#FFFBF0', border: '1px solid #ECD5AA', borderRadius: 7, fontSize: 8.5, color: '#9A6A10', lineHeight: 1.5 }}>
                  {task.note}
                </div>
              )}
            </div>

            {/* ── Delay summary ── */}
            <div style={{ flexShrink: 0, borderTop: `1px solid ${C.line}`, background: C.surface }}>
              <div style={{ padding: '7px 14px 5px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 800, fontSize: 11 }}>지연 구간 목록</span>
                <span style={{ fontSize: 8, color: '#B0B8C4' }}>이동 시간 초과 구간만 표시 · 엣지 내부 이동과 진입 전 대기는 별도 집계</span>
              </div>

              {delayedEdges.length === 0 ? (
                <div style={{ padding: '10px 14px 12px', fontSize: 9, color: '#C0C8D0', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 14, opacity: 0.5 }}>✓</span>
                  {task.taskStatus === '진행 중'
                    ? '완료된 구간에서 지연이 발생하지 않았습니다 (진행 중인 구간은 완료 후 집계됩니다)'
                    : '지연된 이동 구간이 없습니다'}
                </div>
              ) : (
                <div style={{ padding: '0 14px 10px', display: 'flex', flexWrap: 'wrap' as const, gap: 6 }}>
                  {delayedEdges.map(e => {
                    const fn = nodeMap[e.fromNode]; const tn = nodeMap[e.toNode]
                    const delta = (e.actualMoveSec ?? 0) - e.planMoveSec
                    return (
                      <div key={e.id} onClick={() => handleEdgeSelect(e.id)}
                        style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 10px', background: '#FFF5DF', border: `1px solid ${selectedEdgeId === e.id ? '#c98720' : '#ECD5AA'}`, borderRadius: 7, cursor: 'pointer', outline: 'none', maxWidth: 380 }}>
                        <span style={{ fontFamily: MONO, fontSize: 9, fontWeight: 900, color: '#9A6A10' }}>#{e.seq}</span>
                        <span style={{ fontSize: 9, color: '#9A6A10', fontWeight: 600 }}>{fn?.label ?? e.fromNode} → {tn?.label ?? e.toNode}</span>
                        <span style={{ fontFamily: MONO, fontSize: 10, fontWeight: 900, color: C.warning }}>+{delta}s</span>
                        <span style={{ fontSize: 8, color: '#B89050', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{e.delayReason ?? '원인 미확인'}</span>
                      </div>
                    )
                  })}
                  <div style={{ width: '100%', fontSize: 7.5, color: '#C0C8D0', paddingTop: 4, lineHeight: 1.4 }}>
                    집계 기준: 현재 세션 1건 기록 · 반복 기록이 충분하지 않아 상습 병목 또는 최적 경로를 단정할 수 없습니다
                  </div>
                </div>
              )}
            </div>

          </div>{/* end right panel */}
        </div>
      )}
    </div>
  )
}

function AlarmRow({ dot, label, time, target, state, muted = false }: { dot: string; label: string; time: string; target: string; state: string; muted?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7, padding: '4px 0', borderBottom: '1px solid #F0F3F7' }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, display: 'inline-block', marginTop: 3, flexShrink: 0 }} />
      <div>
        <div style={{ fontSize: 10, color: muted ? '#97A0AB' : C.text, fontWeight: 600 }}>{label}</div>
        <div style={{ fontSize: 9, color: '#B0B8C4', marginTop: 1 }}>{time} · {target} · {state}</div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════
// Responsive Preview Screen
// ══════════════════════════════════════

// Shared topology SVG — scales via viewBox, works inside any container
function MiniTopoMap({ uid = 'a' }: { uid?: string }) {
  const TN: Record<string, { x: number; y: number }> = {
    J0:{x:94,y:210},J1:{x:168,y:210},J2:{x:234,y:210},J3:{x:300,y:210},
    J4:{x:337,y:210},J5:{x:401,y:210},J6:{x:468,y:210},J7:{x:503,y:210},
    J8:{x:569,y:210},J9:{x:635,y:210},J10:{x:726,y:210},
    TA1:{x:234,y:143},TA2:{x:401,y:143},TA3:{x:569,y:143},
    BA1:{x:234,y:266},BA2:{x:401,y:266},BA3:{x:569,y:266},
    RV1:{x:726,y:87},RV2:{x:726,y:325},
  }
  type ES='base'|'active'|'overlap'
  const TE:{f:string;t:string;s:ES}[]=[
    {f:'J0',t:'J1',s:'base'},{f:'J1',t:'J2',s:'base'},{f:'J2',t:'J3',s:'overlap'},
    {f:'J3',t:'J4',s:'base'},{f:'J4',t:'J5',s:'base'},{f:'J5',t:'J6',s:'active'},
    {f:'J6',t:'J7',s:'active'},{f:'J7',t:'J8',s:'active'},{f:'J8',t:'J9',s:'active'},
    {f:'J9',t:'J10',s:'active'},{f:'J2',t:'TA1',s:'base'},{f:'J5',t:'TA2',s:'base'},
    {f:'J8',t:'TA3',s:'active'},{f:'J2',t:'BA1',s:'base'},{f:'J5',t:'BA2',s:'base'},
    {f:'J8',t:'BA3',s:'base'},{f:'J10',t:'RV1',s:'active'},{f:'J10',t:'RV2',s:'base'},
  ]
  const ec=(s:ES)=>s==='active'?'#2589F5':s==='overlap'?'#8B6BE8':'#B9C3CF'
  const ew=(s:ES)=>s==='base'?2:4
  const RACKS=[
    {id:'RACK A',x:168,y:45,w:132,h:98},{id:'RACK B',x:335,y:45,w:132,h:98},{id:'RACK C',x:503,y:45,w:132,h:98},
    {id:'RACK D',x:168,y:265,w:132,h:98},{id:'RACK E',x:335,y:265,w:132,h:98},{id:'RACK F',x:503,y:265,w:132,h:98},
  ]
  const CHS=[{id:'CH-01',x:726,y:62,w:88,h:50},{id:'CH-02',x:726,y:300,w:88,h:50}]
  const BOTS=[
    {x:601,y:210,col:'#2589F5',bg:'#EAF3FF',id:'R-01'},
    {x:196,y:210,col:'#E8A020',bg:'#FFF4E0',id:'R-02'},
    {x:726,y:145,col:'#36BD8A',bg:'#EAF8F2',id:'R-03'},
  ]
  return (
    <svg viewBox="0 0 840 420" preserveAspectRatio="xMidYMid meet" style={{width:'100%',height:'100%'}}>
      <defs>
        <pattern id={`mg${uid}`} width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#DFE4EB" strokeWidth="0.6"/>
        </pattern>
      </defs>
      <rect width="840" height="420" fill="#E7EBF0"/>
      <rect width="840" height="420" fill={`url(#mg${uid})`}/>
      {RACKS.map(r=>(
        <g key={r.id}>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} rx="4" fill="#F9FAFB" stroke="#DFE4EB" strokeWidth="1.5"/>
          <line x1={r.x+r.w*0.33} y1={r.y+8} x2={r.x+r.w*0.33} y2={r.y+r.h-8} stroke="#E8ECF1" strokeWidth="1"/>
          <line x1={r.x+r.w*0.66} y1={r.y+8} x2={r.x+r.w*0.66} y2={r.y+r.h-8} stroke="#E8ECF1" strokeWidth="1"/>
          <line x1={r.x+6} y1={r.y+r.h*0.45} x2={r.x+r.w-6} y2={r.y+r.h*0.45} stroke="#E8ECF1" strokeWidth="1"/>
          <text x={r.x+r.w/2} y={r.y+r.h-11} fontSize="9" fontWeight="700" fill="#8A96A3" textAnchor="middle" dominantBaseline="middle" fontFamily={FONT}>{r.id}</text>
        </g>
      ))}
      {CHS.map(ch=>(
        <g key={ch.id}>
          <rect x={ch.x} y={ch.y} width={ch.w} height={ch.h} rx="5" fill="#EAF8F2" stroke="#36BD8A" strokeWidth="1.8"/>
          <polyline points={`${ch.x+22},${ch.y+13} ${ch.x+17},${ch.y+26} ${ch.x+21},${ch.y+26} ${ch.x+15},${ch.y+40}`} fill="none" stroke="#36BD8A" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"/>
          <text x={ch.x+34} y={ch.y+22} fontSize="7.5" fontWeight="700" fill="#1A7A55" fontFamily={FONT}>충전</text>
          <text x={ch.x+34} y={ch.y+34} fontSize="9" fontWeight="800" fill="#1A7A55" fontFamily={FONT}>{ch.id}</text>
        </g>
      ))}
      <rect x="12" y="185" width="82" height="52" rx="5" fill="#EBF3FF" stroke="#2589F5" strokeWidth="1.8"/>
      <rect x="22" y="197" width="62" height="10" rx="3" fill="none" stroke="#2589F5" strokeWidth="1.2"/>
      {[30,42,54,66,78].map(lx=><line key={lx} x1={lx} y1="197" x2={lx} y2="207" stroke="#2589F5" strokeWidth="1"/>)}
      <text x="53" y="222" fontSize="7.5" fontWeight="700" fill="#1258B8" fontFamily={FONT} textAnchor="middle">컨베이어</text>
      <text x="53" y="232" fontSize="8.5" fontWeight="800" fill="#1258B8" fontFamily={FONT} textAnchor="middle">ST-02</text>
      <circle cx="88" cy="185" r="9" fill="#E84040"/>
      <text x="88" y="186" fontSize="7.5" fontWeight="800" fill="#fff" fontFamily={FONT} textAnchor="middle" dominantBaseline="middle">07</text>
      <line x1="94" y1="210" x2="14" y2="210" stroke="#B9C3CF" strokeWidth="2"/>
      {TE.map((e,i)=>{const fn=TN[e.f];const tn=TN[e.t];if(!fn||!tn)return null;return <line key={i} x1={fn.x} y1={fn.y} x2={tn.x} y2={tn.y} stroke={ec(e.s)} strokeWidth={ew(e.s)} strokeLinecap="round"/>})}
      {Object.entries(TN).map(([id,n])=>(
        <g key={id}><circle cx={n.x} cy={n.y} r="5.5" fill="#fff" stroke="#20242B" strokeWidth="1.5"/><circle cx={n.x} cy={n.y} r="2" fill="#20242B"/></g>
      ))}
      {BOTS.map(r=>(
        <g key={r.id}>
          <path d={`M ${r.x} ${r.y+22} Q ${r.x-5} ${r.y+16} ${r.x-14} ${r.y+6} A 14 14 0 1 1 ${r.x+14} ${r.y+6} Q ${r.x+5} ${r.y+16} ${r.x} ${r.y+22} Z`} fill={r.bg} stroke={r.col} strokeWidth="1.8"/>
          <text x={r.x} y={r.y+4} fontSize="7.5" fontWeight="800" fill={r.col} textAnchor="middle" dominantBaseline="middle" fontFamily={MONO}>{r.id}</text>
        </g>
      ))}
    </svg>
  )
}
