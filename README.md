# Logistics_FMS

물류센터 환경에서 다중 로봇을 관리하기 위한 FMS(Fleet Management System) 프로젝트입니다.

ROS 2 Jazzy / Nav2 기반 로봇과 Zenoh를 이용해 통신하며, FastAPI Backend와 React Frontend를 통해 로봇의 위치 및 상태를 확인하고 제어합니다.

---

# 1. 개발 환경

본 프로젝트는 다음 환경을 기준으로 구성되어 있습니다.

| 항목 | 환경 |
|---|---|
| OS | Ubuntu 24.04 LTS |
| ROS 2 | Jazzy |
| Navigation | Nav2 |
| Python | Python 3.12 |
| Node.js | Node.js 20 |
| Frontend | React + Vite |
| Backend | FastAPI |
| 통신 | Zenoh |
| Database | PostgreSQL |
| Container | Docker / Docker Compose |

> Ubuntu 24.04 환경 사용을 권장합니다.

---

# 2. 프로젝트 구조

```text
Logistics_FMS/
├── backend/
│   ├── app/
│   │   ├── database/
│   │   │   └── database.py
│   │   └── main.py
│   └── requirements.txt
│
├── frontend/
│   ├── public/
│   ├── src/
│   ├── package.json
│   └── package-lock.json
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
│   ├── common/
│   ├── robot1/
│   └── robot2/
│
├── simulation/
│   ├── mock_fleet.py
│   ├── mock_robot.py
│   └── test_stack.py
│
├── doc/
│
├── setup.sh
├── verify_env.sh
├── .env.example
└── README.md
```

각 폴더의 역할은 다음과 같습니다.

| 폴더 | 역할 |
|---|---|
| `backend/` | FastAPI 기반 FMS Backend |
| `frontend/` | React/Vite 기반 FMS Web UI |
| `infra/` | Zenoh / PostgreSQL Docker 환경 |
| `maps/` | ROS Occupancy Map |
| `routes/` | Nav2 Route Server용 Route Graph |
| `robots/` | 실제 로봇용 ROS 2 코드 |
| `simulation/` | Mock Robot / Fleet 테스트 |
| `doc/` | 프로젝트 문서 |

---

# 3. 프로젝트 Clone

터미널을 실행합니다.

Git이 설치되어 있지 않은 경우:

```bash
sudo apt update
sudo apt install -y git
```

프로젝트를 Clone 합니다.

```bash
cd ~
git clone <GITHUB_REPOSITORY_URL>
```

프로젝트 폴더로 이동합니다.

```bash
cd ~/Logistics_FMS
```

---

# 4. 개발 환경 자동 설치

프로젝트에는 개발 환경을 자동으로 구성하기 위한 `setup.sh`가 포함되어 있습니다.

실행 권한을 부여합니다.

```bash
chmod +x setup.sh verify_env.sh
```

설치를 시작합니다.

```bash
./setup.sh
```

`setup.sh`를 통해 프로젝트 실행에 필요한 환경을 설치합니다.

주요 설치 대상:

```text
Ubuntu 개발 패키지
        │
        ├── ROS 2 Jazzy
        ├── Nav2
        ├── robot_localization
        ├── RViz2
        ├── tf2
        │
        ├── Docker
        ├── Docker Compose
        │
        ├── Node.js
        ├── npm
        │
        ├── Python Virtual Environment
        └── Python Dependencies
```

Python 가상환경은 다음 위치에 생성됩니다.

```text
~/venv/robot
```

---

# 5. Docker 권한 적용

처음 설치한 PC에서는 `setup.sh` 실행 후 Docker 그룹 권한 적용을 위해

**로그아웃 후 다시 로그인해야 할 수 있습니다.**

로그인 후 프로젝트 폴더로 다시 이동합니다.

```bash
cd ~/Logistics_FMS
```

Docker가 정상적으로 동작하는지 확인합니다.

```bash
docker --version
docker compose version
```

