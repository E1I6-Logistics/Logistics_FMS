import { useEffect, useMemo, useState } from 'react'
import WarehouseMap from './WarehouseMap'
import { sendGoalCoordinate, sendGoalNode, stopRobot } from './api/fmsApi'
import { useCmdVel } from './hooks/useCmdVel'
import { useRobotFleet } from './hooks/useRobotFleet'
import { useRouteGraph } from './hooks/useRouteGraph'
import { C, FONT, MONO } from './constants/theme'
import { KEY_ROWS, ROBOT_DATA, type RobotId } from './constants/appData'

type CommandState = { tone: 'success' | 'danger' | 'info'; message: string } | null

const allLayers = { nodeEdge: true, route: true, station: true, robotId: true }

export default function FmsControlApp() {
  const [time, setTime] = useState(new Date())
  const [selectedRobot, setSelectedRobot] = useState<RobotId | null>(null)
  const [targetNode, setTargetNode] = useState<string | null>(null)
  const [commandState, setCommandState] = useState<CommandState>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const {
    managedIds,
    mapRobotIds,
    managedRobots,
    mode: robotMode,
    modeSwitching,
    changeMode,
    error: fleetError,
  } = useRobotFleet()
  const { nodes, edges, nodeItems, loading: graphLoading, error: graphError } = useRouteGraph()

  const selectedLiveRobot = managedRobots.find(robot => robot.id === selectedRobot)
  const connectedRobotCount = managedRobots.filter(robot => robot.connected).length
  const connected = Boolean(selectedLiveRobot?.connected)

  const remote = useCmdVel({
    robotId: selectedRobot,
    enabled: Boolean(selectedRobot && connected),
  })

  useEffect(() => {
    const timer = window.setInterval(() => setTime(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    setTargetNode(null)
    setCommandState(null)
  }, [selectedRobot])

  useEffect(() => {
    if (selectedRobot && !(managedIds as RobotId[]).includes(selectedRobot)) {
      setSelectedRobot(null)
    }
  }, [managedIds, selectedRobot])

  const chargingNode = useMemo(() => {
    const explicit = nodeItems.find(item => /charge|charging|ch[-_ ]?\d|충전/i.test(`${item.id} ${item.label} ${item.mapNodeId}`))
    if (explicit) return explicit.mapNodeId
    return Object.keys(nodes).find(id => /charge|charging|ch[-_ ]?\d|충전/i.test(id)) ?? null
  }, [nodeItems, nodes])

  const nearestNode = useMemo(() => {
    if (!selectedLiveRobot?.hasPose) return null
    const candidates = Object.entries(nodes)
    if (candidates.length === 0) return null
    const [id, point] = candidates.reduce((nearest, candidate) => {
      const nearestDistance = Math.hypot(
        nearest[1].worldX - selectedLiveRobot.x,
        nearest[1].worldY - selectedLiveRobot.y,
      )
      const candidateDistance = Math.hypot(
        candidate[1].worldX - selectedLiveRobot.x,
        candidate[1].worldY - selectedLiveRobot.y,
      )
      return candidateDistance < nearestDistance ? candidate : nearest
    })
    return {
      id,
      x: point.worldX,
      y: point.worldY,
      distance: Math.hypot(point.worldX - selectedLiveRobot.x, point.worldY - selectedLiveRobot.y),
    }
  }, [nodes, selectedLiveRobot])

  const clock = time.toLocaleTimeString('ko-KR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })

  const runCommand = async (id: string, action: () => Promise<unknown>) => {
    try {
      setBusy(id)
      setCommandState({ tone: 'info', message: '명령을 전송하고 있습니다.' })
      await action()
      setCommandState({ tone: 'success', message: '명령이 정상적으로 전송되었습니다.' })
    } catch (error) {
      setCommandState({
        tone: 'danger',
        message: error instanceof Error ? error.message : '명령을 전송하지 못했습니다.',
      })
    } finally {
      setBusy(null)
    }
  }

  const moveToSelectedNode = () => {
    if (!selectedRobot || !targetNode) return
    void runCommand('nodeMove', () => sendGoalNode(selectedRobot, targetNode))
  }

  const returnToNearestNode = () => {
    if (!selectedRobot || !nearestNode) return
    void runCommand('returnToRoute', () => sendGoalCoordinate(selectedRobot, nearestNode.x, nearestNode.y))
  }

  const moveToCharge = () => {
    if (!selectedRobot) return
    if (!chargingNode) {
      setCommandState({ tone: 'danger', message: '경로 그래프에 충전 스테이션 노드가 등록되어 있지 않습니다.' })
      return
    }
    void runCommand('charge', () => sendGoalNode(selectedRobot, chargingNode))
  }

  const stopSelectedRobot = () => {
    if (!selectedRobot) return
    if (!window.confirm(`${selectedRobot} 로봇을 정지하시겠습니까?`)) return
    remote.stop()
    void runCommand('stop', () => stopRobot(selectedRobot))
  }

  const emergencyStopAll = () => {
    const robotIds = managedIds as RobotId[]
    if (robotIds.length === 0) {
      setCommandState({ tone: 'danger', message: '정지할 로봇이 없습니다.' })
      return
    }
    if (!window.confirm(`연결된 로봇 ${robotIds.length}대를 모두 비상정지하시겠습니까?`)) return
    remote.stop()
    void runCommand('emergency', () => Promise.all(robotIds.map(id => stopRobot(id))))
  }

  const handleModeChange = (mode: 'real' | 'simulation') => {
    if (mode === robotMode || modeSwitching) return
    setSelectedRobot(null)
    setTargetNode(null)
    setCommandState({ tone: 'info', message: `${mode === 'real' ? '실제 로봇' : '시뮬레이션'} 모드로 전환하고 있습니다.` })
    void changeMode(mode)
      .then(() => setCommandState({ tone: 'success', message: `${mode === 'real' ? '실제 로봇' : '시뮬레이션'} 모드로 전환되었습니다.` }))
      .catch(error => setCommandState({
        tone: 'danger',
        message: error instanceof Error ? error.message : '운용 모드를 전환하지 못했습니다.',
      }))
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: C.bg, color: C.text, fontFamily: FONT }}>
      <aside className="fms-left-nav" style={{ width: 188, background: C.nav, flexDirection: 'column', flexShrink: 0, boxShadow: '2px 0 8px rgba(0,0,0,.18)' }}>
        <div style={{ padding: '14px 16px 12px', borderBottom: '1px solid rgba(255,255,255,.06)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(140deg,#1A6FD8,#3FA3F5)', display: 'grid', placeItems: 'center', color: '#fff', fontWeight: 900, fontSize: 9.5 }}>FMS</div>
          <div>
            <div style={{ color: '#E8EDF4', fontWeight: 700, fontSize: 12 }}>E1I6 FMS</div>
            <div style={{ color: '#4C5563', fontSize: 9, marginTop: 2 }}>물류센터 관제</div>
          </div>
        </div>
        <nav style={{ flex: 1, paddingTop: 8 }} aria-label="주 메뉴">
          <button aria-current="page" style={{ width: '100%', padding: '9px 16px', border: 0, borderLeft: '3px solid #1A6FD8', background: 'rgba(26,111,216,.16)', color: '#6DB8FF', fontSize: 12, fontWeight: 700, textAlign: 'left' }}>
            <span style={{ display: 'inline-block', width: 5, height: 5, marginRight: 10, borderRadius: '50%', background: '#3FA3F5', boxShadow: '0 0 0 3px rgba(63,163,245,.2)' }} />
            통합 관제
          </button>
        </nav>
        <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(255,255,255,.05)', color: '#343B46', font: `8.5px ${MONO}` }}>v1.0.0-alpha</div>
      </aside>

      <main style={{ display: 'flex', flex: 1, minWidth: 0, flexDirection: 'column', overflow: 'hidden' }}>
        <header style={{ height: 46, flexShrink: 0, padding: '0 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: C.surface, borderBottom: `1px solid ${C.line}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <strong style={{ fontSize: 13.5, letterSpacing: '-.03em' }}>E1I6 물류센터 FMS</strong>
            <span style={{ width: 1, height: 14, background: C.line }} />
            <span style={{ color: C.muted, font: `11px ${MONO}` }}>{clock}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: fleetError ? C.danger : C.success, fontSize: 10.5, fontWeight: 700 }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: fleetError ? C.danger : C.success }} />
              {fleetError ? 'FMS 서버 오류' : `FMS 연결 · 로봇 ${connectedRobotCount}대 온라인`}
            </div>
            <div role="group" aria-label="로봇 운용 모드" style={{ display: 'flex', padding: 2, borderRadius: 7, background: '#EEF1F5', border: `1px solid ${C.line}` }}>
              {([
                ['real', '실제 로봇'],
                ['simulation', '시뮬레이션'],
              ] as const).map(([mode, label]) => {
                const active = robotMode === mode
                return (
                  <button
                    key={mode}
                    disabled={modeSwitching}
                    aria-pressed={active}
                    onClick={() => handleModeChange(mode)}
                    style={{
                      minWidth: 66,
                      padding: '4px 9px',
                      border: 0,
                      borderRadius: 5,
                      background: active ? (mode === 'simulation' ? '#7352B8' : '#16845A') : 'transparent',
                      color: active ? '#fff' : C.muted,
                      fontSize: 9,
                      fontWeight: 800,
                      cursor: modeSwitching ? 'wait' : 'pointer',
                      opacity: modeSwitching && !active ? .55 : 1,
                    }}
                  >
                    {modeSwitching && active ? '전환 중…' : label}
                  </button>
                )
              })}
            </div>
          </div>
        </header>

        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <RobotRail
            robotIds={managedIds as RobotId[]}
            selectedRobot={selectedRobot}
            getStatus={id => managedRobots.find(robot => robot.id === id)?.status ?? ROBOT_DATA[id].status}
            onSelect={setSelectedRobot}
          />

          <section style={{ position: 'relative', display: 'flex', flex: 1, minWidth: 0, background: '#E7EBF0' }} aria-label="FMS 실시간 지도">
            {commandState && (
              <CommandToast state={commandState} onClose={() => setCommandState(null)} />
            )}
            <WarehouseMap
              nodes={nodes}
              edges={edges}
              layers={allLayers}
              selectedRobot={selectedRobot}
              onSelect={setSelectedRobot}
              picking={Boolean(selectedRobot)}
              targetNode={targetNode ?? undefined}
              onPick={setTargetNode}
              graphLoading={graphLoading}
              graphError={graphError}
              visibleRobotIds={mapRobotIds as RobotId[]}
              robotStates={managedRobots}
            />
            <button
              onClick={emergencyStopAll}
              disabled={busy === 'emergency'}
              style={{ position: 'absolute', left: 18, bottom: 18, zIndex: 20, minWidth: 154, height: 48, padding: '0 18px', borderRadius: 9, border: '1px solid #9F1329', background: '#C8233A', color: '#fff', fontSize: 13, fontWeight: 900, boxShadow: '0 5px 16px rgba(176,32,56,.32)', cursor: 'pointer' }}
            >
              <span aria-hidden="true" style={{ marginRight: 8 }}>■</span>
              {busy === 'emergency' ? '정지 명령 전송 중' : '전체 비상정지'}
            </button>
          </section>

          <RobotPanel
            robotId={selectedRobot}
            liveRobot={selectedLiveRobot}
            targetNode={targetNode}
            nearestNode={nearestNode}
            chargingNode={chargingNode}
            remoteStatus={remote.status}
            remoteKeys={remote.activeKeys}
            busy={busy}
            onRemoteDown={remote.pressKey}
            onRemoteUp={remote.releaseKey}
            onRemoteStop={remote.stop}
            onMove={moveToSelectedNode}
            onReturnToRoute={returnToNearestNode}
            onCharge={moveToCharge}
            onStop={stopSelectedRobot}
          />
        </div>
      </main>
    </div>
  )
}

