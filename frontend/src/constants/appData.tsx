import React from 'react'

export const NAV_ITEMS = [
  { id: 'dashboard',   label: '통합 관제',     icon: '⊞' },
  { id: 'robots',      label: '로봇·로봇팔',   icon: '🤖' },
  { id: 'orders',      label: '주문·작업',     icon: '📋' },
  { id: 'alarms',      label: '알람',          icon: '🔔' },
  { id: 'logs',        label: '로그·작업 이력', icon: '📄' },
  { id: 'analytics',   label: '이동시간 분석', icon: '📊' },
]

export type LayerKey         = 'nodeEdge' | 'route' | 'station' | 'robotId'
export type RobotId          = 'R-01' | 'R-02' | 'R-03'
export type TabId            = 'status' | 'task' | 'control'
export type CmdState         = 'requesting' | 'approved' | 'rejected' | 'confirmed' | null
export type RemoteConn       = 'off' | 'connecting' | 'ready'
export type OrderStatus      = '진행 중' | '배차 대기' | '완료' | '실행 불가'
export type OrderFilterStatus = 'all' | OrderStatus
export type ExecState        = null | 'requesting' | 'waiting' | 'dispatched' | 'rejected'
export type AlarmSeverity    = '긴급' | '경고' | '주의' | '정보'
export type AlarmState       = '발생 중' | '확인 필요' | '해결됨'
export type AlarmFilterType  = 'all' | AlarmState
export type AckState         = null | 'requesting' | 'acknowledged'
export type HistoryEventType = '배차' | '이동' | '도킹' | '피킹' | '상태 변경' | '주문'
export type LogEvType = '배차' | '경로' | '피킹' | '인계' | '제어' | '알람'
export interface SLogEntry {
  id: string; ts: string; seq: number
  type: LogEvType; target: string; targetType: 'robot'|'arm'|'task'|'system'
  message: string; isNew?: boolean
  detail: {
    taskId?: string; orderId?: string; robotId?: string
    armId?: string; stationId?: string; route?: string
    duration?: string; ref?: string; operator?: string
  }
}

export const LAYERS: { key: LayerKey; label: string }[] = [
  { key: 'nodeEdge', label: '노드·엣지' },
  { key: 'route',    label: '경로' },
  { key: 'station',  label: '구조물 이름' },
  { key: 'robotId',  label: '로봇 ID' },
]

