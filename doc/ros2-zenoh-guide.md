# Logistics_FMS ROS 2 / Zenoh 환경 설정 및 실행 가이드

> **기준 환경**
>
> -   Ubuntu 24.04
> -   ROS 2 Jazzy
> -   Zenoh 1.9.0
> -   zenoh-bridge-ros2dds 1.9.0
> -   Zenoh 통신: CycloneDDS + LOCALHOST
> -   일반 ROS 2 통신: FastDDS + SUBNET

------------------------------------------------------------------------

## 1. 문서 목적

이 문서는 `Logistics_FMS` 프로젝트에서 사용하는 **Main PC와 TurtleBot
로봇의 ROS 2 / Zenoh 환경 설정 및 실행 방법**을 정리한다.

주요 목적은 다음과 같다.

-   Main PC / Robot의 ROS 2 환경 통일
-   Normal 모드와 Local/Zenoh 모드 구분
-   Zenoh Router 및 ROS2DDS Bridge 구성 명확화
-   Robot별 namespace 분리
-   FMS Backend / Frontend 실행 순서 정리
-   신규 장비 설정 및 장애 발생 시 확인 기준 제공

------------------------------------------------------------------------

## 2. 관련 파일

```text
Logistics_FMS/
├── README.md                         # 프로젝트 개요와 기본 설치·실행
├── start_fms.sh / stop_fms.sh        # 개발 스택 시작·종료
├── scripts/
│   ├── setup.sh / verify_env.sh      # 환경 설치·검증
│   ├── main/                         # Main PC 설정과 설치
│   └── robot/                        # 로봇 설정과 설치
├── doc/
│   ├── ros2-zenoh-guide.md           # 이 문서
│   └── backend-control-customization-guide.md
├── tools/diagnostics/zenoh_monitor.py
├── backend/ / frontend/ / infra/
└── maps/ / robots_ws/ / routes/ / simulation/
```

특정 시점의 장애 조사 기록은 프로젝트 밖에 보관한다. 현재 백엔드는 모의 데이터를 제공하므로 이 문서의 실장비 통신 절차는 장비 환경에서 별도로 확인해야 한다.

------------------------------------------------------------------------

# 3. ROS 2 네트워크 모드

## 3.1 전체 설정표

  ------------------------------------------------------------------------------------------
  장비        모드                Domain ID RMW                    Discovery     용도
  ----------- -------------- -------------- ---------------------- ------------- -----------
  Main PC     `ros_normal`           **15** `rmw_fastrtps_cpp`     `SUBNET`      기본/독립
                                                                                 DDS

  Main PC     `ros_local`            **15** `rmw_cyclonedds_cpp`   `LOCALHOST`   FMS + Zenoh

  Robot1      `ros_normal`           **30** `rmw_fastrtps_cpp`     `SUBNET`      기본/독립
                                                                                 DDS

  Robot2      `ros_normal`           **31** `rmw_fastrtps_cpp`     `SUBNET`      기본/독립
                                                                                 DDS

  Robot3      `ros_normal`           **32** `rmw_fastrtps_cpp`     `SUBNET`      기본/독립
                                                                                 DDS

  Robot1\~3   `ros_local`             **0** `rmw_cyclonedds_cpp`   `LOCALHOST`   FMS + Zenoh
  ------------------------------------------------------------------------------------------

## 3.2 모드 전환 구조

``` mermaid
flowchart TB
    START["새 터미널 / ROS 2 환경"]

    START --> NORMAL["ros_normal"]
    START --> LOCAL["ros_local"]

    NORMAL --> N_RMW["FastDDS<br/>rmw_fastrtps_cpp"]
    NORMAL --> N_DISC["Discovery: SUBNET"]

    N_RMW --> N_MAIN["Main PC<br/>Domain 15"]
    N_RMW --> N_R1["Robot1<br/>Domain 30"]
    N_RMW --> N_R2["Robot2<br/>Domain 31"]
    N_RMW --> N_R3["Robot3<br/>Domain 32"]

    LOCAL --> L_RMW["CycloneDDS<br/>rmw_cyclonedds_cpp"]
    LOCAL --> L_DISC["Discovery: LOCALHOST"]

    L_RMW --> L_MAIN["Main PC<br/>Domain 15"]
    L_RMW --> L_ROBOT["Robot1 / Robot2 / Robot3<br/>Domain 0"]

    L_MAIN --> Z["Zenoh 통신 사용"]
    L_ROBOT --> Z
```

