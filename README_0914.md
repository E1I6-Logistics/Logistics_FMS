# Logistics_FMS

물류센터 환경에서 다중 로봇을 관리하기 위한 FMS(Fleet Management System) 프로젝트.

ROS 2 Jazzy / Nav2 기반 로봇과 Zenoh로 통신하고, FastAPI Backend와 React/Vite Frontend를 통해 Route Graph 확인, 로봇 제어, Telemetry 수집 및 FMS 관제를 수행한다.

---

# 1. 실행 방법

프로젝트는 아래 순서로 실행한다.

```text
① Docker Infrastructure
   ├─ Zenoh Router
   └─ PostgreSQL
          ↓
② FastAPI Backend
          ↓
③ React Frontend
          ↓
④ Mock Fleet 또는 실제 Robot
```

## Terminal 1 - Infrastructure

```bash
cd ~/Logistics_FMS

docker compose -f infra/docker-compose.yml up -d
```

실행 확인:

```bash
docker ps
```

기본적으로 아래 서비스가 실행되어야 한다.

```text
fms-zenoh-router
fms-postgres
```

기본 포트:

| 서비스 | Port |
|---|---:|
| Zenoh | 7447 |
| PostgreSQL | 5432 |
| Backend | 8000 |
| Frontend | 5173 |

---

## Terminal 2 - Backend

```bash
cd ~/Logistics_FMS

source ~/venv/robot/bin/activate
source /opt/ros/jazzy/setup.bash

uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

Backend:

```text
http://localhost:8000
```

FastAPI Swagger:

```text
http://localhost:8000/docs
```

간단 확인:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/route/summary
curl http://127.0.0.1:8000/api/route/nodes
```

---

## Terminal 3 - Frontend

현재 Frontend는 `pnpm` 기준으로 실행한다.

Node.js는 현재 Frontend 구성 기준 **22.12 이상**을 권장한다.

최초 1회:

```bash
npm install --global pnpm

cd ~/Logistics_FMS/frontend
pnpm install --frozen-lockfile
```

실행:

```bash
cd ~/Logistics_FMS/frontend
pnpm dev --host
```

접속:

```text
http://localhost:5173
```

같은 네트워크의 다른 PC에서 접속하는 경우:

```text
http://<FMS_PC_IP>:5173
```

Backend가 다른 PC 또는 주소에서 실행되는 경우 Vite 환경변수를 지정한다.

```env
VITE_FMS_API_BASE=http://127.0.0.1:8000
VITE_FMS_WS_BASE=ws://127.0.0.1:8000
```

---

## Terminal 4 - Mock Fleet

실제 로봇 없이 통신 구조를 검증할 경우:

```bash
cd ~/Logistics_FMS

source ~/venv/robot/bin/activate
source /opt/ros/jazzy/setup.bash

python simulation/mock_fleet.py
```

실제 로봇을 사용하는 경우 Mock Fleet과 동일한 Robot ID가 충돌하지 않도록 Mock 실행을 종료한다.

---

## 종료

Backend / Frontend / Robot:

```text
Ctrl + C
```

Docker:

```bash
cd ~/Logistics_FMS
docker compose -f infra/docker-compose.yml down
```

---

# 2. 최근 변경 사항

기존 구조에서 다음 내용을 변경했다.

- Backend의 단일 `main.py` 구조를 `routers / services / schemas / database`로 모듈화
- 기존 Frontend의 하드코딩 Node/Edge 대신 `routes/test.geojson` 기반 Route Graph 사용
- 특정 Node 이동을 `/api/command/goal-node`로 Backend와 연결
- 선택한 로봇에 대한 키보드 수동제어를 `/ws/cmd_vel` WebSocket으로 연결
- Frontend의 `R-01` 형식과 Backend/Zenoh의 `robot1` 형식을 Backend에서 변환
- 기존 Warehouse UI와 화면 구성은 유지

현재 지도 위 **Node/Edge는 GeoJSON 기반**으로 변경되었으며, 로봇 마커 위치는 아직 기존 데모 데이터를 유지한다. 실제 Robot 위치는 이후 `/api/robots`와 `/ws/dashboard` Telemetry로 연결한다.

---

# 3. 개발 환경

| 항목 | 환경 |
|---|---|
| OS | Ubuntu 24.04 LTS |
| ROS 2 | Jazzy |
| Navigation | Nav2 |
| Python | Python 3.12 |
| Frontend | React + Vite + TypeScript |
| Backend | FastAPI |
| 통신 | Zenoh |
| Database | PostgreSQL |
| Container | Docker / Docker Compose |

