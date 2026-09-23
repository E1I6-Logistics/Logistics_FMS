# FMS 백엔드 제어 로직 커스터마이징 가이드

## 1. 작성 목적

이 문서는 현재 FMS 웹 화면을 그대로 구현하는 방법을 설명하기 위한 문서가 아니다.

프론트엔드와 백엔드 사이의 최소 인터페이스만 유지하고, ROS2, Zenoh, 경로 계획, 로봇 상태 관리 및 장비 제어 로직을 사용자가 직접 설계하고 구현하기 위해 작성한다.

기존 프로젝트에는 실제 장비 제어, 시뮬레이션, 네트워크 검색, 경로 계산, telemetry 변환 등 여러 로직이 이미 포함되어 있다. 이러한 구현을 그대로 사용하면 웹 화면은 빠르게 동작하지만, 사용자가 제어 흐름을 직접 설계하고 학습하기 어렵다.

따라서 다음 원칙으로 백엔드를 정리한다.

- 프론트엔드가 호출하는 API와 WebSocket 주소는 유지한다.
- 요청 파라미터와 반환 형식을 명확한 계약으로 남긴다.
- 실제 제어 로직 대신 deterministic mock 응답을 제공한다.
- 사용자가 구현할 위치에는 함수 시그니처와 `TODO`를 남긴다.
- ROS2, Zenoh, PostgreSQL 및 실제 경로 계획 로직은 기본 구현에서 제거한다.
- 사용자는 웹 구조를 수정하지 않고 백엔드 내부 제어 로직만 단계적으로 교체할 수 있어야 한다.
- `command_log`는 현재 작업 범위에 포함하지 않는다.

## 2. 목표 구조

```text
FMS Frontend
    │
    │ REST / WebSocket 계약
    ▼
FastAPI Router
    │
    │ 검증된 파라미터
    ▼
Mock Control Service
    │
    ├── 현재 단계: deterministic mock 응답
    │
    └── 사용자 구현 단계
         ├── ROS2 명령 전송
         ├── Zenoh telemetry 수신
         ├── 경로 계획
         ├── 로봇 상태 관리
         └── 실제 장비 제어
```

프론트엔드는 제어 로직의 내부 구현을 알 필요가 없다. 동일한 요청과 반환 계약만 지키면 mock 구현을 실제 구현으로 교체할 수 있다.

## 3. 프론트엔드가 사용하는 계약

| 프론트 기능 | 계약 | 용도 |
|---|---|---|
| 맵 정보 | `GET /api/map/info` | 맵 크기와 이미지 정보 조회 |
| 맵 이미지 | `GET /api/map/image` | 관제 맵 이미지 표시 |
| 경로 그래프 | `GET /api/route/graph?raw=true` | 노드 연결 관계 표시 |
| 노드 목록 | `GET /api/route/nodes?include_pixel=true` | 노드 선택과 좌표 변환 |
| 모드 조회 | `GET /api/mode` | 실제 로봇/시뮬레이션 모드 표시 |
| 모드 전환 | `PUT /api/mode` | 운용 모드 변경 |
| 로봇 목록 | `GET /api/robots` | 로봇 상태와 위치 조회 |
| 연결 상태 | `GET /api/connections` | 온라인 로봇 수와 연결 상태 표시 |
| 노드 이동 | `POST /api/command/goal-node` | 선택 노드로 이동 |
| 좌표 이동 | `POST /api/command/goal` | 가장 가까운 노드로 복귀 |
| 로봇 정지 | `POST /api/command/stop` | 개별 또는 전체 로봇 정지 |
| 실시간 상태 | `WS /ws/dashboard` | system 및 telemetry 이벤트 수신 |
| 원격제어 | `WS /ws/cmd_vel` | 선속도와 각속도 명령 전송 |

이 계약들은 프론트엔드가 의존하는 인터페이스다. 엔드포인트 경로, 필드명, 자료형을 변경하면 프론트 코드도 함께 변경해야 한다.

