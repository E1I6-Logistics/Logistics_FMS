# Logistics_FMS

물류센터의 TurtleBot 계열 AMR을 지도에서 관제하고 이동·정지·수동 제어하기 위한 Fleet Management System(FMS)입니다. FastAPI 백엔드, React/Vite 대시보드, ROS 2 Jazzy, Nav2, Zenoh 통신 계층, 모의 로봇 시뮬레이션과 LLM 경로 비교 도구로 구성되어 있습니다.

> **중요:** 현재 백엔드는 시작할 때 ROS 2 노드를 초기화하고 `turtlebot3_my_msg/action/PrecisionDock` 인터페이스를 import합니다. 시뮬레이션 모드만 사용할 때도 `robots_ws`에 [Logistics_AMR](https://github.com/E1I6-Logistics/Logistics_AMR.git)의 `jhleedev00` 브랜치를 clone하고 빌드해야 합니다. 자세한 절차는 [TurtleBot 인터페이스 준비](#2-turtlebot-인터페이스-준비필수)를 참고하세요.

## 주요 기능

- Occupancy Grid Map(PGM/YAML)과 GeoJSON 경로 그래프 표시
- `simulation` / `real` 운용 모드 전환
- 로봇 연결 상태, AMCL 위치, 방향, 배터리, 경로와 작업 상태 표시
- 방향성 경로 그래프 기반 A* 경로 계산과 노드 목적지 이동
- WebSocket 기반 대시보드 텔레메트리와 키보드 수동 주행
- Nav2 `FollowWaypoints`, `Spin` 및 커스텀 `PrecisionDock` 액션 연동
- Zenoh Router와 `zenoh-bridge-ros2dds`를 통한 Main PC·로봇 간 ROS 2 연결
- Mock Fleet를 이용한 로봇 3대 시뮬레이션
- Ollama/OpenAI/Anthropic 기반 선택적 LLM 경로 비교 및 평가

## 현재 개발 현황

아래 내용은 현재 저장소의 코드를 기준으로 정리한 구현 상태입니다.

| 영역 | 현재 상태 |
| --- | --- |
| 대시보드 | 로봇 목록·상태, 지도·경로 그래프, 목표 노드 선택, 모드 전환, 전체 정지 UI, 키보드 원격 제어 구현 |
| 시뮬레이션 | `robot1`~`robot3` 모의 텔레메트리, 노드/좌표 이동, 정지, `cmd_vel`, 약 10 Hz 위치 갱신 구현 |
| 실제 로봇 검색 | Zenoh Router REST API(`8001`)의 세션과 ROS 2 route를 조회해 연결된 `robotN`을 동적으로 등록 |
| 실제 텔레메트리 | `/{robot_id}/amcl_pose`, `/{robot_id}/battery_state`를 구독해 위치·방향·배터리 갱신 |
| 실제 수동 제어 | `/{robot_id}/cmd_vel`에 `geometry_msgs/msg/TwistStamped` 발행 |
| 실제 경로 주행 | 현재 위치에서 가장 가까운 그래프 노드를 찾고 A* 경로를 계산한 뒤 `/{robot_id}/follow_waypoints` 액션 전송 |
| 도착 후 동작 | 목적지별 목표 각도로 `/{robot_id}/spin` 실행. 노드 `0`, `1`, `2` 도착 시 `/{robot_id}/precision_dock` 실행 |
| 가장 가까운 노드 복귀 | 실제 모드용 `/api/command/return-nearest-node` API 구현 |
| LLM 경로 비교 | 코드 경로와 LLM 제안 경로의 유효성·거리·응답 시간을 비교하고 JSONL/요약 파일로 기록 |

### 현재 구현상 유의점

- 실제 ROS 2 명령으로 연결된 경로는 현재 **노드 이동(`/api/command/goal-node`)**과 **WebSocket 수동 제어(`/ws/cmd_vel`)**입니다.
- 좌표 이동(`/api/command/goal`)과 REST 정지(`/api/command/stop`)는 현재 코드에서 모드와 무관하게 Mock Fleet를 처리합니다. 따라서 화면의 전체/개별 정지 버튼을 실제 장비의 비상정지 수단으로 사용하면 안 됩니다.
- 실시간 운용 전에는 로봇별 namespace, Zenoh 연결, Nav2 Action Server, AMCL, 배터리 토픽과 정밀 도킹 서버를 현장에서 반드시 검증해야 합니다.
- 운용 모드는 프로세스 메모리에만 유지되며 기본값은 `simulation`입니다.

## 시스템 구성

```text
React/Vite Dashboard (:5173)
       │ HTTP / WebSocket
       ▼
FastAPI Backend (:8000)
       ├── Map(PGM/YAML) + Route Graph(GeoJSON)
       ├── Mock Fleet (simulation mode)
       └── FMS ROS 2 Node (real mode)
                │ ROS 2 topics/actions
                ▼
       Local zenoh-bridge-ros2dds
                │
                ▼
       Zenoh Router (:7447, REST :8001)
                │
                ▼
       Robot zenoh-bridge-ros2dds ↔ TurtleBot/Nav2
```

## 폴더 구조

빌드 산출물과 의존성 디렉터리는 생략했습니다.

```text
Logistics_FMS/
├── backend/
│   ├── app/
│   │   ├── models/              # 실제 로봇 상태 모델
│   │   ├── ros2/                # ROS 2 Node와 FastAPI-ROS Gateway
│   │   ├── routers/             # Map, Robot, Mode, Command, WebSocket API
│   │   ├── schemas/             # API 요청 및 Robot ID 스키마
│   │   ├── services/            # Mock Fleet, A*, 지도, 그래프, Zenoh 연결 관리
│   │   ├── config.py            # 지도·그래프·모드·CORS 환경 설정
│   │   └── main.py              # FastAPI 앱과 ROS 2 executor 수명주기
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── api/                 # REST/WebSocket 클라이언트
│   │   ├── constants/           # UI 데이터와 테마
│   │   ├── hooks/               # Fleet, Route, cmd_vel 상태 관리
│   │   ├── FmsControlApp.tsx    # 통합 관제 화면
│   │   └── WarehouseMap.tsx     # 지도·노드·경로·로봇 렌더링
│   ├── package.json
│   └── vite.config.ts
├── robots_ws/                   # 백엔드가 source하는 ROS 2 workspace
│   ├── src/
│   │   └── Logistics_AMR/       # 별도 clone: jhleedev00 브랜치
│   ├── build/                   # colcon 생성(커밋 대상 아님)
│   ├── install/                 # colcon 생성, start_fms.sh가 source
│   └── log/                     # colcon 생성
├── maps/                        # PGM/PNG/YAML Occupancy Map
├── routes/                      # GeoJSON 경로 그래프와 비교용 그래프
├── simulation/
│   ├── evaluation/              # 비교 CLI, 평가와 집계
│   ├── llm_providers/           # Ollama/OpenAI/Anthropic provider
│   ├── route_selector/          # 경로 선택기
│   ├── services/                # 비교용 경로 서비스
│   └── simulators/              # Mock Fleet/Robot 실행기
├── tests/                       # 경로·LLM 비교 단위 테스트와 fixture
├── scripts/
│   ├── main/                    # Main PC Zenoh 설치·셸 설정
│   ├── robot/                   # Robot PC Zenoh 설치·셸 설정
│   ├── setup.sh                 # Ubuntu 개발 환경 일괄 설치
│   └── verify_env.sh            # 환경 점검
├── infra/docker-compose.yml     # Zenoh Router 컨테이너
├── tools/diagnostics/           # Zenoh 진단 도구
├── doc/                         # ROS 2/Zenoh 및 백엔드 제어 문서
├── logs/                        # 실행 로그와 PID 파일
├── start_fms.sh                 # 전체 개발 스택 시작
└── stop_fms.sh                  # 전체 개발 스택 종료
```

## 설치

### 1. 기본 환경 설치

지원 기준은 Ubuntu 24.04(x86_64 또는 aarch64/Jetson), ROS 2 Jazzy입니다. 설치 스크립트는 ROS 2/Nav2, Docker Compose, Node.js 20.20.2, `~/venv/robot` Python 가상환경, 백엔드·프런트엔드 의존성과 Zenoh 패키지를 설치합니다. 인터넷 연결과 `sudo` 권한이 필요하며 시스템 패키지를 변경합니다.

```bash
cd ~
git clone <Logistics_FMS 저장소 URL> Logistics_FMS
cd ~/Logistics_FMS
bash scripts/setup.sh
```

Docker 그룹에 처음 추가된 경우 로그아웃 후 다시 로그인해야 Docker를 `sudo` 없이 사용할 수 있습니다. 설치가 끝나면 새 터미널을 열거나 다음 명령으로 셸 환경을 적용합니다.

```bash
source ~/.bashrc
```

### 2. TurtleBot 인터페이스 준비(필수)

백엔드의 `FmsRosNode`는 Logistics_AMR 저장소에 있는 커스텀 TurtleBot 메시지·액션 인터페이스를 사용합니다. 프로젝트의 실제 workspace 이름은 `robots_ws`이며, 소스는 그 안의 `src`에 clone합니다.

```bash
cd ~/Logistics_FMS
mkdir -p robots_ws/
cd robots_ws/

git clone https://github.com/E1I6-Logistics/Logistics_AMR.git
cd Logistics_AMR
git switch jhleedev00
```

이어서 ROS 의존성을 설치하고 workspace 전체를 빌드합니다.

```bash
cd ~/Logistics_FMS/robots_ws/Logistics_AMR/
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

이미 `Logistics_AMR` 디렉터리가 있다면 새로 clone하지 말고 다음과 같이 브랜치를 맞춘 뒤 다시 빌드합니다.

```bash
cd ~/Logistics_FMS/robots_ws/Logistics_AMR/
git fetch origin
git switch jhleedev00
git pull --ff-only origin jhleedev00

cd ~/Logistics_FMS/robots_ws/Logistics_AMR/
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

커스텀 액션 인터페이스가 보이는지 확인할 수 있습니다.

```bash
ros2 interface show turtlebot3_my_msg/action/PrecisionDock
```

> `start_fms.sh`는 `robots_ws/install/setup.bash`를 source하므로 반드시 프로젝트 루트에서 실행해야 합니다. AMR 저장소를 clone만 하고 빌드하지 않으면 백엔드가 `turtlebot3_my_msg`를 import하지 못합니다.

### 3. 환경 확인

```bash
cd ~/Logistics_FMS
bash scripts/verify_env.sh
```

OS, ROS 2, Python, Zenoh, Node.js, Docker, 프런트엔드 의존성과 네트워크 점검 결과를 확인합니다.

## 환경 설정

백엔드 설정 예시는 `backend/.env.example`에 있습니다. 현재 코드는 OS 환경변수를 직접 읽으므로 필요하면 실행 전에 export합니다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `FMS_ROBOT_MODE` | `simulation` | 시작 모드: `simulation` 또는 `real` |
| `FMS_MAP_YAML` | `my_map.yaml` | `maps/` 아래에서 사용할 지도 YAML |
| `FMS_ROUTE_GRAPH` | `test.geojson` | `routes/` 아래에서 사용할 GeoJSON 그래프 |
| `FMS_CORS_ORIGINS` | `*` | 쉼표로 구분한 허용 Origin |
| `VITE_FMS_API_BASE` | 현재 호스트의 `:8000` | 프런트엔드 API 주소 |
| `VITE_FMS_WS_BASE` | API 주소에서 자동 변환 | 프런트엔드 WebSocket 주소 |

예시:

```bash
export FMS_ROBOT_MODE=real
export FMS_MAP_YAML=my_map.yaml
export FMS_ROUTE_GRAPH=test.geojson
```

`start_fms.sh`는 포트, 가상환경, ROS setup과 Zenoh endpoint도 `FMS_BACKEND_PORT`, `FMS_FRONTEND_PORT`, `FMS_VENV_DIR`, `FMS_ROS_WS_SETUP`, `FMS_ZENOH_CONNECT_ENDPOINT` 등의 환경변수로 덮어쓸 수 있습니다.

## 실행과 종료

```bash
cd ~/Logistics_FMS
./start_fms.sh
```

시작 스크립트는 다음 순서로 실행합니다.

1. Docker Compose Zenoh Router(`7447`, REST `8001`)
2. 호스트 ROS 2 daemon과 `zenoh-bridge-ros2dds`
3. FastAPI 백엔드(`8000`)
4. Vite 프런트엔드(`5173`)

| 항목 | 주소 |
| --- | --- |
| 대시보드 | `http://127.0.0.1:5173` |
| 백엔드 상태 | `http://127.0.0.1:8000/health` |
| Swagger API 문서 | `http://127.0.0.1:8000/docs` |
| Zenoh REST | `http://127.0.0.1:8001` |

로그는 `logs/backend.log`, `logs/frontend.log`, `logs/zenoh_bridge.log`에 기록됩니다.

```bash
cd ~/Logistics_FMS
./stop_fms.sh
```

`start_fms.sh`는 기본적으로 기존 FMS 프로세스를 정리한 후 시작합니다. 별도로 실행 중인 ROS 2 daemon이나 Zenoh Bridge가 있다면 충돌하지 않는지 먼저 확인하세요.

### 수동 실행

개별 프로세스를 확인할 때는 터미널을 나누어 실행합니다.

```bash
# 터미널 1: Zenoh Router
cd ~/Logistics_FMS
docker compose -f infra/docker-compose.yml up -d zenoh-router

# 터미널 2: Backend
cd ~/Logistics_FMS
source /opt/ros/jazzy/setup.bash
source robots_ws/install/setup.bash
source ~/venv/robot/bin/activate
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# 터미널 3: Frontend
cd ~/Logistics_FMS/frontend
npm run dev -- --host 0.0.0.0
```

실제 로봇 연결을 확인할 때는 Zenoh Router에 연결하는 호스트·로봇 측 `zenoh-bridge-ros2dds`도 실행해야 합니다.

## API 및 ROS 2 인터페이스

### 주요 API

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| `GET` | `/health` | 백엔드 상태와 현재 모드 |
| `GET`, `PUT` | `/api/mode` | 운용 모드 조회·전환 |
| `GET` | `/api/connections` | Mock 또는 Zenoh 기반 연결 목록 |
| `GET` | `/api/robots` | 로봇 상태 목록 |
| `GET` | `/api/map/info`, `/api/map/image` | 지도 메타데이터·이미지 |
| `GET` | `/api/route/graph`, `/api/route/nodes` | 경로 그래프·노드 |
| `POST` | `/api/command/goal-node` | 노드 목적지 이동 |
| `POST` | `/api/command/goal` | 좌표 목적지 이동(현재 Mock 처리) |
| `POST` | `/api/command/stop` | 정지(현재 Mock 처리) |
| `POST` | `/api/command/return-nearest-node` | 실제 로봇의 가장 가까운 노드 복귀 |
| `WS` | `/ws/dashboard` | 모드·텔레메트리 전송 |
| `WS` | `/ws/cmd_vel` | 수동 속도 명령과 ACK |

### 로봇별 ROS 2 인터페이스

| 종류 | 이름 | 타입 |
| --- | --- | --- |
| Publisher | `/{robot_id}/cmd_vel` | `geometry_msgs/msg/TwistStamped` |
| Subscription | `/{robot_id}/amcl_pose` | `geometry_msgs/msg/PoseWithCovarianceStamped` |
| Subscription | `/{robot_id}/battery_state` | `sensor_msgs/msg/BatteryState` |
| Action Client | `/{robot_id}/follow_waypoints` | `nav2_msgs/action/FollowWaypoints` |
| Action Client | `/{robot_id}/spin` | `nav2_msgs/action/Spin` |
| Action Client | `/{robot_id}/precision_dock` | `turtlebot3_my_msg/action/PrecisionDock` |

로봇 ID는 백엔드에서 `robot1`, `robot2`, `robot3` 형식을 사용하고 UI에서는 `R-01`, `R-02`, `R-03`으로 표시합니다.

## 대시보드 조작

1. 상단에서 실제 로봇 또는 시뮬레이션 모드를 선택합니다.
2. 왼쪽 로봇 목록에서 제어할 로봇을 선택합니다.
3. 지도 또는 제어 패널에서 목적지 노드를 선택하고 이동 명령을 보냅니다.
4. 연결된 로봇은 원격 제어 패널이나 키보드로 조작할 수 있습니다.

| 키 | 동작 |
| --- | --- |
| `W` / `S` | 전진 / 후진 |
| `Q` 또는 `A` | 좌회전 |
| `E` 또는 `D` | 우회전 |
| `Space` | 속도 0 전송 |

키를 누르는 동안 약 10 Hz로 속도 명령을 재전송하며, 창 포커스를 잃거나 원격 제어가 끝나면 정지 명령을 보냅니다.

## LLM 경로 비교

LLM 기능은 코드로 계산한 최단 경로와 모델이 제안한 경로를 비교하는 평가 도구입니다. 실제 로봇의 주행 경로를 LLM 결과로 대체하지 않습니다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m pip install -r simulation/requirements.txt
test -f simulation/.env || cp simulation/.env.example simulation/.env

python -m simulation.evaluation.cli build-compact
python -m simulation.evaluation.cli compare --start 2 --goal 6 --dry-run
python -m simulation.evaluation.cli compare --start 2 --goal 6
```

`simulation/.env`에서 `LLM_PROVIDER`, provider별 모델·인증 정보, `LLM_ROUTE_GRAPH`를 설정합니다. Ollama를 사용할 때는 서버와 모델을 먼저 준비합니다.

```bash
ollama serve
ollama pull qwen3:4b
```

비교 결과는 `simulation/llm_route_comparisons.jsonl`, 집계 결과는 `simulation/llm_route_summary.json`에 기록되며 두 파일은 Git에서 제외됩니다.

## 검증

```bash
# Python 단위 테스트
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m unittest discover -s tests -v

# Frontend 타입 검사와 프로덕션 빌드
cd ~/Logistics_FMS/frontend
npm run typecheck
npm run build
```

실제 장비 연동은 추가로 다음 항목을 확인합니다.

```bash
ros2 topic list
ros2 action list
curl http://127.0.0.1:8001/@/local/router
curl http://127.0.0.1:8000/api/connections
```

## 문제 해결

- **`ModuleNotFoundError: turtlebot3_my_msg`**: Logistics_AMR의 `jhleedev00` 브랜치인지 확인하고 `robots_ws`를 다시 빌드한 뒤 `source robots_ws/install/setup.bash`를 실행합니다.
- **`robots_ws/install/setup.bash`를 찾지 못함**: AMR 소스를 clone만 하고 `colcon build --symlink-install`을 실행하지 않은 상태입니다.
- **대시보드가 열리지 않음**: `logs/frontend.log`, Node.js 버전과 5173 포트 사용 여부를 확인합니다.
- **API가 응답하지 않음**: `logs/backend.log`, ROS 2 인터페이스 import와 `http://127.0.0.1:8000/health`를 확인합니다.
- **로봇이 실제 모드에서 나타나지 않음**: Zenoh REST `8001`, Main/Robot Bridge 연결, robot namespace와 `/api/connections` 응답을 확인합니다.
- **Nav2 이동 명령 실패**: AMCL 위치 수신 여부와 `/{robot_id}/follow_waypoints` Action Server를 확인합니다.
- **Bridge가 바로 종료됨**: `logs/zenoh_bridge.log`, 7447 포트, ROS Domain ID와 RMW 설정을 확인합니다.
- **다른 PC에서 접속 불가**: 방화벽과 5173·8000 포트를 확인합니다. 시작 스크립트는 프런트엔드와 백엔드를 `0.0.0.0`에 바인딩합니다.

## 관련 문서

- `doc/ros2-zenoh-guide.md`: ROS 2/Zenoh 네트워크 구성과 운영 절차
- `doc/backend-control-customization-guide.md`: 백엔드 제어 기능 변경 가이드
- [Logistics_AMR](https://github.com/E1I6-Logistics/Logistics_AMR.git): TurtleBot, Nav2, Zenoh, 커스텀 메시지·액션 소스