Frontend는 현재 구성 기준 Node.js 22.12 이상 및 pnpm 사용을 권장한다.

---

# 4. 프로젝트 구조

```text
Logistics_FMS/
├── backend/
│   ├── app/
│   │   ├── database/
│   │   │   ├── __init__.py
│   │   │   └── database.py
│   │   │
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── commands.py
│   │   │   ├── connections.py
│   │   │   ├── map.py
│   │   │   ├── robots.py
│   │   │   └── websocket.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── command.py
│   │   │   └── robot.py
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── map_service.py
│   │   │   ├── network_service.py
│   │   │   ├── route_graph.py
│   │   │   └── zenoh_service.py
│   │   │
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── main.py
│   │
│   ├── __init__.py
│   ├── .env.example
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── fmsApi.ts
│   │   ├── hooks/
│   │   │   ├── useCmdVel.ts
│   │   │   └── useRouteGraph.ts
│   │   ├── App.tsx
│   │   ├── WarehouseGeometry.tsx
│   │   ├── WarehouseMap.tsx
│   │   └── warehouse-map.css
│   ├── package.json
│   └── pnpm-lock.yaml
│
├── infra/
│   ├── zenoh/
│   └── docker-compose.yml
│
├── maps/
│   ├── my_map.pgm
│   ├── my_map.png
│   └── my_map.yaml
│
├── routes/
│   └── test.geojson
│
├── robots/
├── simulation/
├── debug/
├── doc/
│
├── setup.sh
├── verify_env.sh
└── README.md
```

---

# 5. Backend 구조

Backend는 요청 처리, 실제 FMS 로직, 데이터 모델, DB 처리를 분리한다.

```text
routers/
→ REST / WebSocket Endpoint

schemas/
→ 요청/응답 데이터 구조

services/
→ Map / Route / Zenoh / Network 핵심 로직

database/
→ PostgreSQL 저장 및 조회

config.py
→ 공통 설정

main.py
→ FastAPI 조립 및 Lifecycle
```

## `backend/app/main.py`

Backend Entry Point.

담당:

- FastAPI 생성
- CORS 설정
- Router 등록
- PostgreSQL 시작/종료
- Zenoh 시작/종료
- Map / Route Graph 초기 확인
- `/health`

---

## `database/database.py`

PostgreSQL 처리.

주요 기능:

- DB Connection Pool
- `robots` 테이블
- `telemetry_logs` 테이블
- Robot 최신 상태 저장
- Telemetry History 저장
- Robot 상태 조회

---

## `routers/map.py`

Map / Route Graph API.

```text
GET /api/map/info
GET /api/map/image
GET /api/route/graph
GET /api/route/summary
GET /api/route/nodes
GET /api/route/nodes/{node_id}
```

---

## `routers/robots.py`

Robot 상태 조회.

```text
GET /api/robots
GET /api/robots/{robot_id}
```

---

## `routers/commands.py`

Robot 명령 처리.

```text
GET  /api/command/status
GET  /api/command/capabilities

POST /api/command/goal
POST /api/command/goal-node
POST /api/command/stop
```

`goal-node`는 Frontend가 Node ID만 전달하면 Backend가 GeoJSON에서 좌표를 찾아 Robot Goal로 변환한다.

---

## `routers/websocket.py`

실시간 통신.

```text
WS /ws/dashboard
WS /ws/cmd_vel
```

- `/ws/dashboard`: Robot Telemetry → Frontend
- `/ws/cmd_vel`: Frontend 수동제어 → Robot

cmd_vel WebSocket 종료 시 마지막 제어 Robot에 정지 명령을 전달하는 Fail-safe를 사용한다.

---

## `routers/connections.py`

Zenoh 연결 장치 상태 및 IP 차단/허용.

```text
GET  /api/connections
POST /api/connections/block
POST /api/connections/allow
```

---

# 6. Backend Service

## `services/map_service.py`

ROS Occupancy Map 처리.

- `my_map.yaml` Load
- `my_map.pgm` Load
- PGM → PNG
- World ↔ Pixel 좌표 변환
- Map Metadata 제공

---

## `services/route_graph.py`

`routes/test.geojson` 처리.