function RobotRail({ robotIds, selectedRobot, getStatus, onSelect }: {
  robotIds: RobotId[]
  selectedRobot: RobotId | null
  getStatus: (id: RobotId) => string
  onSelect: (id: RobotId) => void
}) {
  return (
    <aside style={{ width: 64, flexShrink: 0, padding: '10px 0', overflowY: 'auto', background: C.surface, borderRight: `1px solid ${C.line}`, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }} aria-label="로봇 목록">
      <span style={{ color: '#A5AFBB', fontSize: 8, lineHeight: 1.35, textAlign: 'center' }}>로봇<br />목록</span>
      {robotIds.map(id => {
        const selected = id === selectedRobot
        const status = getStatus(id)
        const color = /연결 끊김|OFFLINE/i.test(status) ? C.danger : /이동|작업|RUN|MOV/i.test(status) ? C.success : C.warning
        return (
          <button key={id} onClick={() => onSelect(id)} title={`${id} · ${status}`} aria-pressed={selected}
            style={{ width: 40, height: 40, borderRadius: '50%', border: `2.5px solid ${selected ? C.primary : color}`, background: selected ? '#EDF6FF' : '#F8FAFC', color: selected ? C.primary : C.text, fontSize: 10, fontWeight: 900, cursor: 'pointer', boxShadow: selected ? '0 0 0 3px rgba(37,137,245,.15)' : 'none' }}>
            {id.replace('R-', '')}
          </button>
        )
      })}
    </aside>
  )
}