## 4. 입력 파라미터

### 4.1 운용 모드 전환

```http
PUT /api/mode
Content-Type: application/json
```

```json
{
  "mode": "simulation"
}
```

`mode`는 다음 값만 허용한다.

```text
real | simulation
```

### 4.2 노드 이동

```http
POST /api/command/goal-node
Content-Type: application/json
```

```json
{
  "robot_id": "R-01",
  "node_id": "8"
}
```

파라미터:

```text
robot_id: string
node_id: string | number
```

### 4.3 좌표 이동

```http
POST /api/command/goal
Content-Type: application/json
```

```json
{
  "robot_id": "R-01",
  "target_x": 1.25,
  "target_y": -0.4
}
```

파라미터:

```text
robot_id: string
target_x: number
target_y: number
```

### 4.4 로봇 정지

```http
POST /api/command/stop
Content-Type: application/json
```

```json
{
  "robot_id": "R-01"
}
```

### 4.5 원격제어

```text
WS /ws/cmd_vel
```

```json
{
  "robot_id": "R-01",
  "linear_x": 0.2,
  "angular_z": 0.0
}
```

파라미터:

```text
robot_id: string
linear_x: number
angular_z: number
```

## 5. Mock 반환 형식

### 5.1 맵 정보

```json
{
  "width": 95,
  "height": 48,
  "image_url": "/api/map/image",
  "image_name": "my_map.pgm"
}
```

맵 이미지 API는 JSON이 아니라 `image/png` 형식의 `FileResponse` 또는 `Response`를 반환한다.

### 5.2 Route Node

```json
[
  {
    "id": "8",
    "x": 1.25,
    "y": -0.4,
    "frame": "map",
    "pixel_x": 72,
    "pixel_y": 31,
    "properties": {}
  }
]
```

`x`, `y`는 실제 제어에서 사용할 월드 좌표이며 `pixel_x`, `pixel_y`는 프론트 맵에 표시할 좌표다.

### 5.3 로봇 상태

```json
{
  "robot_id": "robot1",
  "ui_id": "R-01",
  "status": "IDLE",
  "battery": 95,
  "x": 0.0,
  "y": 0.0,
  "yaw": 0.0,
  "updated_at": "2026-09-22T10:00:00+00:00",
  "mode": "simulation",
  "route": null,
  "pixel_x": 50,
  "pixel_y": 30,
  "map_pose_received": true,
  "connection_state": "ONLINE"
}
```

`GET /api/robots`는 위 객체 세 개를 배열로 반환한다.

```json
[
  { "robot_id": "robot1", "ui_id": "R-01" },
  { "robot_id": "robot2", "ui_id": "R-02" },
  { "robot_id": "robot3", "ui_id": "R-03" }
]
```

실제 반환에서는 축약하지 말고 각 객체에 전체 필드를 포함해야 한다.

`updated_at`은 현재 시각으로 계속 갱신해야 한다. 프론트엔드는 마지막 갱신 후 5초가 지나면 해당 로봇을 오프라인으로 판단한다.

### 5.4 계획 경로

```json
{
  "node_ids": ["0", "3", "8"],
  "edge_ids": ["edge-0-3", "edge-3-8"],
  "phase": "moving",
  "segment_index": 0
}
```

`phase`는 다음 값을 사용한다.

```text
ready | moving
```

### 5.5 운용 모드

```json
{
  "mode": "simulation",
  "real_available": true,
  "simulation_active": true
}
```

### 5.6 연결 상태

```json
{
  "devices": [
    {
      "ip": "mock://robot1",
      "name": "robot1",
      "known": true,
      "connected": true,
      "blocked": false,
      "state": "CONNECTED"
    },
    {
      "ip": "mock://robot2",
      "name": "robot2",
      "known": true,
      "connected": true,
      "blocked": false,
      "state": "CONNECTED"
    },
    {
      "ip": "mock://robot3",
      "name": "robot3",
      "known": true,
      "connected": true,
      "blocked": false,
      "state": "CONNECTED"
    }
  ]
}
```

