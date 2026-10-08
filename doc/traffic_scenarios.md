# 웹·CLI 단일 시나리오 실행

## 사용 방법

1. 변경된 백엔드를 재시작하고 웹 페이지를 새로고침한다.
2. 실제 로봇 또는 시뮬레이션 모드를 선택한다.
3. 지도 상단 좌측 확대 버튼 오른쪽의 콤보박스에서 설명을 선택한다.
4. **테스트 실행**을 누른다. 선택한 시나리오 하나만 실행된다.
5. 버튼 아래에서 진행·완료·실패 사유를 확인한다. 종료 전 다른 테스트는 시작할 수 없다.

CLI도 같은 API를 사용한다. 이름을 생략하면 사용법 오류로 종료한다.

```bash
python3 tests/traffic_scenarios.py cycle
python3 tests/traffic_scenarios.py head_on
python3 tests/traffic_scenarios.py bottleneck
```

CLI는 서버에 설정된 현재 모드를 따른다. 전체 자동 순차 실행은 제거했다.
완료 시 종료 코드 0, 실패/거부/조회 중단 시 1이다. CLI를 닫거나 Ctrl+C를 눌러도
서버가 접수한 테스트는 계속된다. 테스트 중단은 웹의 개별/전체 비상정지를 사용한다.
실행 중 페이지를 닫아도 서버는 계속 실행하고, 다시 열면 상태를 조회한다.

## 모드별 동작

| 항목 | 시뮬레이션 | 실제 로봇 |
| --- | --- | --- |
| 시작 위치 | 기존 좌표 재설정과 빈 노드 임시 배치로 JSON 시작점 복원 | 직접 물리적으로 배치한 위치를 확인하며 자동 이동/좌표 변경 없음 |
| 시작 상태 | 모든 대상이 IDLE이고 활성 이동 요청이 없어야 함 | 연결·최신 위치·IDLE·진행 중 주문/내비게이션 없음 |
| 시작 위치 허용 오차 | Mock 좌표를 노드 좌표에 맞춤 | 기존 `REAL_OCCUPANCY_TOLERANCE_M` 재사용, 기본 0.15m. 가장 가까운 노드도 지정 시작점이어야 함 |
| 이동 | 기존 Mock `navigate_to_node()` | 기존 ROS Gateway `navigate_to_node()` |
| 완료 | 모든 목적지 도착 및 양보 종료 | 목적지 도착 후 기존 ArUco 정렬까지 완료, 모든 대상 IDLE 및 진행 요청 없음 |
| 제한 시간 | 기본 30초 | 기본 180초. 실제 설정/정렬 시간에 맞춰 JSON에서 조정 |

실물 시작 위치가 틀리면 **명령 전송 전에** 불일치 로봇, 필요한 노드, 거리와
허용 오차를 모아 표시한다. 연결 해제·위치 미수신·오래된 위치·기존 작업 중인 로봇도
구체적인 사유를 표시하고 거부한다. 기존 `goal_node`가 완료 뒤 남아 있어도
그 필드 하나만으로 주행 중이라고 판단하지 않는다.

ArUco 정렬을 우회하는 테스트 전용 주행 모드는 만들지 않았다. 기존 일반 이동과
정렬을 유지하되, **주문 없는 이동은 정렬 성공 시 IDLE로 완료**하도록 했다.
이 경우 OMX에 빈 작업을 보내지 않는다. 주문 있는 이동의 ArUco → OMX 흐름은 유지한다.

## 설정 파일

경로: `tests/traffic_scenarios.json`

```json
{
  "base_url": "http://127.0.0.1:8000",
  "timeout_seconds": {"simulation": 30, "real": 180},
  "scenarios": [{
    "name": "cycle",
    "description": "세 로봇의 순환 대기와 해소",
    "robots": [
      {"id": "robot1", "start": "0", "goal": "1"},
      {"id": "robot2", "start": "1", "goal": "2"},
      {"id": "robot3", "start": "2", "goal": "0"}
    ]
  }]
}
```

- `name`: API/CLI 실행 식별자. 중복 불가.
- `description`: 콤보박스에 표시할 설명.
- `robots`: 배열 순서대로 이동 요청을 전송한다. 원자적인 동시 출발은 아니다.
- `start`, `goal`: 현재 `test.geojson`의 노드 ID. 시작 노드끼리는 중복할 수 없다.
- `goal: null`: 해당 로봇에 목적지 명령을 보내지 않는다. 기존 양보 알고리즘의 적용 대상은 될 수 있다.
- `base_url`: CLI가 접속할 서버 주소. 웹은 기존 프런트엔드 API 설정을 사용한다.
- `timeout_seconds`: 모드별 실행 제한 시간. 기존 단일 숫자에서 모드별 값으로 변경했다.

