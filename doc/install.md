# install.sh 실행 결과 분석 및 구성 요소 상세 검증 명세서

본 문서는 최신 install.sh 스크립트를 실행했을 때 로컬 환경에 설치·생성되는 모든 시스템 구성 요소, 디렉터리 및 소스 코드의 역할과 단계별 검증 절차를 정리한 명세서입니다.

---

1. 생성되는 전체 파일 및 디렉터리 맵

스크립트 실행 완료 시 사용자의 홈 디렉터리(~) 하위에 다음 구조가 자동으로 완성됩니다.

~/
├── venv/
│   └── robot/                          # ROS 2 Jazzy 연동 Python 가상환경
│
└── Last_Project/
    ├── fms_infra/
    │   └── docker-compose.yml          # 인프라 정의 파일 (Zenoh Router + PostgreSQL 16)
    │
    ├── fms_server/
    │   ├── database.py                 # PostgreSQL 비동기 I/O (asyncpg) 및 스키마 관리
    │   ├── main.py                     # FastAPI 코어, Zenoh 브로커, WebSocket 브로드캐스터
    │   └── static/                     # 정적 웹 리소스 보관 경로
    │
    ├── fms_web/                        # React (Vite) 프론트엔드 프로젝트
    │   ├── package.json                # React 18, Vite 의존성 및 실행 스크립트 정의
    │   ├── vite.config.js              # 0.0.0.0 바인딩(외부 접속 허용) 설정
    │   ├── index.html                  # 싱글 페이지 애플리케이션(SPA) 루트 HTML
    │   ├── node_modules/               # 설치된 npm 라이브러리 모음
    │   └── src/
    │       ├── main.jsx                # React DOM 진입점
    │       └── App.jsx                 # 2D 캔버스 맵, 상태 카드, Goal 전송 메인 UI
    │
    ├── mock_robot.py                   # 단일 가상 로봇 (텔레메트리 발행 + Goal 수신)
    ├── mock_fleet.py                   # 3대 다중 로봇 군집 모의 시뮬레이터
    └── test_stack.py                   # 인프라(Zenoh 7447, DB 5432) 연결성 진단 도구

---

2. 각 구성 요소별 상세 역할 및 기능

2.1 시스템 패키지 및 인프라 레이어
* Node.js 20.x LTS & npm: Vite 빌드 및 React 프론트엔드 런타임 환경 제공.
* zenoh-bridge-ros2dds: 현장 로봇의 ROS 2 DDS 토픽을 Zenoh 프로토콜로 경량 변환해 주는 브리지 유틸리티.
* Docker Container - fms-zenoh-router (포트 7447):
  * eclipse/zenoh:latest 기반 컨테이너. TCP 7447번 포트를 개방하여 로봇과 서버 간 초저지연 데이터 통신을 중계하는 메시지 브로커.
* Docker Container - fms-postgres (포트 5432):
  * PostgreSQL 16-alpine 컨테이너. 로봇 상태 및 시계열 위치 기록을 영구 보존 (postgres_data 볼륨 마운트).

2.2 가상환경 및 백엔드 레이어 (~/venv/robot, fms_server/)
* ~/venv/robot: 
  * --system-site-packages 옵션으로 구성되어 Ubuntu 24.04 시스템의 ROS 2 Jazzy 바이너리(rclpy)와 충돌 없이 통신 라이브러리(eclipse-zenoh, fastapi, asyncpg 등)를 격리 실행.
* fms_server/database.py:
  * 서버 기동 시 robots(최신 상태) 및 telemetry_logs(시계열 위치 기록) 테이블 자동 생성.
  * asyncpg 비동기 커넥션 풀을 통해 초당 수십 건의 위치 데이터를 논블로킹으로 적재.
* fms_server/main.py:
  * Zenoh 리스너: */telemetry 토픽을 실시간 수신하여 DB 적재 및 화면 브로드캐스트.
  * WebSocket 서버 (/ws/dashboard): 수신한 텔레메트리를 브라우저 화면으로 밀리초 단위 즉각 브로드캐스트.
  * REST API (POST /api/command/goal): 웹 UI에서 지정한 목표 좌표를 해당 로봇의 {robot_id}/goal 토픽으로 하달.
  * CORS 미들웨어: React 개발 서버(5173)와의 크로스 오리진 통신 차단 방지.

2.3 프론트엔드 레이어 (fms_web/)
* fms_web/src/App.jsx:
  * 접속한 주소(window.location.hostname)를 기반으로 백엔드(8000)와 웹소켓 자동 페어링.
  * HTML5 Canvas를 이용해 1m 단위 그리드 맵과 로봇의 위치/헤딩 방향을 실시간 렌더링.
  * 각 로봇의 온라인 상태, 배터리 잔량 게이지, 수동 주행 목표(Nav2 Goal) 전송 인터페이스 제공.
* 설치 최적화:
  * install.sh 내에서 fms_web 경로로 직접 이동 후 npm install --prefer-offline --no-audit을 수행하여 네트워크 지연 및 설치 멈춤 현상 차단.