### Normal 모드

Normal 모드는 Zenoh를 사용하지 않는 기본 ROS 2 환경이다.

``` text
Main PC : Domain 15 / FastDDS / SUBNET
Robot1  : Domain 30 / FastDDS / SUBNET
Robot2  : Domain 31 / FastDDS / SUBNET
Robot3  : Domain 32 / FastDDS / SUBNET
```

장비별 Domain ID가 다르므로 현재 설정에서 Normal 모드는 Main PC와 Robot
간 FMS 통신용이 아니다.

### Local / Zenoh 모드

FMS와 Robot이 통신할 때 사용한다.

``` text
Main PC : Domain 15 / CycloneDDS / LOCALHOST
Robot   : Domain 0  / CycloneDDS / LOCALHOST
```

Main과 Robot은 DDS Domain이 서로 다르며, `zenoh-bridge-ros2dds`와
`zenohd`가 이 둘을 연결한다.

------------------------------------------------------------------------

# 4. Zenoh 버전 및 설치 구성

프로젝트에서 검증한 버전은 **1.9.0**으로 통일한다.

  장비            zenohd   zenoh-bridge-ros2dds
  --------- ------------ ----------------------
  Main PC      **1.9.0**              **1.9.0**
  Robot1      설치 안 함              **1.9.0**
  Robot2      설치 안 함              **1.9.0**
  Robot3      설치 안 함              **1.9.0**

``` mermaid
flowchart LR
    subgraph MAIN["Main PC"]
        MD["zenohd<br/>v1.9.0"]
        MB["zenoh-bridge-ros2dds<br/>v1.9.0"]
    end

    subgraph ROBOTS["Robots"]
        R1["Robot1<br/>bridge v1.9.0"]
        R2["Robot2<br/>bridge v1.9.0"]
        R3["Robot3<br/>bridge v1.9.0"]
    end

    R1 --> MD
    R2 --> MD
    R3 --> MD
    MD --> MB
```

> `zenohd`는 중앙 Router 역할을 하므로 Main PC에서만 실행한다.

------------------------------------------------------------------------

# 5. 전체 Zenoh 통신 구조

## 5.1 전체 시스템

``` mermaid
flowchart LR
    subgraph ROBOT1["Robot 1"]
        direction TB
        R1ROS["TurtleBot3 ROS 2 Nodes<br/>Domain 0<br/>CycloneDDS<br/>LOCALHOST"]
        R1BR["zenoh-bridge-ros2dds 1.9.0<br/>Namespace: /robot1"]
        R1ROS --> R1BR
    end

    subgraph ROBOT2["Robot 2"]
        direction TB
        R2ROS["TurtleBot3 ROS 2 Nodes<br/>Domain 0<br/>CycloneDDS<br/>LOCALHOST"]
        R2BR["zenoh-bridge-ros2dds 1.9.0<br/>Namespace: /robot2"]
        R2ROS --> R2BR
    end

    subgraph ROBOT3["Robot 3"]
        direction TB
        R3ROS["TurtleBot3 ROS 2 Nodes<br/>Domain 0<br/>CycloneDDS<br/>LOCALHOST"]
        R3BR["zenoh-bridge-ros2dds 1.9.0<br/>Namespace: /robot3"]
        R3ROS --> R3BR
    end

    subgraph MAIN["Main PC - 10.10.141.15"]
        direction TB
        ZD["zenohd 1.9.0<br/>Central Zenoh Router<br/>TCP :7447"]
        MBR["Main zenoh-bridge-ros2dds 1.9.0<br/>Domain 15<br/>CycloneDDS<br/>LOCALHOST"]
        ROS["Main ROS 2 / FMS ROS Interface"]
        BE["FastAPI Backend<br/>Uvicorn :8000"]
        FE["Frontend<br/>npm run dev -- --host"]

        ZD -->|"localhost Zenoh"| MBR
        MBR --> ROS
        ROS --> BE
        BE --> FE
    end

    R1BR -->|"tcp/10.10.141.15:7447"| ZD
    R2BR -->|"tcp/10.10.141.15:7447"| ZD
    R3BR -->|"tcp/10.10.141.15:7447"| ZD
```