---

# 6. 설치 환경 검증

프로젝트에서 제공하는 검증 스크립트를 실행합니다.

```bash
cd ~/Logistics_FMS
./verify_env.sh
```

다음 환경들이 정상적으로 확인되어야 합니다.

```text
ROS 2 Jazzy
Nav2
Python
Python Virtual Environment
FastAPI
Zenoh
Node.js
npm
Docker
Docker Compose
Frontend node_modules
```

오류가 없다면 프로젝트 실행 환경 구성이 완료된 것입니다.

---

# 7. 프로젝트 실행

프로젝트는 여러 프로그램이 동시에 실행되어야 하므로 터미널을 여러 개 사용합니다.

기본 실행 순서는 다음과 같습니다.

```text
① Docker
   │
   ├── Zenoh Router
   └── PostgreSQL
          │
          ▼
② Backend
          │
          ▼
③ Frontend
          │
          ▼
④ Mock Robot 또는 실제 Robot
```

---

# 8. Docker 인프라 실행

### Terminal 1

```bash
cd ~/Logistics_FMS

docker compose -f infra/docker-compose.yml up -d
```

실행 상태를 확인합니다.

```bash
docker ps
```

다음 컨테이너가 실행되어야 합니다.

```text
fms-zenoh-router
fms-postgres
```

현재 구성에서 기본적으로 사용하는 포트는 다음과 같습니다.

| 서비스 | Port |
|---|---:|
| Zenoh | 7447 |
| PostgreSQL | 5432 |
| Backend | 8000 |
| Frontend | 5173 |

---

# 9. Backend 실행

### Terminal 2

프로젝트 루트로 이동합니다.

```bash
cd ~/Logistics_FMS
```

Python 가상환경을 활성화합니다.

```bash
source ~/venv/robot/bin/activate
```

ROS 2 환경도 적용합니다.

```bash
source /opt/ros/jazzy/setup.bash
```

Backend를 실행합니다.

```bash
uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

정상적으로 실행되면 Backend가 다음 주소에서 동작합니다.

```text
http://localhost:8000
```

FastAPI 문서는 다음 주소에서 확인할 수 있습니다.

```text
http://localhost:8000/docs
```

---

# 10. Frontend 실행

### Terminal 3

```bash
cd ~/Logistics_FMS/frontend
```

Frontend를 실행합니다.

```bash
npm run dev -- --host
```

터미널에 표시되는 주소로 접속합니다.

일반적으로 로컬 PC에서는:

```text
http://localhost:5173
```

으로 접속할 수 있습니다.

같은 네트워크의 다른 PC에서 접속할 경우:

```text
http://<FMS_PC_IP>:5173
```

형태로 접속합니다.

---

# 11. Mock Fleet 실행

실제 로봇 없이 FMS를 테스트하려면 Mock Fleet을 실행합니다.

### Terminal 4

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
source /opt/ros/jazzy/setup.bash
```

실행:

```bash
python simulation/mock_fleet.py
```

정상적으로 연결되면:

```text
Mock Fleet
    │
    │ Robot Telemetry
    ▼
Zenoh Router
    │
    ▼
FastAPI Backend
    │
    ├── REST API
    └── WebSocket
           │
           ▼
      React Frontend
           │
           ▼
   FMS Dashboard
```

구조로 데이터가 전달됩니다.

Frontend에서 로봇 위치와 상태가 표시되는지 확인합니다.

---

# 12. 실제 Robot 실행

실제 로봇을 사용할 경우 Mock Fleet 대신 `robots/`의 로봇 프로그램을 실행합니다.

## Robot 1

```bash
cd ~/Logistics_FMS

source /opt/ros/jazzy/setup.bash
source ~/venv/robot/bin/activate

python robots/robot1/robot_node.py
```

## Robot 2

다른 터미널에서:

```bash
cd ~/Logistics_FMS

source /opt/ros/jazzy/setup.bash
source ~/venv/robot/bin/activate

python robots/robot2/robot_node.py
```