type LiveRobot = ReturnType<typeof useRobotFleet>['managedRobots'][number]

function RobotPanel({ robotId, liveRobot, targetNode, nearestNode, chargingNode, remoteStatus, remoteKeys, busy, onRemoteDown, onRemoteUp, onRemoteStop, onMove, onReturnToRoute, onCharge, onStop }: {
  robotId: RobotId | null
  liveRobot?: LiveRobot
  targetNode: string | null
  nearestNode: { id: string; x: number; y: number; distance: number } | null
  chargingNode: string | null
  remoteStatus: 'off' | 'connecting' | 'ready'
  remoteKeys: Set<string>
  busy: string | null
  onRemoteDown: (key: string) => void
  onRemoteUp: (key: string) => void
  onRemoteStop: () => void
  onMove: () => void
  onReturnToRoute: () => void
  onCharge: () => void
  onStop: () => void
}) {
  if (!robotId) {
    return (
      <aside style={{ width: 390, flexShrink: 0, borderLeft: `1px solid ${C.line}`, background: C.surface, display: 'grid', placeItems: 'center', padding: 32, boxSizing: 'border-box', textAlign: 'center' }}>
        <div>
          <div style={{ width: 54, height: 54, margin: '0 auto 14px', display: 'grid', placeItems: 'center', borderRadius: 15, background: '#EDF6FF', color: C.primary, fontSize: 24 }}>◎</div>
          <strong style={{ display: 'block', fontSize: 14, marginBottom: 7 }}>로봇을 선택하세요</strong>
          <span style={{ color: C.muted, fontSize: 11, lineHeight: 1.6 }}>지도 또는 좌측 로봇 목록에서<br />제어할 로봇을 선택하세요.</span>
        </div>
      </aside>
    )
  }

  const fallback = ROBOT_DATA[robotId]
  const battery = liveRobot?.battery ?? fallback.battery
  const connected = Boolean(liveRobot?.connected)
  const status = !connected ? '연결 끊김' : liveRobot?.status || fallback.status
  const statusColor = !connected ? C.danger : /MOV|RUN|이동|작업/i.test(status) ? C.success : C.warning
  const batteryColor = battery < 30 ? C.danger : battery < 50 ? C.warning : C.success
  const route = liveRobot?.route?.node_ids?.length ? liveRobot.route.node_ids.map(id => `N${id}`).join(' → ') : '—'
  const controlsEnabled = connected && remoteStatus === 'ready'

  return (
    <aside style={{ width: 390, flexShrink: 0, borderLeft: `1px solid ${C.line}`, background: C.surface, display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '-2px 0 8px rgba(0,0,0,.05)' }} aria-label={`${robotId} 정보 및 제어`}>
      <div style={{ padding: '14px 16px', borderBottom: `1px solid ${C.line}`, display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: '#EDF6FF', border: `2px solid ${C.primary}`, color: C.primary, fontWeight: 900 }}>{robotId.replace('R-', '')}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <strong style={{ fontSize: 16 }}>{robotId}</strong>
            <span style={{ padding: '2px 7px', borderRadius: 5, background: `${statusColor}16`, color: statusColor, fontSize: 9, fontWeight: 800 }}>{status}</span>
          </div>
          <span style={{ color: C.muted, font: `9px ${MONO}` }}>{fallback.serial}</span>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '14px 16px 18px' }}>
        <SectionTitle>핵심 상태</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <StatusCard label="배터리" value={`${Math.round(battery)}%`} color={batteryColor}>
            <div style={{ height: 5, borderRadius: 5, overflow: 'hidden', background: '#E3E8EF', marginTop: 8 }}><div style={{ width: `${battery}%`, height: '100%', background: batteryColor }} /></div>
          </StatusCard>
          <StatusCard label="통신 상태" value={connected ? '● 정상' : '● 끊김'} color={connected ? C.success : C.danger} />
        </div>

        <div style={{ marginTop: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: `1px solid ${C.line}`, borderRadius: 9, background: '#F3FBF7' }}>
          <div>
            <div style={{ fontSize: 10, color: C.muted }}>원격제어</div>
            <strong style={{ display: 'block', marginTop: 3, color: connected ? C.success : C.danger, fontSize: 12 }}>
              {remoteStatus === 'connecting' ? '자동 연결 중' : controlsEnabled ? '● 항상 활성화' : '● 통신 연결 대기'}
            </strong>
          </div>
          <span style={{ padding: '3px 8px', borderRadius: 20, background: connected ? '#DDF4EA' : '#F1F3F6', color: connected ? '#167A55' : C.muted, fontSize: 9, fontWeight: 800 }}>AUTO</span>
        </div>

        <SectionTitle>작업 일정</SectionTitle>
        <div style={{ border: `1px solid ${C.line}`, borderRadius: 9, padding: '2px 11px' }}>
          <InfoRow label="작업 시작" value={fallback.startTime} />
          <InfoRow label="최초 예상 완료" value={fallback.estOrig} />
          <InfoRow label="현재 예상 완료" value={fallback.estCurr} />
          <InfoRow label="예상 지연" value={fallback.delay} danger={fallback.delay !== '—' && fallback.delay !== '없음'} last />
        </div>

        <SectionTitle>계획 경로</SectionTitle>
        <div style={{ padding: '10px 12px', border: '1px solid #CFE2F7', borderRadius: 9, background: '#F4F8FF', color: route === '—' ? C.muted : '#1155A8', font: `10px ${MONO}`, lineHeight: 1.55 }}>{route}</div>

        <SectionTitle>노드 이동</SectionTitle>
        <div style={{ padding: 11, border: `1px solid ${targetNode ? '#A8CAEF' : C.line}`, borderRadius: 9, background: targetNode ? '#F4F8FF' : '#F8FAFC' }}>
          <div style={{ marginBottom: 9, color: targetNode ? C.primary : C.muted, fontSize: 10, fontWeight: 700 }}>
            {targetNode ? `선택 노드: N${targetNode}` : '맵에서 이동할 노드를 선택하세요.'}
          </div>
          <button onClick={onMove} disabled={!targetNode || !connected || busy !== null} style={primaryButton(Boolean(targetNode && connected && busy === null))}>
            {busy === 'nodeMove' ? '이동 명령 전송 중' : '선택 노드로 이동'}
          </button>
          <div style={{ margin: '10px 0 7px', borderTop: `1px solid ${C.line}` }} />
          <div style={{ marginBottom: 7, color: nearestNode ? C.muted : C.danger, fontSize: 9, lineHeight: 1.5 }}>
            {nearestNode
              ? `가장 가까운 경로 노드: N${nearestNode.id} · 약 ${nearestNode.distance.toFixed(2)}m`
              : '현재 위치 또는 경로 노드 정보를 확인할 수 없습니다.'}
          </div>
          <button onClick={onReturnToRoute} disabled={!nearestNode || !connected || busy !== null} style={secondaryButton(Boolean(nearestNode && connected && busy === null))}>
            {busy === 'returnToRoute' ? '경로 복귀 명령 전송 중' : '가장 가까운 노드로 복귀'}
          </button>
        </div>

        <SectionTitle>원격제어</SectionTitle>
        <div style={{ opacity: controlsEnabled ? 1 : .48 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}>
            {KEY_ROWS.flat().map(({ k, l }) => {
              const pressed = remoteKeys.has(k.toLowerCase())
              return (
                <button key={k} disabled={!controlsEnabled}
                  onPointerDown={() => controlsEnabled && onRemoteDown(k)}
                  onPointerUp={() => controlsEnabled && onRemoteUp(k)}
                  onPointerLeave={() => pressed && onRemoteUp(k)}
                  style={{ height: 44, borderRadius: 8, border: `1px solid ${pressed ? C.primary : '#BEC8D6'}`, background: pressed ? '#EAF2FF' : '#fff', color: C.text, fontSize: 11, fontWeight: 900 }}>
                  {k}<span style={{ display: 'block', marginTop: 2, color: C.muted, fontSize: 8, fontWeight: 500 }}>{l}</span>
                </button>
              )
            })}
          </div>
          <button disabled={!controlsEnabled} onClick={onRemoteStop} style={{ width: '100%', height: 38, marginTop: 6, borderRadius: 8, border: '1px solid #BEC8D6', background: '#fff', color: C.text, fontSize: 10, fontWeight: 800 }}>SPACE · 주행 정지</button>
        </div>

        <SectionTitle>직접 제어</SectionTitle>
        <button onClick={onCharge} disabled={!connected || busy !== null} style={secondaryButton(connected && busy === null)} title={chargingNode ? `충전 노드 ${chargingNode}` : '충전 노드 등록 필요'}>
          {busy === 'charge' ? '충전 이동 명령 전송 중' : '충전 스테이션으로 이동'}
        </button>
        <button onClick={onStop} disabled={!connected || busy !== null} style={dangerButton(connected && busy === null)}>
          {busy === 'stop' ? '정지 명령 전송 중' : '정지'}
          <span style={{ display: 'block', marginTop: 2, fontSize: 8, fontWeight: 500 }}>현재 선택된 로봇만 정지</span>
        </button>
      </div>
    </aside>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ margin: '16px 0 7px', color: '#8B97A5', fontSize: 8.5, fontWeight: 800, letterSpacing: '.09em' }}>{children}</div>
}