export const ROBOT_DATA: Record<RobotId, {
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

export const TABS: { id: TabId; label: string }[] = [
  { id: 'status',  label: '상태' },
  { id: 'task',    label: '작업' },
  { id: 'control', label: '제어' },
]

// Control commands — ready:false = 준비 중 (not yet implemented in backend)
export const CTRL_CMDS = [
  { id: 'assign',   label: '작업 배정',        variant: 'primary',  ready: false, confirm: false },
  { id: 'nodeMove', label: '특정 노드 이동',   variant: 'default',  ready: true,  confirm: false },
  { id: 'charge',   label: '충전 스테이션 이동', variant: 'default', ready: false, confirm: false },
  { id: 'stop',     label: '선택 로봇 정지',   variant: 'danger',   ready: true,  confirm: true  },
  { id: 'manual',   label: '수동 모드 전환',   variant: 'warning',  ready: false, confirm: true  },
]

export const KEY_ROWS = [
  [{ k: 'Q', l: '좌회전' }, { k: 'W', l: '전진' },  { k: 'E', l: '우회전' }],
  [{ k: 'A', l: '좌회전' }, { k: 'S', l: '후진' },  { k: 'D', l: '우회전' }],
]

// ── Stage 4 data ──
export type ArmId = 'ARM-1' | 'ARM-2'
export type PackingStatus = '가용' | '예약' | '사용 중'

export const ARM_DATA: Record<ArmId, {
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

export const PACKING_STATIONS: {
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

export const CHARGING_STATIONS = [
  { id: 'CH-1', note: '배치 미확정' },
  { id: 'CH-2', note: '배치 미확정' },
  { id: 'CH-3', note: '배치 미확정' },
]

// ── Stage 5: Orders ──
export const TASK_STEPS = ['배차', '팔레트 방문·피킹', '패킹 ST 이동', '물품 인계', '완료']

export interface PaletteVisitEntry {
  paletteId: string; armId: ArmId; itemSummary: string
  visitOrder: number; stepStatus: 'done' | 'active' | 'pending'
}
export interface OrderEntry {
  id: string; itemSummary: string; qtyTotal: string
  status: OrderStatus; statusColor: string; statusBg: string
  feasible: boolean; blockReason: string | null
  assignedRobot: RobotId | null; currentStepLabel: string
  paletteVisits: PaletteVisitEntry[]
  estimatedPacking: string
  estCompOrig: string; estCompCurr: string; actualComp?: string
  progressStep: number; palettesTotal: number; palettesVisited: number
}

export const ORDER_DATA: OrderEntry[] = [
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
export interface ATNode {
  id: string; label: string
  x: number; y: number  // 0–100 percent
  type: 'start' | 'palette' | 'arm' | 'packing' | 'charging' | 'junction'
}
export interface ATEdge {
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
export interface ATTask {
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
export const AT_NODES: ATNode[] = [
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

export const AT_NODE_COLOR: Record<ATNode['type'], string> = {
  start: '#1A6FD8', junction: '#7A8999', arm: '#7255CB',
  palette: '#1FA466', packing: '#CC8215', charging: '#1FA466',
}

export const AT_TASKS: ATTask[] = [
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
export interface AlarmEntry {
  id: string; severity: AlarmSeverity
  target: string; targetId: string | null; targetType: 'robot' | 'arm' | 'system'
  location: string; content: string; state: AlarmState
  occurredAt: string; updatedAt: string
  relatedTaskId: string | null; relatedOrderId: string | null
  deviceStateAtTime: string; description: string
}
export interface HistoryEntry {
  id: string; time: string
  target: string; targetId: string | null; targetType: 'robot' | 'arm' | 'system'
  eventType: HistoryEventType; description: string
  relatedRobotId: string | null; relatedOrderId: string | null
}

export const SEVERITY_CFG: Record<AlarmSeverity, { color: string; bg: string; bd: string }> = {
  '긴급': { color: '#B02038', bg: '#FEF0F3', bd: '#EDAAB6' },
  '경고': { color: '#8C5A0A', bg: '#FEF4E1', bd: '#E4C070' },
  '주의': { color: '#1155A8', bg: '#E8F1FF', bd: '#9DC4F0' },
  '정보': { color: '#50606F', bg: '#F2F5F9', bd: '#CDD5DF' },
}
export const STATE_CFG: Record<AlarmState, { color: string; bg: string; bd: string }> = {
  '발생 중':  { color: '#B02038', bg: '#FEF0F3', bd: '#EDAAB6' },
  '확인 필요': { color: '#8C5A0A', bg: '#FEF4E1', bd: '#E4C070' },
  '해결됨':   { color: '#50606F', bg: '#F2F5F9', bd: '#CDD5DF' },
}
export const EVT_CFG: Partial<Record<HistoryEventType, { color: string; bg: string }>> = {
  '배차':    { color: '#1155A8', bg: '#E8F1FF' },
  '이동':    { color: '#147A4E', bg: '#E4F6EF' },
  '피킹':    { color: '#5E3FB3', bg: '#EDE8FF' },
  '도킹':    { color: '#8C5A0A', bg: '#FEF4E1' },
  '상태 변경': { color: '#B02038', bg: '#FEF0F3' },
  '주문':    { color: '#50606F', bg: '#F2F5F9' },
}
export const HIST_TYPES: string[]   = ['all', '배차', '이동', '피킹', '도킹', '상태 변경', '주문']
export const HIST_TARGETS: string[] = ['all', 'R-01', 'R-02', 'R-03', 'ARM-1', 'ARM-2', '시스템']

export const ALARM_DATA: AlarmEntry[] = [
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

export const HISTORY_DATA: HistoryEntry[] = [
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
export const LOG_EVT_CFG: Record<LogEvType, { label:string; color:string; bg:string; bd:string }> = {
  '배차': { label:'배차', color:'#1A6FD8', bg:'#EBF3FF', bd:'#91C0F8' },
  '경로': { label:'경로', color:'#0B5FAD', bg:'#E0EEFF', bd:'#7DB5F0' },
  '피킹': { label:'피킹', color:'#1A7A55', bg:'#E4F6EF', bd:'#88D5B3' },
  '인계': { label:'인계', color:'#167B52', bg:'#E8FBF2', bd:'#8AD5B5' },
  '제어': { label:'제어', color:'#5E3FB3', bg:'#F0ECFF', bd:'#C4B0F0' },
  '알람': { label:'알람', color:'#B02038', bg:'#FEF0F3', bd:'#EDAAB6' },
}

export const LOG_ICONS: Record<LogEvType, React.ReactNode> = {
  '배차': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M1.5 4.5H7M4.8 2.5L7 4.5 4.8 6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>),
  '경로': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><circle cx="2" cy="7" r="1.1" stroke="currentColor" strokeWidth="1"/><circle cx="7" cy="2" r="1.1" stroke="currentColor" strokeWidth="1"/><path d="M2.8 6.4 Q2.8 3.5 6 2.8" stroke="currentColor" strokeWidth="1" fill="none"/></svg>),
  '피킹': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M4.5 1V5.5M2.5 3.5L4.5 5.5 6.5 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/><line x1="1.5" y1="7.5" x2="7.5" y2="7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>),
  '인계': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M1.5 5H5M4 3.5L5.5 5 4 6.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 4H7.5M6 2.5L7.5 4 6 5.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round"/></svg>),
  '제어': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><circle cx="4.5" cy="4.5" r="1.4" stroke="currentColor" strokeWidth="1"/><path d="M4.5 1.3v1.1M4.5 6.6v1.1M1.3 4.5h1.1M6.6 4.5h1.1" stroke="currentColor" strokeWidth="1" strokeLinecap="round"/></svg>),
  '알람': (<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><path d="M4.5 1L8 7.5H1L4.5 1Z" stroke="currentColor" strokeWidth="1" fill="none" strokeLinejoin="round"/><line x1="4.5" y1="4" x2="4.5" y2="5.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/><circle cx="4.5" cy="6.5" r="0.4" fill="currentColor"/></svg>),
}

export const SESSION_LOG: SLogEntry[] = [
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

export const LIVE_LOG_QUEUE: SLogEntry[] = [
  { id:'L026', ts:'09:33:37', seq:26, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 · ARM-1 피킹 재시작 — 4번째 물품',               detail:{ armId:'ARM-1', taskId:'TK-260913-001', ref:'ALM-002' } },
  { id:'L027', ts:'09:33:52', seq:27, type:'피킹',  target:'ARM-1',         targetType:'arm',    message:'팔레트 1 · 4/6 피킹 완료',                               detail:{ armId:'ARM-1', taskId:'TK-260913-001', duration:'91 s' } },
  { id:'L028', ts:'09:34:08', seq:28, type:'경로',  target:'R-02',          targetType:'robot',  message:'TK-260913-002 · R-02 경로 확정 완료',                     detail:{ robotId:'R-02', taskId:'TK-260913-002', route:'HOME → J12 → J5 → J4 → PA2', duration:'26 s 예상' } },
  { id:'L029', ts:'09:34:21', seq:29, type:'배차',  target:'TK-260913-002', targetType:'task',   message:'TK-260913-002 배차 확정 · R-02 출발',                     detail:{ robotId:'R-02', taskId:'TK-260913-002', orderId:'ORD-260913-002' } },
]


// Screen-specific display configuration
export const CMD_RESULT_CFG: Record<NonNullable<CmdState>, { bg: string; border: string; color: string; icon: string; text: string }> = {
  requesting: { bg: '#EAF2FF', border: '#9DC4F0', color: '#1155A8', icon: '⟳', text: '요청 중 — 백엔드 검증 중' },
  approved:   { bg: '#E4F6EF', border: '#8DCFB2', color: '#147A4E', icon: '✓', text: '승인됨 — 로봇 상태를 확인하세요' },
  rejected:   { bg: '#FEF0F3', border: '#EDAAB6', color: '#B02038', icon: '✕', text: '거절됨 — 실행 조건 미충족 또는 통신 끊김' },
  confirmed:  { bg: '#E4F6EF', border: '#8DCFB2', color: '#0C5E3A', icon: '●', text: '실행 확인 — 로봇이 명령을 수신했습니다' },
}

export const FILTER_ITEMS: { label: string; value: OrderFilterStatus }[] = [
  { label: '전체',     value: 'all'      },
  { label: '진행 중',  value: '진행 중'  },
  { label: '배차 대기', value: '배차 대기' },
  { label: '완료',     value: '완료'     },
  { label: '실행 불가', value: '실행 불가' },
]
