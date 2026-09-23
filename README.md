# Logistics_FMS

물류센터의 여러 로봇을 지도에서 확인하고 이동·수동 제어 화면을 개발하기 위한 Fleet Management System(FMS) 프로젝트입니다. 이 저장소에는 **FastAPI 백엔드**, **React/Vite 대시보드**, 지도와 경로 데이터, ROS 2·Zenoh 실행 스크립트가 있습니다.

> 현재 백엔드 API는 메모리의 모의 로봇 데이터를 반환합니다. `real`/`simulation` 모드를 바꿀 수 있지만, 모드를 `real`로 바꾸는 것만으로 실제 로봇 텔레메트리나 명령 전송이 연결되지는 않습니다. 실장비 운용 전에는 ROS 2/Zenoh 통합을 별도로 검증해야 합니다.

## 구조

```text
maps/ · routes/ ──→ FastAPI API ──→ React 대시보드
                         ↑                  ↕
                  메모리 모의 로봇       HTTP / WebSocket

ROS 2 로봇 ↔ zenoh-bridge-ros2dds ↔ Zenoh Router  (통합 준비용 프로세스)
```

| 경로 | 역할 |
| --- | --- |
| `backend/app/` | 지도·경로·로봇·명령 API, WebSocket, 모의 데이터 |
| `frontend/` | React 대시보드와 Vite 개발 서버 |
| `maps/`, `routes/` | Occupancy Map과 GeoJSON 경로 그래프 |
| `robots_ws/` | ROS 2 로봇 작업 공간 |
| `infra/docker-compose.yml` | 개발용 Zenoh Router 컨테이너 |
| `scripts/main/`, `scripts/robot/` | Main PC·로봇용 Zenoh 설치와 셸 설정 예시 |
| `doc/ros2-zenoh-guide.md` | ROS 2/Zenoh 네트워크 설정과 운영 절차의 상세 참고 문서 |
| `doc/backend-control-customization-guide.md` | 백엔드 제어 화면의 세부 변경 안내 |
| `start_fms.sh`, `stop_fms.sh` | 개발 스택 시작과 종료 |
| `tools/diagnostics/zenoh_monitor.py` | 로컬 Zenoh 메시지 수신을 확인하는 진단 도구 |

프런트엔드는 `backend/app/services/mock_data.py`의 데이터를 사용합니다. 지도·경로·로봇 조회 및 명령 API 계약을 확인할 수 있지만, 화면 표시를 실제 로봇 연결 확인으로 해석하지 마세요.

## 지원 환경과 설치

`scripts/setup.sh`는 **Ubuntu 24.04**의 x86_64 PC 또는 aarch64/Jetson 환경을 대상으로 합니다. ROS 2 Jazzy, Docker Compose, Node.js 20.20.2, `~/venv/robot` Python 가상환경, 백엔드·프런트엔드 의존성과 Main PC용 Zenoh 패키지를 설치합니다. 처음 실행에는 인터넷과 `sudo` 권한이 필요하며 시스템 패키지도 변경합니다.

```bash
cd ~
git clone <저장소 URL> Logistics_FMS
cd ~/Logistics_FMS
bash scripts/setup.sh
bash scripts/verify_env.sh
```

Docker 그룹에 새로 추가되었다면 로그아웃 후 다시 로그인해야 할 수 있습니다. 설치 스크립트는 `scripts/main/bashrc_main.conf`를 `~/.axbashrc`로 복사하고 `~/.bashrc`에서 읽도록 설정합니다. 새 터미널을 열거나 `source ~/.bashrc`를 실행한 뒤 ROS 설정을 확인하세요. 로봇 PC에는 역할에 맞는 `scripts/robot/install_robot.sh`와 `scripts/robot/bashrc_robot.conf`를 사용합니다.

`scripts/verify_env.sh`의 출력에서 OS, ROS 2, Python, Zenoh, Node.js, Docker, 프런트엔드 의존성과 네트워크 항목을 확인합니다. 기본 Node.js 20.20.2는 이 저장소의 Vite 8 요구 범위에 들어갑니다.

## 실행

설치가 끝난 Main PC에서 저장소 루트로 이동해 다음 명령을 사용합니다.

```bash
cd ~/Logistics_FMS
./start_fms.sh
```

이 스크립트는 다음 순서로 시작합니다.

1. Docker Compose의 Zenoh Router (`7447`)
2. 호스트의 ROS 2 daemon과 `zenoh-bridge-ros2dds`
3. FastAPI 백엔드 (`8000`)
4. Vite 프런트엔드 (`5173`)

브라우저에서 `http://127.0.0.1:5173`을 엽니다. 백엔드 상태는 `http://127.0.0.1:8000/health`, API 목록은 `http://127.0.0.1:8000/docs`에서 확인합니다. 시작 스크립트는 `logs/`에 `backend.log`, `frontend.log`, `zenoh_bridge.log`와 PID 파일을 기록합니다. 오류가 나면 해당 로그를 확인하세요.

```bash
./stop_fms.sh
```

종료 스크립트는 프런트엔드, 백엔드, Bridge, ROS daemon, Compose Router 순으로 중지합니다. `start_fms.sh`는 기존 실행 프로세스를 정리하고 시작하므로, 작업 중인 별도 ROS 2/Zenoh 프로세스가 있다면 실행 전에 스크립트를 확인하세요.