### 5.7 명령 성공 응답

```json
{
  "status": "SUCCESS",
  "robot_id": "robot1",
  "ui_id": "R-01",
  "command": "goal-node",
  "target": {
    "node_id": "8"
  },
  "mode": "simulation"
}
```

현재 프론트는 명령 응답 본문을 사용하지 않고 HTTP 성공 여부만 확인한다. 이 반환 형식은 이후 실제 제어 구현을 위한 표준 계약으로 사용한다.

### 5.8 명령 오류 응답

FastAPI의 공통 오류 형식을 사용한다.

```json
{
  "detail": "Unknown robot: robot4"
}
```

권장 상태 코드:

| 상태 코드 | 의미 |
|---|---|
| `400` | 잘못된 로봇 ID, 노드 ID 또는 좌표 |
| `404` | 존재하지 않는 로봇 또는 노드 |
| `409` | 현재 로봇 상태에서 수행할 수 없는 명령 |
| `503` | 실제 제어 시스템을 사용할 수 없음 |

## 6. WebSocket 이벤트 계약

### 6.1 Dashboard system 이벤트

```json
{
  "type": "system",
  "data": {
    "mode": "simulation"
  }
}
```

### 6.2 Dashboard telemetry 이벤트

```json
{
  "type": "telemetry",
  "data": {
    "robot_id": "robot1",
    "ui_id": "R-01",
    "status": "IDLE",
    "battery": 95,
    "x": 0.0,
    "y": 0.0,
    "yaw": 0.0,
    "updated_at": "2026-09-22T10:00:00+00:00",
    "mode": "simulation",
    "route": null,
    "pixel_x": 50,
    "pixel_y": 30,
    "map_pose_received": true,
    "connection_state": "ONLINE"
  }
}
```

`GET /api/robots`와 `telemetry.data`는 동일한 로봇 상태 구조를 사용해야 한다.

### 6.3 cmd_vel acknowledgement

```json
{
  "type": "ack",
  "status": "SUCCESS",
  "robot_id": "robot1",
  "command": "cmd_vel"
}
```

현재 프론트는 acknowledgement를 직접 사용하지 않지만, 디버깅 및 향후 상태 표시에 사용할 수 있도록 반환한다.

## 7. 사용자가 구현할 함수 골격

다음 함수들은 API 계약을 유지하면서 내부 로직을 사용자가 직접 작성할 영역이다.

```python
async def set_operation_mode(mode: str) -> dict:
    """
    TODO:
    - real/simulation 값 검증
    - 기존 제어 자원 안전 종료
    - 새로운 제어 자원 초기화
    - dashboard system 이벤트 전송
    - 현재 모드 반환
    """
```

```python
async def get_robot_states() -> list[dict]:
    """
    TODO:
    - telemetry 또는 내부 상태 저장소 조회
    - robot1~robot3 상태 정규화
    - UI ID와 pixel 좌표 계산
    - 프론트 계약에 맞는 배열 반환
    """
```

```python
async def move_robot_to_node(robot_id: str, node_id: str | int) -> dict:
    """
    TODO:
    - 로봇과 노드 존재 여부 검증
    - 현재 위치 확인
    - 경로 생성
    - 실제 제어 시스템에 이동 명령 전달
    - 명령 접수 결과 반환
    """
```

```python
async def move_robot_to_pose(
    robot_id: str,
    target_x: float,
    target_y: float,
) -> dict:
    """
    TODO:
    - 좌표 유효성 검증
    - 안전 영역 확인
    - 실제 제어 시스템에 좌표 이동 명령 전달
    - 명령 접수 결과 반환
    """
```