## 5.2 ROS 메시지 전달 경로

Robot2의 데이터를 Main PC에서 수신하는 예:

``` mermaid
sequenceDiagram
    participant ROSR as Robot2 ROS 2 Node
    participant DDSR as Robot2 CycloneDDS
    participant BR as Robot2 ROS2DDS Bridge
    participant ZD as Main zenohd
    participant BM as Main ROS2DDS Bridge
    participant DDSM as Main CycloneDDS
    participant FMS as FMS / ROS 2 Backend

    ROSR->>DDSR: /odom, /scan, service, action
    DDSR->>BR: Local DDS discovery
    BR->>ZD: Zenoh TCP<br/>tcp/10.10.141.15:7447
    ZD->>BM: Zenoh routing
    BM->>DDSM: DDS Domain 15
    DDSM->>FMS: /robot2/odom<br/>/robot2/scan ...
```

Robot bridge의 namespace에 의해 Main에서는 다음과 같이 구분된다.

``` text
/robot1/...
/robot2/...
/robot3/...
```

------------------------------------------------------------------------

# 6. Main PC 환경

## 6.1 Main PC 설정

``` text
OS        : Ubuntu 24.04
ROS       : ROS 2 Jazzy
Normal    : Domain 15 / FastDDS / SUBNET
Zenoh     : Domain 15 / CycloneDDS / LOCALHOST
zenohd    : 1.9.0
ROS Bridge: 1.9.0
```

### Normal 모드

``` bash
ros_normal
```

``` text
ROS_DOMAIN_ID=15
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

### Zenoh 모드

``` bash
ros_local
```

``` text
ROS_DOMAIN_ID=15
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

------------------------------------------------------------------------

# 7. Robot 환경

## 7.1 Robot 공통 Zenoh 설정

``` text
OS        : Ubuntu 24.04
ROS       : ROS 2 Jazzy
Zenoh     : Domain 0 / CycloneDDS / LOCALHOST
ROS Bridge: 1.9.0
```

### Normal Domain

``` text
Robot1 → 30
Robot2 → 31
Robot3 → 32
```

### Zenoh Domain

``` text
Robot1 → 0
Robot2 → 0
Robot3 → 0
```

### Robot별 namespace

  Robot    Hostname       Zenoh Namespace
  -------- -------------- -----------------
  Robot1   `turtlebot1`   `/robot1`
  Robot2   `turtlebot2`   `/robot2`
  Robot3   `turtlebot3`   `/robot3`

------------------------------------------------------------------------

# 8. Main PC 실행 방법

FMS 전체 시스템을 실행할 때는 역할별 터미널을 분리한다.

``` mermaid
flowchart TB
    START["Main PC 시작"]

    START --> T1["Terminal 1<br/>Zenoh Router"]
    START --> T2["Terminal 2<br/>Main ROS2DDS Bridge"]
    START --> T3["Terminal 3<br/>FMS Backend"]
    START --> T4["Terminal 4<br/>FMS Frontend"]

    T1 --> T1A["ros_local"]
    T1A --> T1B["zenohd<br/>TCP 0.0.0.0:7447"]

    T2 --> T2A["ros_local"]
    T2A --> T2B["zenoh-bridge-ros2dds<br/>Domain 15"]

    T3 --> T3A["Python venv<br/>~/venv/robot"]
    T3A --> T3B["ros_local"]
    T3B --> T3C["FastAPI / Uvicorn<br/>Port 8000"]

    T4 --> T4A["npm run dev -- --host<br/>Frontend"]
```

## 8.1 Terminal 1 - Zenoh Router

``` bash
ros_local
```

실행:

``` bash
zenohd -l tcp/0.0.0.0:7447
```

역할:

``` text
Robot1 Bridge ─┐
Robot2 Bridge ─┼──> zenohd :7447
Robot3 Bridge ─┘
                     │
                     └──> Main Bridge
```

------------------------------------------------------------------------

## 8.2 Terminal 2 - Main ROS2DDS Bridge

새 터미널을 열었다면 다시:

``` bash
ros_local
```

실행:

``` bash
zenoh-bridge-ros2dds \
    -d 15 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/127.0.0.1:7447 \
    client
```

Main bridge에는 Robot namespace를 지정하지 않는다.