2.4 테스트 및 시뮬레이션 레이어
* test_stack.py: Docker 인프라(Zenoh 7447, DB 5432)가 정상 구동 중인지 즉각 확인하는 연결성 진단 스크립트.
* mock_robot.py: 1번 로봇이 반경 3m 원을 돌며 위치를 전송하고 웹에서 내린 주행 명령을 수신하는 양방향 검증기.
* mock_fleet.py: 3대(robot1, robot2, robot3)의 로봇이 서로 다른 궤적과 속도로 동시 주행하는 다중 군집 관제 모의 시뮬레이터.

---

3. 실행 결과 검증 단계 (정상 작동 확인법)

스크립트 실행 완료 후 아래 4단계를 순서대로 실행하여 전체 시스템이 올바르게 셋업되었는지 검증합니다.

1단계: 인프라 컨테이너 구동 상태 확인
터미널에서 Docker 컨테이너가 정상적으로 기동되었는지 확인합니다.

$ docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

정상 결과:
* fms-zenoh-router: Up ... 상태 확인
* fms-postgres: Up ... 및 0.0.0.0:5432->5432/tcp 매핑 확인

이어서 자가 진단 스크립트를 실행합니다:
$ source ~/venv/robot/bin/activate
$ python ~/Last_Project/test_stack.py

정상 결과 출력:
=== [시스템 인프라 진단 테스트] ===
1. Zenoh Router (7447): 정상 연결 완료 (ZID: ...)
2. PostgreSQL DB (5432): 정상 연결 완료

---

2단계: 서비스 구동 (터미널 3개 분할 실행)

[터미널 1] FastAPI 백엔드 기동
$ cd ~/Last_Project
$ source ~/venv/robot/bin/activate
$ uvicorn fms_server.main:app --host 0.0.0.0 --port 8000 --reload

* 정상 결과:
  * -> PostgreSQL FMS 테이블 초기화 완료! 로그 출력
  * -> FMS Zenoh 수신 세션 활성화 완료! 로그 출력
  * Uvicorn running on http://0.0.0.0:8000 표시

[터미널 2] React 프론트엔드 기동 (반드시 fms_web 디렉터리에서 실행)
$ cd ~/Last_Project/fms_web
$ npm run dev -- --host

* 정상 결과:
  * ➜ Local: http://localhost:5173/
  * ➜ Network: http://<본인IP>:5173/ 형태로 외부 노출 접속 주소 표기

[터미널 3] 군집 로봇 시뮬레이션 기동
$ cd ~/Last_Project
$ source ~/venv/robot/bin/activate
$ python3 mock_fleet.py

* 정상 결과:
  * -> 3대 로봇 군집 시뮬레이션 시작 (robot1, robot2, robot3) 로그 출력 유지

---

3단계: 화면 모니터링 및 실시간성 검증

1. PC 브라우저 또는 외부 디바이스에서 접속:
   * 주소: http://localhost:5173 (또는 네트워크 IP http://<호스트IP>:5173)
2. 검증 체크포인트:
   * 우측 상단 상태가 🟢 실시간 관제 연결됨으로 표시되는가?
   * 좌측 사이드바에 robot1, robot2, robot3 카드의 좌표와 배터리 수치가 실시간 갱신되는가?
   * 중앙 2D 지도 그리드 위에 3대의 로봇 마커가 서로 다른 반경과 속도로 주행 궤적을 그리는가?

---

4단계: 양방향 명령 하달 검증 (Command & Control)

1. 터미널 3의 mock_fleet.py를 종료(Ctrl + C)하고 단일 로봇 검증기를 실행합니다:
   $ python3 ~/Last_Project/mock_robot.py
2. 웹 브라우저 좌측 하단 제어창에서:
   * 로봇 ID: robot1
   * 목표 X: 4.5
   * 목표 Y: -1.5
   * [Nav2 목표 전송] 버튼 클릭
3. 정상 결과:
   * 브라우저 알림창에 [robot1] 주행 목표 전송 완료! (4.5, -1.5) 출력
   * mock_robot.py 콘솔 화면에 즉시 수신 로그 출력:
     [Robot1 Goal 수신] -> {"x": 4.5, "y": -1.5}

---

4. 네트워크 접속 포트 요약

* React 대시보드: 포트 5173 | 접속 주소: http://<호스트IP>:5173 | 설명: 현장 작업자/관리자용 2D 웹 인터페이스
* FastAPI 백엔드: 포트 8000 | 접속 주소: http://<호스트IP>:8000/docs | 설명: Swagger REST API 명세 및 WebSocket 엔드포인트
* Zenoh 라우터: 포트 7447 | 접속 주소: tcp/<호스트IP>:7447 | 설명: 현장 AMR 로봇 브리지 및 노드 연동 단자
* PostgreSQL: 포트 5432 | 접속 주소: localhost:5432 | 설명: 관제 데이터베이스 (DB: fms_db, User: fms_admin)