목록 조회와 실행 요청 때마다 파일을 읽는다. JSON 변경 후 웹 새로고침 또는
콤보박스 포커스로 목록을 다시 읽을 수 있다. 진행 중 실행에는 접수 당시 설정을 사용한다.
현재 연결된 로봇은 모두 JSON에 포함해야 하며, 지정한 로봇은 모두 연결되어 있어야 한다.
노드 존재·방향별 도달 가능 경로·서버 그래프와 `test.geojson`의 일치를 검사한다.
그래프 변경 시 코드의 노드 목록을 고칠 필요 없이 이 JSON을 조정한다.

## 실행 중 처리

- 백엔드가 시작 시 모드를 고정하고 중복 실행, 모드 전환, 대상 로봇에 대한 새 이동·충전·복귀·주문·비영속도 수동 명령을 거부한다.
- 프런트엔드도 관련 조작을 비활성화한다. 비상정지는 허용하며 시뮬레이션 전체 정지도 연결했다.
- 일부 명령 전송 실패, 위치/연결 상실, PAUSED/비상정지, 제한 시간 초과 시 실패로 판정하고 참여 로봇에 기존 정지 함수를 호출한다.
- 정지 요청 실패는 메시지에 표시한다. 실물 정지에는 기존 비상정지 동작이 적용되며 자동 해제하지 않는다. 실패 표시는 물리적 정지 완료의 보증이 아니다.
- 상태는 현재 서버 프로세스 메모리에서 관리한다. 기본 단일 worker 실행을 전제로 하며 서버 재시작 후 이전 실행 이력은 유지하지 않는다.
- 시간 초과를 교착 확정으로 분류하지 않는다. 성공은 주행과 후속 동작 완료를 뜻하며 병목의 발생이나 최소 거리 준수를 보증하지 않는다.

앞서 논의한 차체 크기 기반 최소 거리 적용은 이번 UI/실행 연결 범위에 포함하지 않았다.
`cycle`의 근접 현상과 경로 예약 알고리즘은 별도로 개선해야 한다.

## 구현 위치

| 파일 | 함수/구성 요소 | 역할 |
| --- | --- | --- |
| `frontend/src/components/ScenarioControls.tsx` | `ScenarioControls` | 설명 콤보박스, 단일 실행, 상태/오류 표시 |
| `frontend/src/FmsControlApp.tsx` | `FmsControlApp`, `RobotPanel` | 지도 도구 오른쪽 배치, 실행 중 기존 조작 제한 |
| `frontend/src/api/fmsApi.ts` | `getScenarios`, `runScenario`, `getScenarioStatus` | 웹 API 연결 |
| `backend/app/routers/scenarios.py` | `list_scenarios`, `run_scenario`, `scenario_status` | 목록 GET, 실행 POST, 상태 GET |
| `backend/app/services/scenario_service.py` | `ScenarioManager.start`, `_run`, `robot_states` | 검증, 단일 실행·완료/실패 관리, 모드별 상태 확인 |
| `backend/app/services/command_service.py` | `navigate_to_node`, `stop_robot` | 기존 모드별 명령 재사용 |
| `simulation/scenarios.py` | `placement`, `prepare` | 기존 Mock 초기 배치 로직 이동 |
| `backend/app/ros2/ros_gateway.py` | `on_aruco_align_result` | 주문 없는 이동 완료, 비상정지 후 늦은 정렬 결과 무시 |
| `tests/traffic_scenarios.py` | `main` | 같은 실행 API를 사용하는 필수 이름 CLI |

공통 실행부는 Mock을 상위에서 import하지 않는다. 시뮬레이션 준비는 해당 분기에서만
`simulation.scenarios`를 로드한다. 시뮬레이션 제거 시 이 분기와 Mock 상태/명령 분기를
제거하면 실제 상태 확인·실행·UI·CLI는 유지할 수 있다. 테스트 JSON은 공통 데이터로 남긴다.

## 검증

```bash
source robots_ws/Logistics_AMR/install/setup.bash
source ~/venv/robot/bin/activate
python -m unittest discover -s tests -v
python -m unittest discover -s backend/tests -v
npm run typecheck --prefix frontend
npm run build --prefix frontend
```

위 명령은 저장소에 남아 있는 기존 테스트와 프런트엔드 검사를 실행한다.
이번 기능 검증용으로 추가했던 서비스/API 테스트 파일과 ArUco 검증 항목은 제거했다.