------------------------------------------------------------------------

## 8.3 Terminal 3 - FMS Backend

``` bash
cd ~/Logistics_FMS
```

Python 가상환경:

``` bash
source ~/venv/robot/bin/activate
```

ROS 2 Zenoh 환경:

``` bash
ros_local
```

Backend 실행:

``` bash
python -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload
```

실행 예:

``` text
(robot) (ID:15)ugie01:~/Logistics_FMS$
```

------------------------------------------------------------------------

## 8.4 Terminal 4 - FMS Frontend

``` bash
cd ~/Logistics_FMS/frontend
```

실행:

``` bash
npm run dev -- --host
```

Frontend가 ROS 2 노드를 직접 실행하지 않는다면 이 터미널의 `ros_local`
설정은 필수가 아니다.

------------------------------------------------------------------------

# 9. Robot 실행 방법

각 Robot은 **ROS 2 Bringup**과 **Zenoh Bridge**를 별도 터미널에서
실행한다.

``` mermaid
flowchart TB
    START["Robot 시작"]

    START --> T1["Terminal 1<br/>TurtleBot3 Bringup"]
    START --> T2["Terminal 2<br/>Zenoh Bridge"]

    T1 --> L1["ros_local"]
    L1 --> ENV1["Domain 0<br/>CycloneDDS<br/>LOCALHOST"]
    ENV1 --> TB3["turtlebot3_bringup<br/>robot.launch.py"]

    T2 --> L2["ros_local"]
    L2 --> ENV2["Domain 0<br/>CycloneDDS<br/>LOCALHOST"]
    ENV2 --> BR["zenoh-bridge-ros2dds"]
    BR --> ROUTER["Main PC<br/>10.10.141.15:7447"]
```

## 9.1 Terminal 1 - TurtleBot3 Bringup

``` bash
ros_local
```

확인:

``` bash
echo $ROS_DOMAIN_ID
echo $RMW_IMPLEMENTATION
echo $ROS_AUTOMATIC_DISCOVERY_RANGE
```

정상:

``` text
0
rmw_cyclonedds_cpp
LOCALHOST
```

Bringup:

``` bash
ros2 launch turtlebot3_bringup robot.launch.py
```

------------------------------------------------------------------------

## 9.2 Terminal 2 - Zenoh Bridge

새 터미널:

``` bash
ros_local
```

### Robot1

``` bash
zenoh-bridge-ros2dds \
    -d 0 \
    -n /robot1 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/10.10.141.15:7447 \
    client
```

### Robot2

``` bash
zenoh-bridge-ros2dds \
    -d 0 \
    -n /robot2 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/10.10.141.15:7447 \
    client
```

### Robot3

``` bash
zenoh-bridge-ros2dds \
    -d 0 \
    -n /robot3 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/10.10.141.15:7447 \
    client
```

### 공통 명령 형식

``` bash
zenoh-bridge-ros2dds \
    -d 0 \
    -n /robotN \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/<MAIN_PC_IP>:7447 \
    client
```

------------------------------------------------------------------------

# 10. Zenoh Endpoint 주의사항

이 프로젝트에서 사용하는 endpoint 형식:

``` text
tcp/IP:PORT
```

정상:

``` text
tcp/10.10.141.15:7447
tcp/127.0.0.1:7447
```

잘못된 형식:

``` text
tcp://10.10.141.15:7447
tcp:/10.10.141.15:7447
```

잘못 입력할 경우 다음과 같은 오류가 발생할 수 있다.

``` text
Unicast not supported for tcp: protocol
Unable to connect to any of [...]
Failed to start Zenoh runtime
```

------------------------------------------------------------------------

# 11. 통신 확인

## 11.1 전체 확인 흐름

``` mermaid
flowchart LR
    R["Robot ROS 2 실행"] --> RB["Robot Bridge 실행"]
    RB --> Z["Main zenohd 연결"]
    Z --> MB["Main Bridge 실행"]
    MB --> TL["ros2 topic list"]
    TL --> DATA["topic echo / topic hz"]
    DATA --> SA["service / action 확인"]
```

Main PC의 테스트 터미널에서도:

``` bash
ros_local
```

을 먼저 실행한다.

### Robot2 topic 확인

``` bash
ros2 topic list | grep robot2
```