- GeoJSON Node 조회
- 전체 Node 목록 생성
- `startid`, `endid` 기반 Edge 구성
- Frontend 렌더링용 Route Graph 생성
- Node ID → 실제 좌표 조회

Route Graph의 기준 데이터는 `test.geojson`이다.

---

## `services/zenoh_service.py`

FMS ↔ Robot 통신 핵심 Service.

- Zenoh Session
- Telemetry Subscribe
- Goal Publish
- cmd_vel Publish
- ROS2 CDR Payload 생성
- Dashboard WebSocket Broadcast
- Robot Stop

---

## `services/network_service.py`

Network 상태 관리.

- Zenoh Peer 확인
- Robot IP 상태 확인
- `iptables` Block / Allow

---

# 7. Frontend 구조

Frontend는 기존 `sein-ui`의 Dashboard UI를 유지하면서 실제 Backend 연결 기능을 추가했다.

## `src/App.tsx`

전체 FMS Dashboard.

- Robot 선택
- 관리자 모드
- 상세 Panel
- 제어 메뉴
- Node 이동
- 키보드 원격제어
- 작업 / 알람 / 로그 UI

---

## `src/WarehouseMap.tsx`

Warehouse Map 렌더링.

- Node / Edge
- Robot Marker
- Route
- Zoom / Pan
- Layer On/Off
- 목표 Node 선택
- 원본 Map 비교

Node/Edge는 기존 하드코딩 배열 대신 Backend Route API에서 가져온다.

---

## `src/WarehouseGeometry.tsx`

Warehouse의 벽, 구조물 등 UI용 Geometry.

현재 기존 135 × 135 Map 기반 SVG Geometry를 유지한다.

---

## `src/api/fmsApi.ts`

Backend 주소와 REST / WebSocket API 연결을 관리한다.

기본 주소:

```text
REST : http://127.0.0.1:8000
WS   : ws://127.0.0.1:8000
```

---

## `src/hooks/useRouteGraph.ts`

Backend에서 Route Graph를 읽어 WarehouseMap에서 사용할 Node/Edge 데이터로 변환한다.

사용 API:

```text
GET /api/route/nodes
GET /api/route/graph
```

---

## `src/hooks/useCmdVel.ts`

선택 Robot의 키보드 수동제어 WebSocket을 관리한다.

사용 API:

```text
WS /ws/cmd_vel
```

현재 키:

```text
W       전진
S       후진

Q / A   좌회전
E / D   우회전

SPACE   정지
```

관리자 모드 + 원격제어 ON 상태에서 활성화된다.

WebSocket 종료 또는 Browser Focus 해제 시 `0 cmd_vel`을 전송한다.

---

# 8. Map / Route Graph

## Map

```text
maps/my_map.yaml
maps/my_map.pgm
maps/my_map.png
```

ROS Occupancy Map 데이터.

---

## Route Graph

```text
routes/test.geojson
```

로봇 이동 경로의 기준 데이터.

```text
GeoJSON
   ├─ Node/Edge 지도 표시
   ├─ 목표 Node Picker
   ├─ Goal 좌표 조회
   └─ 향후 Path Planning
```

Node/Edge를 Frontend에 별도로 하드코딩하지 않고 GeoJSON을 공통 기준으로 사용한다.

---

# 9. 데이터 흐름

## Route Graph

```text
routes/test.geojson
        ↓
route_graph.py
        ↓
/api/route/nodes
/api/route/graph
        ↓
useRouteGraph.ts
        ↓
WarehouseMap.tsx
```

## Node Goal

```text
Operator
   ↓
Frontend에서 Node 선택
   ↓
POST /api/command/goal-node
   ↓
commands.py
   ↓
route_graph.py
   ↓
Node ID → x/y
   ↓
zenoh_service.py
   ↓
robotN/goal
   ↓
Robot
```

## Manual Control

```text
Operator
   ↓
Robot 선택
   ↓
관리자 모드
   ↓
원격제어 ON
   ↓
Keyboard
   ↓
useCmdVel.ts
   ↓
WS /ws/cmd_vel
   ↓
websocket.py
   ↓
zenoh_service.py
   ↓
robotN/cmd_vel
   ↓
Robot
```

## Telemetry

```text
Robot
   ↓
Zenoh
   ↓
zenoh_service.py
   ├─ PostgreSQL
   └─ /ws/dashboard
          ↓
       Frontend
```

---

# 10. 주요 Backend API

