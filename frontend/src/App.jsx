import React, { useEffect, useMemo, useRef, useState } from 'react';

export default function App() {
  // ==========================================================
  // 공통
  // ==========================================================
  const [activeTab, setActiveTab] = useState('control');
  const [wsStatus, setWsStatus] = useState('연결 시도 중...');
  const [devices, setDevices] = useState([]);
  const [deviceError, setDeviceError] = useState('');
  const BACKEND_HOST = window.location.hostname;
  const API_BASE = `http://${BACKEND_HOST}:8000`;

  // ==========================================================
  // ACS / FMS 관제 상태
  // ==========================================================
  const [robots, setRobots] = useState({});
  const [mapInfo, setMapInfo] = useState(null);
  const [routeGraph, setRouteGraph] = useState(null);
  const [mapImage, setMapImage] = useState(null);
  const [mapError, setMapError] = useState('');
  const [edgeStates, setEdgeStates] = useState({});
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [canvasRevision, setCanvasRevision] = useState(0);

  const [targetRobot, setTargetRobot] = useState('robot1');
  const [targetX, setTargetX] = useState(3.5);
  const [targetY, setTargetY] = useState(2.0);

  const canvasRef = useRef(null);
  const canvasWrapRef = useRef(null);
  const viewTransformRef = useRef(null);

  // ==========================================================
  // WMS 상태 - 기존 코드 유지
  // ==========================================================
  const [inventory] = useState([
    { sku_id: 'SKU-001', name: '알루미늄 프로파일', stock_qty: 120, rack_zone: 'Rack-A', coord_x: 3.0, coord_y: 2.0 },
    { sku_id: 'SKU-002', name: '모터 드라이버 모듈', stock_qty: 45, rack_zone: 'Rack-B', coord_x: -2.0, coord_y: 4.0 },
    { sku_id: 'SKU-003', name: '리튬이온 배터리 팩', stock_qty: 15, rack_zone: 'Rack-C', coord_x: 0.0, coord_y: -3.0 },
  ]);

  const [orders, setOrders] = useState([
    { order_id: 'ORD-101', item: 'SKU-001 (수량: 5)', status: 'DISPATCHED', llm_reason: 'robot1이 Rack-A 최단 거리 및 배터리 95% 상태로 최적 할당됨.' },
    { order_id: 'ORD-102', item: 'SKU-003 (수량: 2)', status: 'PENDING', llm_reason: '배차 대기 중...' },
  ]);

  const [newOrderSku, setNewOrderSku] = useState('SKU-001');
  const [newOrderQty, setNewOrderQty] = useState(1);
  const [llmAutoMode, setLlmAutoMode] = useState(true);

  // ==========================================================
  // GeoJSON 파싱
  // ==========================================================
  const graphData = useMemo(() => {
    if (!routeGraph?.features) {
      return { nodes: [], edges: [], nodeMap: new Map() };
    }

    const nodes = routeGraph.features.filter(
      (feature) => feature?.geometry?.type === 'Point'
    );

    const edges = routeGraph.features.filter((feature) => {
      const type = feature?.geometry?.type;
      return type === 'LineString' || type === 'MultiLineString';
    });

    const nodeMap = new Map();
    nodes.forEach((node) => {
      nodeMap.set(Number(node.properties.id), node);
    });

    return { nodes, edges, nodeMap };
  }, [routeGraph]);

  // ==========================================================
  // 1. 정적 데이터(Map YAML/PGM + GeoJSON) 1회 로드
  // ==========================================================
  useEffect(() => {
    let cancelled = false;

    async function loadStaticMapData() {
      try {
        setMapError('');

        const [mapResponse, graphResponse, robotResponse] = await Promise.all([
          fetch(`${API_BASE}/api/map/info`),
          fetch(`${API_BASE}/api/route/graph`),
          fetch(`${API_BASE}/api/robots`),
        ]);

        if (!mapResponse.ok) {
          throw new Error(`Map info HTTP ${mapResponse.status}`);
        }
        if (!graphResponse.ok) {
          throw new Error(`Route graph HTTP ${graphResponse.status}`);
        }

        const info = await mapResponse.json();
        const graph = await graphResponse.json();

        if (cancelled) return;

        setMapInfo(info);
        setRouteGraph(graph);

        if (robotResponse.ok) {
          const robotList = await robotResponse.json();
          const robotObject = {};
          robotList.forEach((robot) => {
            robotObject[robot.robot_id] = robot;
          });
          setRobots(robotObject);
        }

        const image = new Image();
        image.crossOrigin = 'anonymous';
        image.onload = () => {
          if (!cancelled) setMapImage(image);
        };
        image.onerror = () => {
          if (!cancelled) setMapError('맵 PNG 변환 이미지를 불러오지 못했습니다.');
        };
        image.src = `${API_BASE}${info.image_url}`;
      } catch (error) {
        console.error(error);
        if (!cancelled) {
          setMapError(`정적 지도 로딩 실패: ${error.message}`);
        }
      }
    }

    loadStaticMapData();

    return () => {
      cancelled = true;
    };
  }, [API_BASE]);

  // ==========================================================
  // 2. WebSocket: 동적 데이터만 수신
  // ==========================================================
  useEffect(() => {
    const socket = new WebSocket(`ws://${BACKEND_HOST}:8000/ws/dashboard`);

    socket.onopen = () => setWsStatus('🟢 실시간 관제 연결됨');
    socket.onclose = () => setWsStatus('🔴 백엔드 연결 끊김');
    socket.onerror = () => setWsStatus('⚠️ 연결 오류');

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'telemetry') {
          const d = msg.data;
          setRobots((prev) => ({ ...prev, [d.robot_id]: d }));
        }

        // 향후 FMS Traffic Manager에서 이런 메시지를 보내면 바로 표시 가능
        // { type: 'edge_state', data: { edge_id: 16, state: 'OCCUPIED', robot_id: 'robot1' } }
        if (msg.type === 'edge_state') {
          const d = msg.data;
          setEdgeStates((prev) => ({
            ...prev,
            [Number(d.edge_id)]: d,
          }));
        }
      } catch (error) {
        console.error('WebSocket 파싱 에러:', error);
      }
    };

    return () => socket.close();
  }, [BACKEND_HOST]);

  // ==========================================================
  // Zenoh 연결 장비 관리
  // ==========================================================
  useEffect(() => {
    let stopped = false;
    async function loadDevices() {
      try {
        const response = await fetch(`${API_BASE}/api/connections`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (!stopped) {
          setDevices(data.devices || []);
          setDeviceError('');
        }
      } catch (error) {
        if (!stopped) setDeviceError(error.message);
      }
    }
    loadDevices();
    const timer = setInterval(loadDevices, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, [API_BASE]);

  const changeDeviceAccess = async (ip, action) => {
    try {
      const response = await fetch(`${API_BASE}/api/connections/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '처리 실패');
      setDevices(data.devices || []);
    } catch (error) {
      alert(`연결 관리 실패: ${error.message}`);
    }
  };

  // ==========================================================
  // 3. Canvas 크기 변경 감지
  // ==========================================================
  useEffect(() => {
    const wrapper = canvasWrapRef.current;
    if (!wrapper) return;

    const observer = new ResizeObserver(() => {
      setCanvasRevision((value) => value + 1);
    });

    observer.observe(wrapper);
    return () => observer.disconnect();
  }, [activeTab]);

  // ==========================================================
  // 좌표 변환
  // ROS map 좌표(m) -> PGM 픽셀 -> Canvas 픽셀
  // ==========================================================
  function createViewTransform(canvas, info) {
    const padding = 28;
    const mapWidth = info.width;
    const mapHeight = info.height;

    const availableWidth = Math.max(1, canvas.width - padding * 2);
    const availableHeight = Math.max(1, canvas.height - padding * 2);

    const viewScale = Math.min(
      availableWidth / mapWidth,
      availableHeight / mapHeight
    );

    const drawWidth = mapWidth * viewScale;
    const drawHeight = mapHeight * viewScale;
    const offsetX = (canvas.width - drawWidth) / 2;
    const offsetY = (canvas.height - drawHeight) / 2;

    return {
      viewScale,
      drawWidth,
      drawHeight,
      offsetX,
      offsetY,
    };
  }

  function rosToCanvas(x, y, info, view) {
    const [originX, originY, originYaw = 0] = info.origin;

    // 일반적인 ROS SLAM map yaml은 yaw=0이다.
    // yaw가 존재하면 world -> map-local로 역회전한다.
    const dx = x - originX;
    const dy = y - originY;
    const c = Math.cos(-originYaw);
    const s = Math.sin(-originYaw);
    const localX = c * dx - s * dy;
    const localY = s * dx + c * dy;

    const mapPixelX = localX / info.resolution;
    const mapPixelY = info.height - localY / info.resolution;

    return {
      x: view.offsetX + mapPixelX * view.viewScale,
      y: view.offsetY + mapPixelY * view.viewScale,
    };
  }

  function canvasToRos(canvasX, canvasY, info, view) {
    const [originX, originY, originYaw = 0] = info.origin;

    const mapPixelX = (canvasX - view.offsetX) / view.viewScale;
    const mapPixelY = (canvasY - view.offsetY) / view.viewScale;

    const localX = mapPixelX * info.resolution;
    const localY = (info.height - mapPixelY) * info.resolution;

    const c = Math.cos(originYaw);
    const s = Math.sin(originYaw);

    return {
      x: originX + c * localX - s * localY,
      y: originY + s * localX + c * localY,
    };
  }

  // ==========================================================
  // 방향 화살표
  // ==========================================================
  function drawArrowHead(ctx, from, to, size = 8) {
    const angle = Math.atan2(to.y - from.y, to.x - from.x);
    const arrowPoint = {
      x: from.x + (to.x - from.x) * 0.62,
      y: from.y + (to.y - from.y) * 0.62,
    };

    ctx.beginPath();
    ctx.moveTo(arrowPoint.x, arrowPoint.y);
    ctx.lineTo(
      arrowPoint.x - size * Math.cos(angle - Math.PI / 6),
      arrowPoint.y - size * Math.sin(angle - Math.PI / 6)
    );
    ctx.lineTo(
      arrowPoint.x - size * Math.cos(angle + Math.PI / 6),
      arrowPoint.y - size * Math.sin(angle + Math.PI / 6)
    );
    ctx.closePath();
    ctx.fill();
  }

  function edgeStrokeFor(edgeId) {
    const state = edgeStates[edgeId]?.state;
    if (state === 'OCCUPIED') return '#ef4444';
    if (state === 'RESERVED') return '#f59e0b';
    if (state === 'BLOCKED') return '#a855f7';
    return '#22c55e';
  }

  // ==========================================================
  // 4. 실제 지도 + Route Graph + Robot 렌더링
  // ==========================================================
  useEffect(() => {
    if (activeTab !== 'control') return;

    const canvas = canvasRef.current;
    const wrapper = canvasWrapRef.current;
    if (!canvas || !wrapper) return;

    const rect = wrapper.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;

    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 이후 계산은 CSS pixel 기준
    const logicalCanvas = {
      width: rect.width,
      height: rect.height,
    };

    ctx.clearRect(0, 0, logicalCanvas.width, logicalCanvas.height);
    ctx.fillStyle = '#0b1120';
    ctx.fillRect(0, 0, logicalCanvas.width, logicalCanvas.height);

    if (!mapInfo || !mapImage) {
      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px sans-serif';
      ctx.fillText('ROS2 Map 로딩 중...', 24, 34);
      return;
    }

    const view = createViewTransform(logicalCanvas, mapInfo);
    viewTransformRef.current = view;

    // 4-1. PGM -> PNG 지도 배경
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(
      mapImage,
      view.offsetX,
      view.offsetY,
      view.drawWidth,
      view.drawHeight
    );

    // 지도 외곽선
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1;
    ctx.strokeRect(view.offsetX, view.offsetY, view.drawWidth, view.drawHeight);

    // 4-2. Route Edge
    graphData.edges.forEach((edge) => {
      const edgeId = Number(edge.properties?.id);
      const startId = Number(edge.properties?.startid);
      const endId = Number(edge.properties?.endid);

      const startNode = graphData.nodeMap.get(startId);
      const endNode = graphData.nodeMap.get(endId);
      if (!startNode || !endNode) return;

      const [startX, startY] = startNode.geometry.coordinates;
      const [endX, endY] = endNode.geometry.coordinates;
      const start = rosToCanvas(startX, startY, mapInfo, view);
      const end = rosToCanvas(endX, endY, mapInfo, view);

      const stroke = edgeStrokeFor(edgeId);
      ctx.strokeStyle = stroke;
      ctx.fillStyle = stroke;
      ctx.lineWidth = edgeStates[edgeId] ? 5 : 3;
      ctx.globalAlpha = 0.9;

      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();

      drawArrowHead(ctx, start, end, edgeStates[edgeId] ? 10 : 8);
      ctx.globalAlpha = 1;
    });

    // 4-3. Route Node
    graphData.nodes.forEach((node) => {
      const nodeId = Number(node.properties?.id);
      const [x, y] = node.geometry.coordinates;
      const point = rosToCanvas(x, y, mapInfo, view);

      const selected = nodeId === selectedNodeId;
      ctx.fillStyle = selected ? '#facc15' : '#38bdf8';
      ctx.strokeStyle = '#082f49';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(point.x, point.y, selected ? 7 : 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#0f172a';
      ctx.font = 'bold 11px sans-serif';
      ctx.fillText(String(nodeId), point.x + 8, point.y - 7);
    });

    // 4-4. 실시간 Robot
    Object.entries(robots).forEach(([id, robot]) => {
      const point = rosToCanvas(robot.x, robot.y, mapInfo, view);

      ctx.fillStyle = '#0284c7';
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(point.x, point.y, 12, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // yaw는 ROS 좌표 기준. canvas y축은 아래쪽이라 화면 각도 계산 시 부호를 반전.
      const headingLength = 22;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      ctx.lineTo(
        point.x + Math.cos(robot.yaw) * headingLength,
        point.y - Math.sin(robot.yaw) * headingLength
      );
      ctx.stroke();

      ctx.fillStyle = '#0f172a';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText(id, point.x - 18, point.y - 18);
    });
  }, [
    activeTab,
    canvasRevision,
    mapInfo,
    mapImage,
    graphData,
    robots,
    edgeStates,
    selectedNodeId,
  ]);

  // ==========================================================
  // Canvas 클릭 -> ROS 좌표 목표 입력
  // ==========================================================
  const handleMapClick = (event) => {
    if (!mapInfo || !viewTransformRef.current) return;

    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;

    const view = viewTransformRef.current;

    const insideMap =
      mouseX >= view.offsetX &&
      mouseX <= view.offsetX + view.drawWidth &&
      mouseY >= view.offsetY &&
      mouseY <= view.offsetY + view.drawHeight;

    if (!insideMap) return;

    const ros = canvasToRos(mouseX, mouseY, mapInfo, view);
    setTargetX(Number(ros.x.toFixed(3)));
    setTargetY(Number(ros.y.toFixed(3)));

    // 클릭한 지점과 가장 가까운 Node도 표시
    let nearestNode = null;
    let nearestDistance = Infinity;

    graphData.nodes.forEach((node) => {
      const [nx, ny] = node.geometry.coordinates;
      const distance = Math.hypot(nx - ros.x, ny - ros.y);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestNode = Number(node.properties.id);
      }
    });

    // 0.4m 이내의 노드가 있으면 선택 표시
    setSelectedNodeId(nearestDistance <= 0.4 ? nearestNode : null);
  };

  // ==========================================================
  // Nav2 목표 전송
  // ==========================================================
  const handleSendGoal = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/command/goal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          robot_id: targetRobot,
          target_x: parseFloat(targetX),
          target_y: parseFloat(targetY),
        }),
      });

      const result = await response.json();
      if (result.status !== 'SUCCESS') {
        throw new Error(result.message || '목표 전송 실패');
      }

      alert(`[${targetRobot}] 목표 전송 성공: (${targetX}, ${targetY})`);
    } catch (error) {
      alert(`목표 전송 실패: ${error.message}`);
    }
  };

  // ==========================================================
  // WMS 주문 시뮬레이션
  // ==========================================================
  const handleCreateOrder = () => {
    const newId = `ORD-${Math.floor(100 + Math.random() * 900)}`;
    const targetItem = inventory.find((item) => item.sku_id === newOrderSku);

    const simulatedReason = llmAutoMode
      ? `[LLM 분석] 품목(${targetItem.name}) 위치(${targetItem.rack_zone}) 기준 가장 인접하고 배터리가 충분한 robot1을 최적 로봇으로 선정함.`
      : '[수동 지정] 관리자 오버라이드 배차 완료.';

    const newOrder = {
      order_id: newId,
      item: `${newOrderSku} (수량: ${newOrderQty})`,
      status: 'DISPATCHED',
      llm_reason: simulatedReason,
    };

    setOrders((prev) => [newOrder, ...prev]);
    alert(`신규 주문 접수 및 LLM 자동 배차 완료 (${newId})`);
  };

  // ==========================================================
  // UI
  // ==========================================================
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#f8fafc', overflow: 'hidden' }}>
      <div style={{ height: '60px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <h1 style={{ fontSize: '18px', color: '#38bdf8', margin: 0 }}>🚀 통합 FMS / ACS / WMS Hub</h1>
          <div style={{ display: 'flex', background: '#0f172a', borderRadius: '6px', padding: '3px', border: '1px solid #334155' }}>
            <button onClick={() => setActiveTab('control')} style={tabButtonStyle(activeTab === 'control')}>
              🗺️ 실시간 관제 (FMS/ACS)
            </button>
            <button onClick={() => setActiveTab('wms')} style={tabButtonStyle(activeTab === 'wms')}>
              📦 재고 관리 & LLM 배차 (WMS)
            </button>
            <button onClick={() => setActiveTab('connections')} style={tabButtonStyle(activeTab === 'connections')}>
              🔌 연결 관리
            </button>
          </div>
        </div>
        <div style={{ fontSize: '13px', color: wsStatus.includes('🟢') ? '#22c55e' : '#ef4444', fontWeight: 'bold' }}>
          {wsStatus}
        </div>
      </div>

      {activeTab === 'control' && (
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          <div style={{ width: '360px', background: '#1e293b', padding: '18px', borderRight: '1px solid #334155', display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto', flexShrink: 0 }}>
            <section style={panelStyle}>
              <h3 style={panelTitleStyle}>🗺️ 정적 지도 / Route Graph</h3>
              {mapError ? (
                <div style={{ color: '#fca5a5', fontSize: '12px', lineHeight: 1.5 }}>{mapError}</div>
              ) : (
                <div style={{ fontSize: '12px', lineHeight: 1.7, color: '#cbd5e1' }}>
                  <div>Map: {mapInfo ? `${mapInfo.width} × ${mapInfo.height} px` : '로딩 중...'}</div>
                  <div>Resolution: {mapInfo ? `${mapInfo.resolution} m/px` : '-'}</div>
                  <div>Origin: {mapInfo ? `(${mapInfo.origin[0]}, ${mapInfo.origin[1]}, ${mapInfo.origin[2]})` : '-'}</div>
                  <div>Node: {graphData.nodes.length}개</div>
                  <div>Edge: {graphData.edges.length}개</div>
                  <div style={{ marginTop: '6px', color: '#94a3b8' }}>맵을 클릭하면 ROS 목표 좌표가 입력됩니다.</div>
                </div>
              )}
            </section>

            <section>
              <h3 style={panelTitleStyle}>🤖 연동된 로봇 실시간 상태</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {Object.keys(robots).length === 0 ? (
                  <div style={{ color: '#64748b', fontSize: '13px', textAlign: 'center', padding: '14px' }}>
                    연결된 로봇 대기 중...
                  </div>
                ) : (
                  Object.entries(robots).map(([id, robot]) => (
                    <div key={id} style={panelStyle}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '7px' }}>
                        <span style={{ fontWeight: 'bold' }}>{id}</span>
                        <span style={{ fontSize: '11px', color: '#38bdf8' }}>{robot.status}</span>
                      </div>
                      <div style={rowStyle}><span>위치</span><span>({Number(robot.x).toFixed(2)}, {Number(robot.y).toFixed(2)}) m</span></div>
                      <div style={rowStyle}><span>Yaw</span><span>{Number(robot.yaw).toFixed(2)} rad</span></div>
                      <div style={rowStyle}><span>배터리</span><span>{Number(robot.battery).toFixed(1)}%</span></div>
                      <div style={{ height: '6px', background: '#334155', borderRadius: '3px', marginTop: '6px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', background: '#22c55e', width: `${Math.max(0, Math.min(100, Number(robot.battery)))}%` }} />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </section>

            <section style={{ ...panelStyle, marginTop: 'auto' }}>
              <h3 style={panelTitleStyle}>수동 주행 목표 전송 (ACS)</h3>
              <input value={targetRobot} onChange={(e) => setTargetRobot(e.target.value)} placeholder="로봇 ID" style={inputStyle} />
              <input type="number" value={targetX} onChange={(e) => setTargetX(e.target.value)} placeholder="목표 X (m)" step="0.1" style={inputStyle} />
              <input type="number" value={targetY} onChange={(e) => setTargetY(e.target.value)} placeholder="목표 Y (m)" step="0.1" style={inputStyle} />
              {selectedNodeId !== null && (
                <div style={{ fontSize: '12px', color: '#facc15', marginTop: '5px' }}>
                  가장 가까운 Route Node: {selectedNodeId}
                </div>
              )}
              <button onClick={handleSendGoal} style={primaryButtonStyle}>Nav2 목표 전송</button>
            </section>
          </div>

          <div ref={canvasWrapRef} style={{ flex: 1, minWidth: 0, minHeight: 0, position: 'relative', background: '#0b1120' }}>
            <canvas ref={canvasRef} onClick={handleMapClick} style={{ display: 'block', width: '100%', height: '100%', cursor: 'crosshair' }} />

            <div style={{ position: 'absolute', left: 14, bottom: 14, background: 'rgba(15, 23, 42, 0.88)', border: '1px solid #334155', borderRadius: '7px', padding: '9px 12px', fontSize: '11px', lineHeight: 1.7, pointerEvents: 'none' }}>
              <div><span style={{ color: '#22c55e' }}>━━▶</span> FREE</div>
              <div><span style={{ color: '#f59e0b' }}>━━▶</span> RESERVED</div>
              <div><span style={{ color: '#ef4444' }}>━━▶</span> OCCUPIED</div>
              <div><span style={{ color: '#a855f7' }}>━━▶</span> BLOCKED</div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'wms' && (
        <div style={{ display: 'flex', flex: 1, padding: '20px', gap: '20px', overflowY: 'auto' }}>
          <div style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '20px' }}>
            <h2 style={{ fontSize: '16px', color: '#38bdf8', marginTop: 0 }}>📦 창고 실시간 재고 현황 (WMS)</h2>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8' }}>
                  <th style={{ padding: '10px' }}>SKU ID</th>
                  <th style={{ padding: '10px' }}>품목명</th>
                  <th style={{ padding: '10px' }}>재고수량</th>
                  <th style={{ padding: '10px' }}>보관 랙</th>
                  <th style={{ padding: '10px' }}>위치 좌표</th>
                </tr>
              </thead>
              <tbody>
                {inventory.map((item) => (
                  <tr key={item.sku_id} style={{ borderBottom: '1px solid #334155' }}>
                    <td style={{ padding: '10px', color: '#38bdf8', fontWeight: 'bold' }}>{item.sku_id}</td>
                    <td style={{ padding: '10px' }}>{item.name}</td>
                    <td style={{ padding: '10px' }}>{item.stock_qty} EA</td>
                    <td style={{ padding: '10px' }}>{item.rack_zone}</td>
                    <td style={{ padding: '10px', color: '#94a3b8' }}>({item.coord_x}, {item.coord_y})</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '20px' }}>
              <h2 style={{ fontSize: '16px', color: '#38bdf8', marginTop: 0 }}>🛒 모바일 앱 주문 시뮬레이터</h2>
              <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
                <select value={newOrderSku} onChange={(e) => setNewOrderSku(e.target.value)} style={{ ...inputStyle, flex: 2 }}>
                  {inventory.map((item) => (
                    <option key={item.sku_id} value={item.sku_id}>{item.sku_id} - {item.name}</option>
                  ))}
                </select>
                <input type="number" value={newOrderQty} onChange={(e) => setNewOrderQty(e.target.value)} min="1" style={{ ...inputStyle, flex: 1 }} />
              </div>
              <label style={{ fontSize: '13px', display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '12px' }}>
                <input type="checkbox" checked={llmAutoMode} onChange={(e) => setLlmAutoMode(e.target.checked)} />
                🧠 LLM 지능형 자동 배차 연동 활성화
              </label>
              <button onClick={handleCreateOrder} style={primaryButtonStyle}>주문 접수 및 LLM 배차 실행</button>
            </div>

            <div style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '20px', overflowY: 'auto' }}>
              <h2 style={{ fontSize: '16px', color: '#38bdf8', marginTop: 0 }}>🤖 LLM 배차 의사결정 로그</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {orders.map((order) => (
                  <div key={order.order_id} style={panelStyle}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ color: '#38bdf8', fontWeight: 'bold' }}>{order.order_id}</span>
                      <span style={{ color: order.status === 'DISPATCHED' ? '#22c55e' : '#f59e0b', fontSize: '11px' }}>[{order.status}]</span>
                    </div>
                    <div style={{ fontSize: '13px', color: '#cbd5e1' }}>주문 품목: {order.item}</div>
                    <div style={{ marginTop: '7px', fontSize: '12px', color: '#94a3b8' }}>{order.llm_reason}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'connections' && (
        <div style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
          <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
            <h2 style={{ color: '#38bdf8', marginTop: 0 }}>🔌 Zenoh 연결 관리</h2>
            <div style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '18px' }}>메인 PC TCP 7447에 연결되는 장비를 표시합니다.</div>
            {deviceError && <div style={{ color: '#fca5a5', marginBottom: '12px' }}>조회 오류: {deviceError}</div>}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '18px' }}>
              <section style={connectionPanelStyle}>
                <h3 style={{ color: '#22c55e', marginTop: 0 }}>승인 / 연결 장비</h3>
                {devices.filter((d) => !d.blocked && (d.known || d.connected)).map((d) => (
                  <DeviceRow key={d.ip} device={d} onAction={changeDeviceAccess} />
                ))}
              </section>
              <section style={connectionPanelStyle}>
                <h3 style={{ color: '#f59e0b', marginTop: 0 }}>미승인 / 차단 장비</h3>
                {devices.filter((d) => d.blocked || (!d.known && d.connected)).map((d) => (
                  <DeviceRow key={d.ip} device={d} onAction={changeDeviceAccess} />
                ))}
              </section>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function DeviceRow({ device, onAction }) {
  const stateColor = device.blocked ? '#ef4444' : device.connected ? '#22c55e' : '#64748b';
  return (
    <div style={{ ...panelStyle, marginBottom: '9px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div>
          <div style={{ fontWeight: 'bold' }}>{device.name}</div>
          <div style={{ color: '#94a3b8', fontSize: '12px' }}>{device.ip}</div>
          <div style={{ color: stateColor, fontSize: '11px', marginTop: '3px' }}>● {device.state}</div>
        </div>
        <button
          onClick={() => onAction(device.ip, device.blocked ? 'allow' : 'block')}
          style={{ ...smallActionButtonStyle, background: device.blocked ? '#0284c7' : '#b91c1c' }}
        >
          {device.blocked ? '연결 허용' : '차단'}
        </button>
      </div>
    </div>
  );
}

const connectionPanelStyle = { background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '18px' };
const smallActionButtonStyle = { border: 'none', color: '#fff', padding: '8px 12px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' };

const panelStyle = {
  background: '#0f172a',
  border: '1px solid #334155',
  borderRadius: '8px',
  padding: '12px',
};

const panelTitleStyle = {
  fontSize: '14px',
  color: '#38bdf8',
  margin: '0 0 9px 0',
};

const rowStyle = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: '12px',
  fontSize: '12px',
  margin: '4px 0',
  color: '#cbd5e1',
};

const inputStyle = {
  width: '100%',
  padding: '8px',
  margin: '4px 0',
  background: '#1e293b',
  border: '1px solid #334155',
  color: '#fff',
  borderRadius: '4px',
  boxSizing: 'border-box',
};

const primaryButtonStyle = {
  width: '100%',
  padding: '10px',
  background: '#0284c7',
  border: 'none',
  color: '#fff',
  borderRadius: '4px',
  cursor: 'pointer',
  fontWeight: 'bold',
  marginTop: '8px',
};

function tabButtonStyle(active) {
  return {
    padding: '6px 16px',
    background: active ? '#0284c7' : 'transparent',
    border: 'none',
    color: '#fff',
    borderRadius: '4px',
    cursor: 'pointer',
    fontWeight: 'bold',
    fontSize: '13px',
  };
}