### 전체 Robot 확인

``` bash
ros2 topic list | grep -E '/robot1|/robot2|/robot3'
```

### Odom 확인

``` bash
ros2 topic echo /robot2/odom
```

### LiDAR 주기 확인

``` bash
ros2 topic hz /robot2/scan
```

### Service 확인

``` bash
ros2 service list | grep robot2
```

### Action 확인

``` bash
ros2 action list | grep robot2
```

------------------------------------------------------------------------

# 12. 설치 및 버전 확인

## 12.1 Robot

``` bash
zenoh-bridge-ros2dds --version
```

기대:

``` text
zenoh-bridge-ros2dds v1.9.0
```

RMW 확인:

``` bash
ros2 pkg prefix rmw_cyclonedds_cpp
ros2 pkg prefix rmw_fastrtps_cpp
```

Hold 확인:

``` bash
apt-mark showhold | grep zenoh
```

------------------------------------------------------------------------

## 12.2 Main PC

``` bash
zenohd --version
zenoh-bridge-ros2dds --version
```

기대:

``` text
zenohd v1.9.0
zenoh-bridge-ros2dds v1.9.0
```

RMW:

``` bash
ros2 pkg prefix rmw_cyclonedds_cpp
ros2 pkg prefix rmw_fastrtps_cpp
```

Hold:

``` bash
apt-mark showhold | grep zenoh
```

------------------------------------------------------------------------

# 13. 프로젝트 환경 검증

프로젝트 루트:

``` bash
cd ~/Logistics_FMS
chmod +x verify_env.sh
./verify_env.sh
```

검증 대상:

-   Ubuntu
-   ROS 2 Jazzy
-   Nav2
-   robot_localization
-   Python 가상환경
-   Python Backend 패키지
-   rclpy
-   Node.js
-   npm
-   Docker
-   Docker Compose
-   Frontend `node_modules`

------------------------------------------------------------------------

# 14. 모드 변경 시 주의사항

## 14.1 실행 중인 ROS 2 프로세스

`RMW_IMPLEMENTATION`, `ROS_DOMAIN_ID`, `ROS_AUTOMATIC_DISCOVERY_RANGE`를
변경해도 **이미 실행 중인 ROS 2 프로세스에는 적용되지 않는다.**

따라서 모드를 변경할 때:

``` bash
roskill
ros_local
```

또는:

``` bash
roskill
ros_normal
```

실행 후 ROS 2 노드를 다시 시작한다.

## 14.2 새 터미널

`.bashrc`의 기본 환경은 Normal 모드다.

따라서 Zenoh 통신에 사용하는 새 터미널마다:

``` bash
ros_local
```

을 실행한다.

------------------------------------------------------------------------

# 15. 전체 시스템 시작 순서

``` mermaid
flowchart TB
    A["1. Main PC<br/>ros_local"]
    B["2. Main zenohd 실행<br/>:7447"]
    C["3. Main Bridge 실행<br/>Domain 15"]
    D["4. FMS Backend 실행<br/>:8000"]
    E["5. FMS Frontend 실행"]
    F["6. Robot ros_local"]
    G["7. TurtleBot3 Bringup"]
    H["8. Robot Bridge 실행<br/>/robot1~3"]
    I["9. Main에서 ROS 2 통신 확인"]
    J["시스템 운용"]

    A --> B --> C --> D --> E
    B --> F --> G --> H
    C --> I
    H --> I
    I --> J
```

Main과 Robot의 실행 순서가 완전히 직렬일 필요는 없지만, **Main `zenohd`
Router를 먼저 실행한 뒤 Robot bridge를 연결하는 방식**이 확인 및
디버깅에 가장 편하다.

------------------------------------------------------------------------

# 16. 빠른 실행 명령

## Main PC

### Terminal 1

``` bash
ros_local
zenohd -l tcp/0.0.0.0:7447
```

### Terminal 2

``` bash
ros_local

zenoh-bridge-ros2dds \
    -d 15 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/127.0.0.1:7447 \
    client
```

### Terminal 3

``` bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
ros_local

python -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload
```

### Terminal 4

``` bash
cd ~/Logistics_FMS/frontend
npm run dev -- --host
```

------------------------------------------------------------------------

## Robot1

### Terminal 1

``` bash
ros_local
ros2 launch turtlebot3_bringup robot.launch.py
```

