// React의 핵심 훅(Hooks)들을 불러옵니다. (상태 관리, 부수 효과 처리, 캐싱, DOM 참조 등)
import React, { useEffect, useMemo, useRef, useState } from 'react';

export default function App() {
  // ==========================================================
  // 공통
  // ==========================================================
  // 화면의 탭(실시간 관제, WMS, 연결 관리) 상태를 관리합니다.
  const [activeTab, setActiveTab] = useState('control');
  // 백엔드와의 통합 웹소켓 연결 상태를 텍스트로 표시하기 위한 변수입니다.
  const [wsStatus, setWsStatus] = useState('연결 시도 중...');
  // Zenoh 네트워크에 연결된 기기 목록과 에러 메시지를 관리합니다.
  const [devices, setDevices] = useState([]);
  const [deviceError, setDeviceError] = useState('');
  // 현재 웹페이지가 접속된 도메인/IP를 기반으로 API 서버 주소를 동적으로 설정합니다.
  const BACKEND_HOST = window.location.hostname;
  const API_BASE = `http://${BACKEND_HOST}:8000`;

  // ==========================================================
  // ACS / FMS 관제 상태
  // ==========================================================
  // 웹소켓으로 수신한 각 로봇의 실시간 상태(위치, 배터리 등)를 객체 형태로 저장합니다.
  const [robots, setRobots] = useState({});
  // 지도의 메타데이터(크기, 해상도, 기준점 등), 경로 그래프 정보, 그리고 PGM에서 변환된 지도 이미지를 저장합니다.
  const [mapInfo, setMapInfo] = useState(null);
  const [routeGraph, setRouteGraph] = useState(null);
  const [mapImage, setMapImage] = useState(null);
  const [mapError, setMapError] = useState('');
  // 맵의 엣지(경로 선)들의 상태(OCCUPIED 등)와 선택된 노드를 추적합니다.
  const [edgeStates, setEdgeStates] = useState({});
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  // 화면 크기가 바뀔 때마다 Canvas를 다시 그리도록 유도하는 트리거 변수입니다.
  const [canvasRevision, setCanvasRevision] = useState(0);

  // 사용자가 지도에서 목표 지점을 클릭했을 때, 이동을 명령할 대상 로봇과 좌표를 저장합니다.
  const [targetRobot, setTargetRobot] = useState('robot1');
  const [targetX, setTargetX] = useState(3.5);
  const [targetY, setTargetY] = useState(2.0);

  // ==========================================================
  // CMD_VEL 실시간 테스트 상태
  // ==========================================================
  // 수동 조작(조이스틱) 탭에서 선택된 로봇과 직진/회전 속도를 설정합니다.
  const [cmdRobot, setCmdRobot] = useState('robot1');
  const [linearSpeed, setLinearSpeed] = useState(0.2);
  const [angularSpeed, setAngularSpeed] = useState(0.8);
  const [cmdWsStatus, setCmdWsStatus] = useState('연결 시도 중...');
  const [cmdTxCount, setCmdTxCount] = useState(0);

  // useRef를 사용한 변수들은 렌더링을 발생시키지 않으면서도 최신 값을 즉시 참조해야 할 때(예: setInterval 내부) 사용합니다.
  const cmdWsRef = useRef(null);
  const cmdTimerRef = useRef(null);
  const cmdRobotRef = useRef('robot1');

  // Canvas DOM 요소에 직접 접근하여 그림을 그리기 위한 참조 변수들입니다.
  const canvasRef = useRef(null);
  const canvasWrapRef = useRef(null);
  const viewTransformRef = useRef(null);

  // ==========================================================
  // WMS 상태 - 기존 코드 유지
  // ==========================================================
  // 창고 내 재고 목록을 모의(Mock) 데이터로 관리합니다. 각 물품이 어느 랙(Rack)과 좌표에 있는지 나타냅니다.
  const [inventory] = useState([
    { sku_id: 'SKU-001', name: '알루미늄 프로파일', stock_qty: 120, rack_zone: 'Rack-A', coord_x: 3.0, coord_y: 2.0 },
    { sku_id: 'SKU-002', name: '모터 드라이버 모듈', stock_qty: 45, rack_zone: 'Rack-B', coord_x: -2.0, coord_y: 4.0 },
    { sku_id: 'SKU-003', name: '리튬이온 배터리 팩', stock_qty: 15, rack_zone: 'Rack-C', coord_x: 0.0, coord_y: -3.0 },
  ]);

  // 배차된 주문들의 목록입니다. 향후 백엔드의 LLM 서버와 연동되어 사유(llm_reason)가 자동 생성될 수 있습니다.
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
  // 백엔드에서 받은 경로(GeoJSON) 데이터가 바뀔 때만 재연산(useMemo)하여 노드(점)와 엣지(선)로 분류합니다.
  const graphData = useMemo(() => {
    if (!routeGraph?.features) {
      return { nodes: [], edges: [], nodeMap: new Map() };
    }

    // GeoJSON에서 'Point' 타입은 주행 가능한 거점(Node)을 의미합니다.
    const nodes = routeGraph.features.filter(
      (feature) => feature?.geometry?.type === 'Point'
    );

    // 'LineString' 타입은 거점 사이를 잇는 길(Edge)을 의미합니다.
    const edges = routeGraph.features.filter((feature) => {
      const type = feature?.geometry?.type;
      return type === 'LineString' || type === 'MultiLineString';
    });

    // 각 노드의 ID를 키(Key)로 하는 Map을 만들어두면, 엣지를 그릴 때 시작점/끝점 노드의 좌표를 빠르게 찾을 수 있습니다.
    const nodeMap = new Map();
    nodes.forEach((node) => {
      nodeMap.set(Number(node.properties.id), node);
    });

    return { nodes, edges, nodeMap };
  }, [routeGraph]);

  // ==========================================================
  // 1. 정적 데이터(Map YAML/PGM + GeoJSON) 1회 로드
  // ==========================================================
  // 앱이 처음 실행될 때(마운트) 딱 한 번만 백엔드(main.py)의 API를 호출하여 기반 데이터를 가져옵니다.
  useEffect(() => {
    let cancelled = false;

    async function loadStaticMapData() {
      try {
        setMapError('');

        // 맵 정보, 경로 그래프, 현재 DB에 저장된 로봇 목록을 병렬(Promise.all)로 빠르게 동시에 가져옵니다.
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

        // 컴포넌트가 언마운트된 경우 상태 업데이트를 방지합니다. (메모리 누수 방지)
        if (cancelled) return;

        setMapInfo(info);
        setRouteGraph(graph);

        // DB에서 불러온 초기 로봇 상태들을 딕셔너리(객체) 형태로 변환하여 저장합니다.
        if (robotResponse.ok) {
          const robotList = await robotResponse.json();
          const robotObject = {};
          robotList.forEach((robot) => {
            robotObject[robot.robot_id] = robot;
          });
          setRobots(robotObject);
        }

        // 백엔드가 PGM을 PNG로 변환해준 URL을 이용해 브라우저 메모리에 이미지 객체를 생성합니다.
        const image = new Image();
        image.crossOrigin = 'anonymous'; // CORS 이슈를 방지합니다.
        image.onload = () => {
          if (!cancelled) setMapImage(image); // 이미지 로딩이 완료되면 상태에 저장하여 Canvas가 그리도록 합니다.
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
  // 실시간 관제를 위해 백엔드의 `/ws/dashboard` 엔드포인트와 통신을 엽니다.
  useEffect(() => {
    const socket = new WebSocket(`ws://${BACKEND_HOST}:8000/ws/dashboard`);

    socket.onopen = () => setWsStatus('🟢 실시간 관제 연결됨');
    socket.onclose = () => setWsStatus('🔴 백엔드 연결 끊김');
    socket.onerror = () => setWsStatus('⚠️ 연결 오류');

    // 백엔드에서 브로드캐스트(Broadcast)하는 데이터를 수신할 때마다 실행됩니다.
    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        // 메인 PC가 전달한 텔레메트리(위치, 상태) 데이터라면, 로봇 목록 상태(robots)를 기존 값과 병합하여 최신화합니다.
        if (msg.type === 'telemetry') {
          const d = msg.data;
          setRobots((prev) => ({ ...prev, [d.robot_id]: d }));
        }

        // 향후 FMS Traffic Manager에서 이런 메시지를 보내면 바로 표시 가능
        // { type: 'edge_state', data: { edge_id: 16, state: 'OCCUPIED', robot_id: 'robot1' } }
        // 경로 막힘, 충돌 방지를 위한 교차로 통제(Traffic) 상태를 업데이트합니다.
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
  // 2-1. CMD_VEL WebSocket
  // ==========================================================
  // 로봇을 수동으로 직접 조종하기 위해 분리된 전용 웹소켓(빠른 전송 주기)입니다.
  useEffect(() => {
    const socket = new WebSocket(`ws://${BACKEND_HOST}:8000/ws/cmd_vel`);
    cmdWsRef.current = socket;

    socket.onopen = () => setCmdWsStatus('CONNECTED');
    socket.onclose = () => setCmdWsStatus('DISCONNECTED');
    socket.onerror = () => setCmdWsStatus('ERROR');

    // 연결 문제나 사용자 실수 발생 시 즉시 로봇을 멈추는(속도 0 전송) 페일세이프(Fail-Safe) 함수입니다.
    const emergencyStop = () => {
      if (cmdTimerRef.current) {
        clearInterval(cmdTimerRef.current);
        cmdTimerRef.current = null;
      }

      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          robot_id: cmdRobotRef.current,
          linear_x: 0.0,
          angular_z: 0.0,
        }));
      }
    };

    // 브라우저가 포커스를 잃거나 마우스/터치가 풀리면 즉시 정지
    // 사용자가 조이스틱 버튼을 누르다가 브라우저 창을 벗어나거나 화면 밖을 터치하면 로봇이 폭주할 수 있으므로, 해당 이벤트 발생 시 무조건 emergencyStop을 호출합니다.
    window.addEventListener('blur', emergencyStop);
    window.addEventListener('pointerup', emergencyStop);
    window.addEventListener('pointercancel', emergencyStop);

    return () => {
      emergencyStop();
      window.removeEventListener('blur', emergencyStop);
      window.removeEventListener('pointerup', emergencyStop);
      window.removeEventListener('pointercancel', emergencyStop);
      socket.close();
      cmdWsRef.current = null;
    };
  }, [BACKEND_HOST]);

  // 수동 조작 대상 로봇이 변경될 때마다 최신 값을 ref에도 동기화하여 setInterval 내부에서 올바른 타겟을 잡게 합니다.
  useEffect(() => {
    cmdRobotRef.current = cmdRobot;
  }, [cmdRobot]);

  // ==========================================================
  // Zenoh 연결 장비 관리
  // ==========================================================
  // 백엔드의 iptables(방화벽) 규칙에 등록된 접속 기기 상태를 2초마다 주기적으로 확인하는 폴링(Polling) 로직입니다.
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

  // 특정 기기(IP)의 통신을 차단(block)하거나 허용(allow)해달라고 백엔드 API에 요청합니다.
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
  // 브라우저 창 크기가 변하거나 탭이 전환될 때, Canvas 영역을 감지하고 리렌더링을 유발하여 지도를 찌그러짐 없이 다시 그립니다.
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
  // Canvas 크기에 지도를 딱 맞게 넣기 위해 배율(viewScale)과 여백(offsetX, Y)을 계산합니다.
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

  // ROS 기준의 실제 물리적 미터(m) 좌표를 브라우저 화면의 픽셀(px) 좌표로 변환합니다. (로봇을 그릴 때 사용)
  function rosToCanvas(x, y, info, view) {
    const [originX, originY, originYaw = 0] = info.origin;

    // 일반적인 ROS SLAM map yaml은 yaw=0이다.
    // yaw가 존재하면 world -> map-local로 역회전한다.
    // 지도의 기준점(Origin)과 각도를 빼서 순수한 맵 원점 기준 좌표(localX, localY)를 구합니다.
    const dx = x - originX;
    const dy = y - originY;
    const c = Math.cos(-originYaw);
    const s = Math.sin(-originYaw);
    const localX = c * dx - s * dy;
    const localY = s * dx + c * dy;

    // resolution(미터/픽셀 비율)으로 나누어 PGM 이미지상의 픽셀 좌표를 구합니다. 
    // ROS는 y축이 위로 증가하지만, 웹(Canvas)은 아래로 증가하므로 height에서 빼줍니다.
    const mapPixelX = localX / info.resolution;
    const mapPixelY = info.height - localY / info.resolution;

    // 화면 비율(viewScale)과 여백을 적용하여 최종 브라우저상 좌표를 리턴합니다.
    return {
      x: view.offsetX + mapPixelX * view.viewScale,
      y: view.offsetY + mapPixelY * view.viewScale,
    };
  }

  // 브라우저 화면의 클릭 픽셀(px) 좌표를 역으로 계산하여 ROS 기준의 목표 미터(m) 좌표로 환산합니다. (명령 내릴 때 사용)
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
  // 경로 엣지에 진행 방향을 알려주는 화살표 머리를 그리는 헬퍼(Helper) 함수입니다.
  function drawArrowHead(ctx, from, to, size = 8) {
    const angle = Math.atan2(to.y - from.y, to.x - from.x);
    // 선의 62% 지점(가운데보다 약간 앞)에 화살표를 위치시킵니다.
    const arrowPoint = {
      x: from.x + (to.x - from.x) * 0.62,
      y: from.y + (to.y - from.y) * 0.62,
    };

    // 삼각 함수를 이용해 화살표 양 날개의 좌표를 계산하고 색칠합니다.
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

  // 해당 경로(Edge)의 상태에 따라 선의 색상을 결정합니다. (비어있음=초록, 로봇 사용중=빨강 등)
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
  // 데이터(로봇 위치, 지도)가 변할 때마다 초당 수십 번 호출되어 화면(Canvas)을 완전히 지우고 새로 그리는 핵심 렌더링 훅입니다.
  useEffect(() => {
    if (activeTab !== 'control') return;

    const canvas = canvasRef.current;
    const wrapper = canvasWrapRef.current;
    if (!canvas || !wrapper) return;

    const rect = wrapper.getBoundingClientRect();
    // 레티나 디스플레이 등 고해상도 모니터에서 픽셀이 깨지지 않도록 기기 픽셀 비율(dpr)을 곱해 선명하게 설정합니다.
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

    // 화면 전체를 남색 배경으로 덮어 이전 프레임을 지웁니다(초기화).
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
    // 이미지를 확대할 때 뿌옇게(Anti-aliasing) 되지 않고 도트(픽셀)가 그대로 살도록 설정합니다.
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
    // GeoJSON에서 파싱한 경로 선(Edge)들을 먼저 그립니다.
    graphData.edges.forEach((edge) => {
      const edgeId = Number(edge.properties?.id);
      const startId = Number(edge.properties?.startid);
      const endId = Number(edge.properties?.endid);

      const startNode = graphData.nodeMap.get(startId);
      const endNode = graphData.nodeMap.get(endId);
      if (!startNode || !endNode) return;

      const [startX, startY] = startNode.geometry.coordinates;
      const [endX, endY] = endNode.geometry.coordinates;
      // ROS 좌표를 Canvas 픽셀 좌표로 변환합니다.
      const start = rosToCanvas(startX, startY, mapInfo, view);
      const end = rosToCanvas(endX, endY, mapInfo, view);

      const stroke = edgeStrokeFor(edgeId);
      ctx.strokeStyle = stroke;
      ctx.fillStyle = stroke;
      // 엣지에 상태(교통 통제)가 적용되었으면 선을 굵게(5), 아니면 일반(3) 굵기로 그립니다.
      ctx.lineWidth = edgeStates[edgeId] ? 5 : 3;
      ctx.globalAlpha = 0.9;

      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();

      // 화살표 머리를 추가합니다.
      drawArrowHead(ctx, start, end, edgeStates[edgeId] ? 10 : 8);
      ctx.globalAlpha = 1;
    });

    // 4-3. Route Node
    // 거점(Node) 동그라미들을 그립니다.
    graphData.nodes.forEach((node) => {
      const nodeId = Number(node.properties?.id);
      const [x, y] = node.geometry.coordinates;
      const point = rosToCanvas(x, y, mapInfo, view);

      const selected = nodeId === selectedNodeId;
      // 마우스 클릭 등으로 선택된 노드는 노란색, 아니면 하늘색으로 칠합니다.
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
    // 최신 좌표를 바탕으로 로봇(가장 위 레이어)을 그립니다.
    Object.entries(robots).forEach(([id, robot]) => {
      const point = rosToCanvas(robot.x, robot.y, mapInfo, view);

      // 로봇 본체(파란색 원)
      ctx.fillStyle = '#0284c7';
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(point.x, point.y, 12, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // yaw는 ROS 좌표 기준. canvas y축은 아래쪽이라 화면 각도 계산 시 부호를 반전.
      // 로봇이 바라보는 방향(Heading)을 흰색 직선으로 나타냅니다. 
      const headingLength = 22;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      ctx.lineTo(
        point.x + Math.cos(robot.yaw) * headingLength,
        point.y - Math.sin(robot.yaw) * headingLength // 웹 환경에서는 Y가 밑으로 향하므로 부호를 뒤집습니다.
      );
      ctx.stroke();

      // 로봇 근처에 ID 텍스트를 출력합니다.
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
  // 사용자가 지도 화면을 클릭했을 때 실행됩니다.
  const handleMapClick = (event) => {
    if (!mapInfo || !viewTransformRef.current) return;

    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    // Canvas 좌상단을 (0,0)으로 삼기 위해 오프셋을 뺍니다.
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;

    const view = viewTransformRef.current;

    // 클릭한 곳이 지도의 범위를 벗어난 바깥 영역(여백)이라면 무시합니다.
    const insideMap =
      mouseX >= view.offsetX &&
      mouseX <= view.offsetX + view.drawWidth &&
      mouseY >= view.offsetY &&
      mouseY <= view.offsetY + view.drawHeight;

    if (!insideMap) return;

    // 픽셀을 ROS 미터 좌표로 환산하여 상태(state)에 반영합니다.
    const ros = canvasToRos(mouseX, mouseY, mapInfo, view);
    setTargetX(Number(ros.x.toFixed(3)));
    setTargetY(Number(ros.y.toFixed(3)));

    // 클릭한 지점과 가장 가까운 Node도 표시
    // 거점 근처를 클릭했다면 해당 노드를 0.4m 반경 내에서 검색하여 자동 선택(스냅)해줍니다.
    let nearestNode = null;
    let nearestDistance = Infinity;

    graphData.nodes.forEach((node) => {
      const [nx, ny] = node.geometry.coordinates;
      const distance = Math.hypot(nx - ros.x, ny - ros.y); // 거리 계산 (피타고라스)
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
  // 우측 하단의 [Nav2 목표 전송] 버튼을 눌렀을 때 백엔드 API로 이동 명령 데이터를 쏘아줍니다.
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
  // CMD_VEL 20Hz 실시간 전송
  // ==========================================================
  // 조이스틱 웹소켓(cmd_vel)으로 데이터를 날리는 실제 전송부입니다.
  const sendCmdVel = (robotId, linearX, angularZ) => {
    const socket = cmdWsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;

    socket.send(JSON.stringify({
      robot_id: robotId,
      linear_x: linearX,
      angular_z: angularZ,
    }));

    setCmdTxCount((count) => count + 1);
    return true;
  };

  // 버튼에서 손을 떼었을 때 타이머를 초기화하고 속도를 0으로 만들어 로봇을 정지시킵니다.
  const stopCmd = () => {
    if (cmdTimerRef.current) {
      clearInterval(cmdTimerRef.current);
      cmdTimerRef.current = null;
    }

    sendCmdVel(cmdRobotRef.current, 0.0, 0.0);
  };

  // 조이스틱 버튼을 누르는 순간 호출되며, 첫 명령을 쏘고 50ms마다(초당 20번, 20Hz) 계속 같은 명령을 날리도록 타이머(setInterval)를 돌립니다.
  const startCmd = (linearX, angularZ) => {
    stopCmd();

    const robotId = cmdRobotRef.current;
    sendCmdVel(robotId, linearX, angularZ);

    cmdTimerRef.current = setInterval(() => {
      sendCmdVel(robotId, linearX, angularZ);
    }, 50); // 20 Hz
  };

  const robotOptions = Object.keys(robots).length > 0
    ? Object.keys(robots).sort()
    : ['robot1', 'robot2', 'robot3'];

  // ==========================================================
  // WMS 주문 시뮬레이션
  // ==========================================================
  // WMS 탭에서 물품 주문 버튼을 누르면 새로운 주문을 생성하여 UI에 모의(Mock)로 추가하는 로직입니다.
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
  
  // 전체 앱의 레이아웃을 감싸는 최상단 컨테이너(100vh 높이 꽉 채움)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#f8fafc', overflow: 'hidden' }}>
      
      {/* 상단 네비게이션 헤더 (GNB) */}
      <div style={{ height: '60px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <h1 style={{ fontSize: '18px', color: '#38bdf8', margin: 0 }}>🚀 통합 FMS / ACS / WMS Hub</h1>
          {/* 화면 전환을 위한 탭 버튼 묶음 */}
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
        {/* 현재 백엔드와의 소켓 연결 상태 텍스트 출력 */}
        <div style={{ fontSize: '13px', color: wsStatus.includes('🟢') ? '#22c55e' : '#ef4444', fontWeight: 'bold' }}>
          {wsStatus}
        </div>
      </div>

      {/* '실시간 관제 (control)' 탭이 선택되었을 때만 렌더링되는 화면 */}
      {activeTab === 'control' && (
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          {/* 좌측 사이드바 패널 (정보 및 조작 패널 모음) */}
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

            {/* 현재 웹소켓으로 수신 중인 로봇들의 상태(배터리 바 등)를 그리는 패널 */}
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
                      {/* 배터리 잔량을 나타내는 초록색 프로그레스 바(Progress bar) */}
                      <div style={{ height: '6px', background: '#334155', borderRadius: '3px', marginTop: '6px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', background: '#22c55e', width: `${Math.max(0, Math.min(100, Number(robot.battery)))}%` }} />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </section>

            {/* 수동 조이스틱 조작 패널 */}
            <section style={panelStyle}>
              <h3 style={panelTitleStyle}>🎮 CMD_VEL 실시간 테스트</h3>

              <select
                value={cmdRobot}
                onChange={(e) => {
                  stopCmd();
                  setCmdRobot(e.target.value);
                  cmdRobotRef.current = e.target.value;
                }}
                style={inputStyle}
              >
                {robotOptions.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </select>

              {/* 상, 하, 좌, 우, 정지 방향키 조이스틱 UI 그리드(Grid) */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 60px)', gap: '8px', justifyContent: 'center', marginTop: '10px' }}>
                <div />
                <button
                  onPointerDown={() => startCmd(linearSpeed, 0.0)}
                  onPointerUp={stopCmd}
                  onPointerCancel={stopCmd}
                  onPointerLeave={stopCmd}
                  style={cmdButtonStyle}
                >
                  ▲
                </button>
                <div />

                <button
                  onPointerDown={() => startCmd(0.0, angularSpeed)}
                  onPointerUp={stopCmd}
                  onPointerCancel={stopCmd}
                  onPointerLeave={stopCmd}
                  style={cmdButtonStyle}
                >
                  ◀
                </button>

                <button
                  onClick={stopCmd}
                  style={{ ...cmdButtonStyle, background: '#dc2626' }}
                >
                  ■
                </button>

                <button
                  onPointerDown={() => startCmd(0.0, -angularSpeed)}
                  onPointerUp={stopCmd}
                  onPointerCancel={stopCmd}
                  onPointerLeave={stopCmd}
                  style={cmdButtonStyle}
                >
                  ▶
                </button>

                <div />
                <button
                  onPointerDown={() => startCmd(-linearSpeed, 0.0)}
                  onPointerUp={stopCmd}
                  onPointerCancel={stopCmd}
                  onPointerLeave={stopCmd}
                  style={cmdButtonStyle}
                >
                  ▼
                </button>
                <div />
              </div>

              {/* 전진(Linear) / 회전(Angular) 최대 속도 조절 슬라이더 */}
              <div style={{ marginTop: '12px' }}>
                <div style={rowStyle}>
                  <span>Linear</span>
                  <span>{linearSpeed.toFixed(2)} m/s</span>
                </div>
                <input
                  type="range"
                  min="0.05"
                  max="0.5"
                  step="0.05"
                  value={linearSpeed}
                  onChange={(e) => setLinearSpeed(Number(e.target.value))}
                  style={{ width: '100%' }}
                />
              </div>

              <div style={{ marginTop: '8px' }}>
                <div style={rowStyle}>
                  <span>Angular</span>
                  <span>{angularSpeed.toFixed(2)} rad/s</span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="2.0"
                  step="0.1"
                  value={angularSpeed}
                  onChange={(e) => setAngularSpeed(Number(e.target.value))}
                  style={{ width: '100%' }}
                />
              </div>

              <div style={{ ...rowStyle, marginTop: '10px' }}>
                <span>CMD WebSocket</span>
                <span style={{ color: cmdWsStatus === 'CONNECTED' ? '#22c55e' : '#ef4444', fontWeight: 'bold' }}>
                  {cmdWsStatus}
                </span>
              </div>
              <div style={rowStyle}><span>TX Rate</span><span>20 Hz</span></div>
              <div style={rowStyle}><span>TX Count</span><span>{cmdTxCount}</span></div>
              <div style={{ marginTop: '8px', fontSize: '11px', color: '#94a3b8', lineHeight: 1.5 }}>
                버튼을 누르고 있는 동안 연속 전송하며, 손을 떼면 즉시 정지 명령을 보냅니다.
              </div>
            </section>

            {/* 자율 주행 목적지 좌표 수동 전송 폼 */}
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

          {/* 지도와 로봇이 그려지는 메인 Canvas 래퍼(Wrapper) 구역 */}
          <div ref={canvasWrapRef} style={{ flex: 1, minWidth: 0, minHeight: 0, position: 'relative', background: '#0b1120' }}>
            <canvas ref={canvasRef} onClick={handleMapClick} style={{ display: 'block', width: '100%', height: '100%', cursor: 'crosshair' }} />

            {/* 지도 좌측 하단에 떠 있는 경로 상태 범례(Legend) UI */}
            <div style={{ position: 'absolute', left: 14, bottom: 14, background: 'rgba(15, 23, 42, 0.88)', border: '1px solid #334155', borderRadius: '7px', padding: '9px 12px', fontSize: '11px', lineHeight: 1.7, pointerEvents: 'none' }}>
              <div><span style={{ color: '#22c55e' }}>━━▶</span> FREE</div>
              <div><span style={{ color: '#f59e0b' }}>━━▶</span> RESERVED</div>
              <div><span style={{ color: '#ef4444' }}>━━▶</span> OCCUPIED</div>
              <div><span style={{ color: '#a855f7' }}>━━▶</span> BLOCKED</div>
            </div>
          </div>
        </div>
      )}

      {/* 'WMS' 탭이 선택되었을 때 나타나는 재고 관리 및 주문 화면 */}
      {activeTab === 'wms' && (
        <div style={{ display: 'flex', flex: 1, padding: '20px', gap: '20px', overflowY: 'auto' }}>
          <div style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '20px' }}>
            <h2 style={{ fontSize: '16px', color: '#38bdf8', marginTop: 0 }}>📦 창고 실시간 재고 현황 (WMS)</h2>
            {/* 재고 목록을 테이블(Table) 형태로 렌더링합니다. */}
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

          {/* 우측: 주문 생성기 및 LLM 로깅 화면 */}
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

      {/* '연결 관리(connections)' 탭: 백엔드 iptables 방화벽과 연동되는 관리자 화면 */}
      {activeTab === 'connections' && (
        <div style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
          <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
            <h2 style={{ color: '#38bdf8', marginTop: 0 }}>🔌 Zenoh 연결 관리</h2>
            <div style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '18px' }}>메인 PC TCP 7447에 연결되는 장비를 표시합니다.</div>
            {deviceError && <div style={{ color: '#fca5a5', marginBottom: '12px' }}>조회 오류: {deviceError}</div>}
            
            {/* 승인된 장비와 차단된 장비를 2분할(Grid)하여 렌더링합니다. */}
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

// 연결 관리 화면의 각 기기(IP) 아이템 한 줄을 렌더링하는 서브 컴포넌트입니다.
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

// ==========================================================
// 하단은 컴포넌트 전체에서 재사용되는 인라인 CSS 스타일 객체들의 모음입니다.
// CSS 파일에 분리하지 않고 JS 내부에 작성하여 관리를 용이하게 한 패턴입니다.
// ==========================================================
const cmdButtonStyle = {
  width: '60px',
  height: '48px',
  background: '#0284c7',
  color: '#fff',
  border: 'none',
  borderRadius: '6px',
  cursor: 'pointer',
  fontSize: '20px',
  fontWeight: 'bold',
  userSelect: 'none', /* 조이스틱 버튼 클릭 시 텍스트 블록 지정 방지 */
  touchAction: 'none', /* 모바일에서 버튼을 누를 때 화면이 스크롤되는 현상 방지 */
};

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