```python
async def stop_robot(robot_id: str) -> dict:
    """
    TODO:
    - 로봇 존재 여부 검증
    - 자율주행 목표 취소
    - 속도 0 명령 전송
    - 정지 결과 반환
    """
```

```python
async def apply_cmd_vel(
    robot_id: str,
    linear_x: float,
    angular_z: float,
) -> dict:
    """
    TODO:
    - 속도 범위 제한
    - 통신 및 안전 상태 확인
    - 원격 주행 명령 전송
    - acknowledgement 반환
    """
```

## 8. 정리 대상

Mock 서비스로 대체한 후 다음 구현은 제거할 수 있다.

- PostgreSQL 초기화 및 telemetry 저장 코드
- ROS2 Gateway와 Action Client 구현
- Zenoh session과 telemetry subscriber 구현
- iptables 및 `ss` 기반 네트워크 장치 검색
- 기존 RobotManager와 Robot 모델
- 기존 SimulationGateway 이동 계산
- 기존 Route Planner
- 사용하지 않는 command status 및 capabilities API
- route summary와 단일 node 조회 API
- 단일 로봇 조회 API
- 연결 allow/block API
- 비어 있는 placeholder service 파일

최상위 `simulation/` 폴더는 별도의 실험 및 ROS 도구일 수 있으므로 기본 삭제 범위에서 제외한다.

## 9. 구현 순서

1. 프론트 TypeScript 타입을 기준으로 응답 스키마를 확정한다.
2. 인메모리 mock store를 만든다.
3. 모드, 로봇, 연결 API를 mock store에 연결한다.
4. 명령 API를 mock 응답으로 교체한다.
5. Dashboard와 cmd_vel WebSocket을 mock store에 연결한다.
6. FastAPI startup/shutdown에서 ROS2와 Zenoh 의존성을 제거한다.
7. 기존 router와 service의 import를 mock service로 변경한다.
8. 실제 장비 관련 파일을 삭제한다.
9. 미사용 Python 의존성을 제거한다.
10. 서버 시작, 프론트 빌드 및 주요 UI 흐름을 검증한다.

## 10. 검증 기준

- FastAPI 애플리케이션이 ROS2, Zenoh, PostgreSQL 없이 시작된다.
- 프론트 typecheck와 production build가 통과한다.
- 초기 화면에 mock 로봇 세 대가 나타난다.
- 로봇은 5초 이후에도 오프라인으로 전환되지 않는다.
- 실제 로봇/시뮬레이션 모드를 전환할 수 있다.
- 로봇을 선택하면 우측 패널 정보가 변경된다.
- 맵에서 노드를 선택하고 mock 이동 명령을 보낼 수 있다.
- 가장 가까운 노드 복귀 명령을 보낼 수 있다.
- 개별 정지와 전체 비상정지가 성공 응답을 받는다.
- 원격제어 WebSocket이 연결되고 acknowledgement를 반환한다.
- 삭제된 모듈을 참조하는 import가 남아 있지 않다.

## 11. 현재 코드에서 확인된 문제

기존 실제 제어 구현에는 다음 미완성 참조가 존재한다.

- `commands.py`가 구현되지 않은 `ros_gateway.follow_waypoints()`를 호출한다.
- `ros_gateway.py`가 구현되지 않은 `_send_follow_waypoints()`를 호출한다.
- DB 영속화 호출은 1차 구현에서 제거했으며 telemetry는 WebSocket으로만 전달한다.

이 문제들은 mock 전환 후 사용자가 실제 제어 로직을 구현할 때 별도로 설계해야 한다.

## 12. 작업 범위 제외

다음 항목은 현재 정리 범위에 포함하지 않는다.

- `command_log` 저장 및 조회
- 사용자 인증과 권한 관리
- 작업·주문 관리
- 알람 이력
- 로봇팔 제어
- LLM 기반 경로 비교
- 운영 데이터베이스 설계