각 로봇의 설정은 다음 파일에서 관리합니다.

```text
robots/robot1/config.json
robots/robot2/config.json
```

> 실제 로봇과 Mock Robot이 동일한 Robot ID 또는 통신 경로를 사용할 경우 충돌할 수 있으므로 실제 로봇 사용 시 Mock Fleet은 종료하는 것을 권장합니다.

---

# 13. 전체 실행 요약

PC를 재부팅한 뒤 프로젝트를 다시 실행할 때는 환경을 다시 설치할 필요가 없습니다.

## Terminal 1 - Infrastructure

```bash
cd ~/Logistics_FMS

docker compose -f infra/docker-compose.yml up -d
```

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

## Terminal 3 - Frontend

```bash
cd ~/Logistics_FMS/frontend

npm run dev -- --host
```

## Terminal 4 - Simulation

```bash
cd ~/Logistics_FMS

source ~/venv/robot/bin/activate
source /opt/ros/jazzy/setup.bash

python simulation/mock_fleet.py
```

---

# 14. 종료 방법

Backend / Frontend / Robot 프로그램은 실행 중인 터미널에서

```text
Ctrl + C
```

를 눌러 종료합니다.

Docker 컨테이너를 종료하려면:

```bash
cd ~/Logistics_FMS

docker compose -f infra/docker-compose.yml down
```

현재 실행 상태만 확인하려면:

```bash
docker ps
```

---

# 15. 다시 실행할 때

`setup.sh`는 **최초 개발환경 구성용**입니다.

매번 실행할 필요가 없습니다.

PC 재부팅 후에는 아래 프로그램들만 다시 실행하면 됩니다.

```text
Docker Infrastructure
        ↓
Backend
        ↓
Frontend
        ↓
Mock Fleet 또는 실제 Robot
```

즉:

```bash
# Terminal 1
cd ~/Logistics_FMS
docker compose -f infra/docker-compose.yml up -d
```

```bash
# Terminal 2
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
source /opt/ros/jazzy/setup.bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
# Terminal 3
cd ~/Logistics_FMS/frontend
npm run dev -- --host
```

```bash
# Terminal 4
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
source /opt/ros/jazzy/setup.bash
python simulation/mock_fleet.py
```

---

# 16. 주요 파일

### Map

```text
maps/my_map.yaml
maps/my_map.pgm
maps/my_map.png
```

### Nav2 Route Graph

```text
routes/test.geojson
```

### Backend

```text
backend/app/main.py
backend/app/database/database.py
```

### Frontend

```text
frontend/src/App.jsx
```

### Robot

```text
robots/robot1/robot_node.py
robots/robot2/robot_node.py
```

### Simulation

```text
simulation/mock_fleet.py
simulation/mock_robot.py
```

### Infrastructure

```text
infra/docker-compose.yml
```

---

# 17. 설치 문제 확인

환경에 문제가 있다고 생각되면 먼저:

```bash
cd ~/Logistics_FMS
./verify_env.sh
```

를 실행합니다.

Docker 상태:

```bash
docker ps
```

ROS 2 확인:

```bash
source /opt/ros/jazzy/setup.bash

echo $ROS_DISTRO
ros2 pkg prefix nav2_bringup
ros2 pkg prefix nav2_route
```

Python 환경 확인:

```bash
source ~/venv/robot/bin/activate

which python
python --version
pip --version
```

Node.js 확인:

```bash
node --version
npm --version
```

---

# Logistics_FMS

```text
ROS 2 / Nav2 Robot
        │
        │
        ▼
      Zenoh
        │
        ▼
 ┌───────────────┐
 │  FMS Backend  │
 │    FastAPI    │
 └───────┬───────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
PostgreSQL  WebSocket
              │
              ▼
       ┌──────────────┐
       │ FMS Frontend │
       │ React / Vite │
       └──────────────┘
```