function StatusCard({ label, value, color, children }: { label: string; value: string; color: string; children?: React.ReactNode }) {
  return <div style={{ padding: '10px 11px', border: `1px solid ${C.line}`, borderRadius: 9, background: '#F8FAFC' }}><span style={{ color: C.muted, fontSize: 9 }}>{label}</span><strong style={{ display: 'block', marginTop: 5, color, fontSize: 13 }}>{value}</strong>{children}</div>
}

function InfoRow({ label, value, danger = false, last = false }: { label: string; value: string; danger?: boolean; last?: boolean }) {
  return <div style={{ minHeight: 32, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: last ? 0 : `1px solid ${C.line}` }}><span style={{ color: C.muted, fontSize: 10 }}>{label}</span><strong style={{ color: danger ? C.danger : C.text, font: `600 10px ${MONO}` }}>{value}</strong></div>
}

function CommandToast({ state, onClose }: { state: NonNullable<CommandState>; onClose: () => void }) {
  const palette = state.tone === 'success' ? { bg: '#E9F8F3', bd: '#A8DECE', fg: '#1A7A55' } : state.tone === 'danger' ? { bg: '#FFF0F2', bd: '#F1C8CD', fg: C.danger } : { bg: '#EDF6FF', bd: '#B9DAFB', fg: C.primary }
  return <div role="status" style={{ position: 'absolute', top: 14, left: '50%', transform: 'translateX(-50%)', zIndex: 30, display: 'flex', alignItems: 'center', gap: 10, maxWidth: 440, padding: '9px 12px', borderRadius: 8, border: `1px solid ${palette.bd}`, background: palette.bg, color: palette.fg, boxShadow: '0 4px 14px rgba(0,0,0,.1)', fontSize: 10, fontWeight: 700 }}><span>{state.message}</span><button onClick={onClose} style={{ border: 0, background: 'transparent', color: palette.fg, cursor: 'pointer' }}>×</button></div>
}

function primaryButton(active: boolean): React.CSSProperties {
  return { width: '100%', height: 44, border: 0, borderRadius: 8, background: active ? C.primary : '#DDE3EC', color: active ? '#fff' : '#9AA4B0', fontSize: 11, fontWeight: 800, cursor: active ? 'pointer' : 'not-allowed' }
}

function secondaryButton(active: boolean): React.CSSProperties {
  return { width: '100%', minHeight: 44, borderRadius: 8, border: `1px solid ${active ? '#9DC4F0' : C.line}`, background: active ? '#EDF6FF' : '#F3F5F8', color: active ? '#1155A8' : '#9AA4B0', fontSize: 11, fontWeight: 800, cursor: active ? 'pointer' : 'not-allowed' }
}

function dangerButton(active: boolean): React.CSSProperties {
  return { width: '100%', minHeight: 48, marginTop: 8, borderRadius: 8, border: `1px solid ${active ? '#E09AA6' : C.line}`, background: active ? '#FFF1F3' : '#F3F5F8', color: active ? C.danger : '#9AA4B0', fontSize: 11, fontWeight: 900, cursor: active ? 'pointer' : 'not-allowed' }
}