### Terminal 2

``` bash
ros_local

zenoh-bridge-ros2dds \
    -d 0 \
    -n /robot1 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/10.10.141.15:7447 \
    client
```

------------------------------------------------------------------------

## Robot2

### Terminal 1

``` bash
ros_local
ros2 launch turtlebot3_bringup robot.launch.py
```

### Terminal 2

``` bash
ros_local

zenoh-bridge-ros2dds \
    -d 0 \
    -n /robot2 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/10.10.141.15:7447 \
    client
```

------------------------------------------------------------------------

## Robot3

### Terminal 1

``` bash
ros_local
ros2 launch turtlebot3_bringup robot.launch.py
```

### Terminal 2

``` bash
ros_local

zenoh-bridge-ros2dds \
    -d 0 \
    -n /robot3 \
    --ros-automatic-discovery-range LOCALHOST \
    -e tcp/10.10.141.15:7447 \
    client
```

------------------------------------------------------------------------

# 17. 최종 운영 구조 요약

``` mermaid
flowchart TB
    subgraph ROBOTS["Robot Layer"]
        R1["Robot1<br/>Domain 0<br/>/robot1"]
        R2["Robot2<br/>Domain 0<br/>/robot2"]
        R3["Robot3<br/>Domain 0<br/>/robot3"]
    end

    subgraph NETWORK["Zenoh Communication Layer"]
        Z["Main zenohd 1.9.0<br/>10.10.141.15:7447"]
        B["Main ROS2DDS Bridge 1.9.0<br/>Domain 15"]
    end

    subgraph FMS["FMS Layer"]
        ROS["ROS 2 Interface"]
        API["FastAPI Backend<br/>:8000"]
        UI["Web Frontend"]
    end

    R1 --> Z
    R2 --> Z
    R3 --> Z

    Z --> B
    B --> ROS
    ROS --> API
    API --> UI
```

------------------------------------------------------------------------

# 18. 핵심 체크리스트

### Main PC

-   [ ] Ubuntu 24.04
-   [ ] ROS 2 Jazzy
-   [ ] `zenohd --version` → 1.9.0
-   [ ] `zenoh-bridge-ros2dds --version` → 1.9.0
-   [ ] `ros_local` → Domain 15
-   [ ] CycloneDDS
-   [ ] LOCALHOST
-   [ ] `zenohd` :7447 실행
-   [ ] Main bridge 실행
-   [ ] Backend 실행
-   [ ] Frontend 실행

### Robot

-   [ ] Ubuntu 24.04
-   [ ] ROS 2 Jazzy
-   [ ] `zenoh-bridge-ros2dds --version` → 1.9.0
-   [ ] `ros_local` → Domain 0
-   [ ] CycloneDDS
-   [ ] LOCALHOST
-   [ ] TurtleBot3 Bringup 실행
-   [ ] Robot별 namespace 확인
-   [ ] Main Router `10.10.141.15:7447` 연결

### 통신

-   [ ] `/robot1/...` 확인
-   [ ] `/robot2/...` 확인
-   [ ] `/robot3/...` 확인
-   [ ] Topic 데이터 수신
-   [ ] Service 확인
-   [ ] Action 확인

------------------------------------------------------------------------

# 19. 중요 주의사항 요약

1.  **FMS ↔ Robot 통신은 `ros_local` + Zenoh를 사용한다.**
2.  Main PC의 Local Domain은 **15**이다.
3.  모든 Robot의 Local Domain은 **0**이다.
4.  Zenoh 모드에서는 **CycloneDDS + LOCALHOST**를 사용한다.
5.  Normal 모드에서는 **FastDDS + SUBNET**을 사용한다.
6.  Robot별 Zenoh namespace는 `/robot1`, `/robot2`, `/robot3`이다.
7.  `zenohd`는 Main PC에서만 실행한다.
8.  Zenoh/ROS2DDS 버전은 **1.9.0으로 고정**한다.
9.  Endpoint는 반드시 `tcp/IP:PORT` 형식을 사용한다.
10. 새 터미널에서 Zenoh 관련 프로세스를 실행하기 전 `ros_local`을 다시
    실행한다.
11. RMW/Domain/Discovery 변경 후 기존 ROS 2 프로세스를 재시작한다.