### 수동 실행

개별 프로세스를 확인하고 싶을 때는 터미널을 나누어 실행할 수 있습니다.

```bash
# 터미널 1: Router
docker compose -f infra/docker-compose.yml up -d zenoh-router

# 터미널 2: Backend
source ~/venv/robot/bin/activate
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# 터미널 3: Frontend
cd frontend
npm run dev -- --host 0.0.0.0
```

위 수동 실행 명령만으로 백엔드의 모의 데이터 화면을 확인할 수 있습니다. Bridge까지 확인할 때는 ROS 2 환경과 `zenoh-bridge-ros2dds`를 별도로 실행해야 합니다. `infra/docker-compose.yml`에는 PostgreSQL 컨테이너가 없습니다. 현재 백엔드도 DB를 사용하지 않습니다.

프런트엔드만 실행할 때는 `frontend/`에서 `npm run dev`를 사용합니다. 저장소의 `pnpm-lock.yaml` 기준으로 별도 설치하려면 `pnpm install --frozen-lockfile`과 `pnpm dev`도 사용할 수 있습니다. `frontend/start-dashboard.cmd`는 Windows에서 프런트엔드만 시작하는 도구입니다. 프런트엔드 검증 명령은 `pnpm typecheck`, `pnpm build`입니다.

## API와 화면 확인

| 항목 | 경로 |
| --- | --- |
| 상태 | `/health` |
| 로봇 목록 | `/api/robots` |
| 지도 정보·이미지 | `/api/map/info`, `/api/map/image` |
| 경로 그래프·노드 | `/api/route/graph`, `/api/route/nodes` |
| 이동·정지 명령 | `/api/command/goal`, `/api/command/goal-node`, `/api/command/stop` |
| WebSocket | `/ws/dashboard`, `/ws/cmd_vel` |

대시보드는 로봇·경로·작업·알람 화면을 제공합니다. 일부 상태와 명령 결과는 모의 동작입니다. 수동 키보드 제어는 로봇 선택, 관리자 모드, 원격제어 활성화 조건에서 동작합니다. `W`/`S`는 전후진, `Q`/`A`와 `E`/`D`는 회전, `Space`는 정지입니다.

## 실제 로봇과 Zenoh

Main PC는 `scripts/main/install_main.sh`, 로봇은 `scripts/robot/install_robot.sh`를 사용합니다. 설치 스크립트는 Zenoh APT 저장소를 등록하고 프로젝트에서 사용하는 버전을 설치합니다. `scripts/main/bashrc_main.conf`, `scripts/robot/bashrc_robot.conf`의 `ros_normal`/`ros_local` 설정과 ROS Domain ID를 장비별로 확인하세요.

`Unable to locate package zenoh-bridge-ros2dds`가 나오면 Zenoh 저장소 등록과 후보 버전을 확인합니다.

```bash
sudo mkdir -p /etc/apt/keyrings
curl -L https://download.eclipse.org/zenoh/debian-repo/zenoh-public-key \
  | sudo gpg --dearmor --yes --output /etc/apt/keyrings/zenoh-public-key.gpg
echo "deb [signed-by=/etc/apt/keyrings/zenoh-public-key.gpg] https://download.eclipse.org/zenoh/debian-repo/ /" \
  | sudo tee /etc/apt/sources.list.d/zenoh.list
sudo apt update
apt-cache policy zenoh-bridge-ros2dds
```

원하는 버전이 보일 때 설치하세요. Main PC/로봇의 Bridge 연결 주소와 ROS 네트워크 설정은 현장 IP에 맞춰 검증해야 합니다. [Zenoh 공식 설치 문서](https://zenoh.io/docs/getting-started/installation/)도 참고할 수 있습니다.

## 문제 해결

- **대시보드가 열리지 않음:** `logs/frontend.log`, Node.js 버전, 5173 포트 사용 여부를 확인합니다.
- **API가 응답하지 않음:** `logs/backend.log`와 `http://127.0.0.1:8000/health`를 확인합니다.
- **Bridge가 종료됨:** `logs/zenoh_bridge.log`, Zenoh 7447 포트, ROS 2 환경값을 확인합니다.
- **다른 PC에서 접속 불가:** `start_fms.sh`는 Vite를 `0.0.0.0`에 바인딩합니다. 방화벽과 5173·8000 포트를 확인합니다.
- **로봇이 모의 데이터로 보임:** 현재 백엔드가 실제 텔레메트리 대신 메모리 데이터를 사용하기 때문입니다. `real` 모드 표시는 실장비 연동 완료를 뜻하지 않습니다.

## 문서 범위

설치와 기본 실행의 기준은 이 README입니다. `doc/ros2-zenoh-guide.md`는 통신 설계와 상세 운영 절차, `doc/backend-control-customization-guide.md`는 세부 구현 설명입니다. 특정 시점의 Zenoh 장애 조사 기록은 프로젝트 밖의 운영 기록 보관소로 옮겼습니다. 실제 장비별 통신·설정은 현재 코드와 설치 스크립트를 함께 확인해야 합니다.