| 방식 | Endpoint | 역할 |
|---|---|---|
| GET | `/health` | Backend 상태 |
| GET | `/api/map/info` | Map Metadata |
| GET | `/api/map/image` | Map Image |
| GET | `/api/route/graph` | GeoJSON Route Graph |
| GET | `/api/route/summary` | Route Graph 요약 |
| GET | `/api/route/nodes` | Node 목록 |
| GET | `/api/route/nodes/{node_id}` | 특정 Node |
| GET | `/api/robots` | 전체 Robot 상태 |
| GET | `/api/robots/{robot_id}` | 특정 Robot 상태 |
| GET | `/api/command/status` | Zenoh / Command 상태 |
| GET | `/api/command/capabilities` | 지원 기능 |
| POST | `/api/command/goal` | 좌표 기반 Goal |
| POST | `/api/command/goal-node` | Node 기반 Goal |
| POST | `/api/command/stop` | Robot 정지 |
| GET | `/api/connections` | 연결 장치 |
| POST | `/api/connections/block` | 연결 차단 |
| POST | `/api/connections/allow` | 연결 허용 |
| WS | `/ws/dashboard` | 실시간 Telemetry |
| WS | `/ws/cmd_vel` | 실시간 수동제어 |

---

# 11. 최초 환경 설치

처음 개발 PC를 구성하는 경우:

```bash
cd ~/Logistics_FMS

chmod +x setup.sh verify_env.sh

./setup.sh
```

Docker 그룹 변경이 적용되지 않은 경우 로그아웃 후 다시 로그인한다.

환경 검증:

```bash
cd ~/Logistics_FMS

./verify_env.sh
```

`setup.sh`는 최초 환경 구성용이므로 매번 실행할 필요가 없다.

---

# 12. 문제 확인

## Backend

```bash
curl http://127.0.0.1:8000/health
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

Route Graph:

```bash
curl http://127.0.0.1:8000/api/route/summary
```

---

## Docker

```bash
docker ps
```

---

## ROS 2

```bash
source /opt/ros/jazzy/setup.bash

echo $ROS_DISTRO
ros2 pkg prefix nav2_bringup
```

---

## Python

```bash
source ~/venv/robot/bin/activate

python --version
pip --version
```

---

## Frontend

```bash
node --version
pnpm --version
```

빌드 확인:

```bash
cd ~/Logistics_FMS/frontend
pnpm run build
```

TypeScript 확인:

```bash
pnpm typecheck
```

---

# 13. 현재 구현 범위

현재 실제 Backend 연동 범위:

```text
Map Metadata / Image
GeoJSON Route Graph
Node 조회
Node 기반 Goal
좌표 기반 Goal
Robot Stop
cmd_vel 수동제어
Zenoh Telemetry 수신
PostgreSQL Robot 상태 저장
Dashboard WebSocket
Zenoh Peer 확인
IP Block / Allow
```

현재 Frontend에서 실제 연결한 범위:

```text
GeoJSON Node
GeoJSON Edge
특정 Node 이동
선택 Robot cmd_vel
```

현재 아직 데모 상태인 주요 부분:

```text
지도 위 Robot 실시간 위치
일부 작업 / 배차 / 알람 데이터
일부 Robot Route 표시
```

다음 단계에서는 `/api/robots` + `/ws/dashboard`를 사용해 Robot 위치 및 상태를 실시간 데이터로 전환한다.

---

# 14. 구조 확장 원칙

새 기능은 `main.py`에 직접 계속 추가하지 않고 역할별로 분리한다.

예:

```text
services/
├── dispatch_service.py
├── path_planner.py
├── occupancy_service.py
└── vlm_service.py

routers/
├── tasks.py
├── dispatch.py
└── occupancy.py
```

기준:

```text
routers   → API
schemas   → 데이터 형식
services  → FMS 로직
database  → 저장/조회
config    → 설정
main      → 조립
```

---

# 15. 시스템 구조

```text
ROS 2 / Nav2 Robot
        │
        ▼
      Zenoh
        │
        ▼
┌──────────────────┐
│   FMS Backend    │
│     FastAPI      │
└────────┬─────────┘
         │
    ┌────┴────────────┐
    │                 │
    ▼                 ▼
PostgreSQL       REST / WebSocket
                      │
                      ▼
               ┌──────────────┐
               │ FMS Frontend │
               │ React / Vite │
               └──────────────┘
```
