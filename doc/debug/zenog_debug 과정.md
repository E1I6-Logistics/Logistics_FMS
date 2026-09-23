# Zenoh 멀티로봇 통신 문제 해결 기록

## 1. 목표 구조

멀티로봇 FMS 통신 구조를 아래와 같이 구성.

```text
Robot1                         Main PC
ROS 2 DDS                      FMS
/odom        ┐                   │
/scan        │                   │
/cmd_vel     ├─ Zenoh Bridge ────┤ Zenoh Router
/goal        │                   │ 10.10.141.15:7447
/telemetry   ┘                   │
                                 │
Robot2                           │
ROS 2 DDS ─ Zenoh Bridge ────────┤
                                 │
Robot3                           │
ROS 2 DDS ─ Zenoh Bridge ────────┘
```

기본 원칙:

- 로봇 내부 통신: ROS 2 DDS
- 로봇 ↔ Main PC 통신: Zenoh
- 로봇 간 직접 DDS 통신 차단
- Main PC에서 `robot1`, `robot2`, `robot3` 구분
- 기존 TurtleBot3 / Nav2 ROS Topic 구조는 최대한 변경하지 않음

---

# 2. 초기 문제

멀티로봇 Zenoh 통신 테스트 중 다음 문제가 발생.

### 주요 증상

- Robot1/2/3의 Topic이 서로 보임
- `zenoh_bridge_ros2dds` Publisher/Subscriber 수가 비정상적으로 증가
- 웹에서 로봇 위치가 정상 좌표와 이전 좌표 사이를 반복
- 로봇 마커가 깜빡이거나 위치가 튐
- Robot Agent에서 보내는 값과 웹에서 표시되는 값이 다름
- Main PC에 알 수 없는 Zenoh 장비가 추가 연결됨

당시 정상 Robot Agent 좌표:

```text
robot1 → (1.0, 1.0)
robot2 → (2.0, -1.0)
robot3 → (-1.0, 2.0)
```

하지만 Zenoh에서는 다음과 같은 다른 좌표도 반복적으로 수신됨.

```text
robot1 → (2.61, 1.44)
robot2 → (2.55, 0.02)
robot3 → (-1.60, 2.43)
```

처음에는 DB 또는 Web UI 문제로 의심.

---

# 3. DB 문제 여부 확인

DB를 거치지 않고 Zenoh 데이터를 직접 확인하기 위해 `zenoh_monitor.py` 사용.

## zenoh_monitor.py

```python
import zenoh

def listener(sample):
    try:
        print(
            f"[RX] key={sample.key_expr} "
            f"payload={sample.payload.to_bytes()}"
        )
    except Exception as e:
        print(f"[ERR] {e}")

conf = zenoh.Config()

conf.insert_json5(
    "connect/endpoints",
    '["tcp/127.0.0.1:7447"]'
)

session = zenoh.open(conf)

print("Zenoh monitor started")
print("subscribing: **")

sub = session.declare_subscriber(
    "**",
    listener
)

try:
    input("Press Enter to stop...\n")
finally:
    sub.undeclare()
    session.close()
```

모든 Zenoh Key를 확인하기 위해:

```python
session.declare_subscriber("**", listener)
```

사용.

실제 모니터에서도 다음과 같이 Robot Topic이 직접 수신됨.

```text
robot1/battery_state
robot1/imu
robot1/joint_states
robot1/odom
robot1/tf

robot2/joint_states
robot2/odom
robot2/tf
```

## 결과

DB를 거치지 않는 `zenoh_monitor.py`에서도 잘못된 좌표가 확인됨.

따라서:

```text
DB → 문제 원인 X
Web → 문제 원인 X
Zenoh 입력 단계에서 이미 잘못된 데이터 존재
```

DB는 잘못된 telemetry를 저장하고 있었을 뿐 최초 원인은 아니었음.

---

# 4. 문제 1 - 모든 로봇이 같은 ROS_DOMAIN_ID 사용

초기에는 Robot1/2/3 모두 다음 환경을 사용.

```text
ROS_DOMAIN_ID=30
ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

즉:

```text
Robot1 DDS ↔ Robot2 DDS ↔ Robot3 DDS
```

서로 직접 DDS Discovery가 가능했던 상태.

각 로봇에는 `zenoh-bridge-ros2dds`도 실행되고 있었기 때문에 구조가 다음과 같이 형성됨.

```text
robot1 DDS ↔ robot2 DDS ↔ robot3 DDS
    │            │            │
 bridge1      bridge2      bridge3
    │            │            │
    └──────── Zenoh ──────────┘
```

## 발생 문제

Robot1의 ROS Topic을 Robot2 DDS에서도 발견.

Robot2의 Zenoh Bridge 역시 해당 Topic을 발견.

결과적으로 동일한 ROS Interface가 여러 Bridge를 통해 Zenoh에 노출될 수 있는 구조가 됨.

```text
robot1 telemetry
      ↓
robot1 bridge
      ↓
    Zenoh
      ↓
robot2 bridge
      ↓
Robot2 DDS
```

실제 확인 과정에서 일부 로봇에서 `zenoh_bridge_ros2dds` Publisher/Subscriber가 19개, 23개 수준으로 증가하는 현상도 확인.

## 조치

각 로봇의 ROS Domain을 분리.

```text
Main PC → ROS_DOMAIN_ID=15

Robot1 → ROS_DOMAIN_ID=30
Robot2 → ROS_DOMAIN_ID=31
Robot3 → ROS_DOMAIN_ID=32
```

`ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`은 그대로 유지.

최종 구조:

```text
Robot1
DDS Domain 30
Agent ↔ Bridge
          │
          │
          ▼
        Zenoh
          │
          ▼
       Main PC
          ▲
          │
Robot2    │
DDS Domain 31
Agent ↔ Bridge
          │
          │
Robot3    │
DDS Domain 32
Agent ↔ Bridge
```

이제:

```text
Robot1 DDS ✕ Robot2 DDS
Robot1 DDS ✕ Robot3 DDS
Robot2 DDS ✕ Robot3 DDS
```

로봇 간 DDS 직접 Discovery 차단.

로봇 간 외부 통신은 Zenoh만 사용.

---

# 5. 문제 2 - 알 수 없는 Zenoh Peer `10.10.141.37`

Main PC의 Zenoh 연결 상태를 확인하던 중 Robot 3대 외에 추가 IP 발견.

정상 Robot IP:

```text
10.10.141.226
10.10.141.246
10.10.141.221
```

추가 연결:

```text
10.10.141.37
```

Main PC `10.10.141.15:7447`에 총 4개의 외부 장비가 연결된 상태 확인.

```text
10.10.141.221
10.10.141.226
10.10.141.246
10.10.141.37   ← Unknown
```

## 네트워크 확인

Main PC에서:

```bash
ss -nt | grep 7447
```

또는 프로세스까지 확인:

```bash
sudo ss -ntp | grep 7447
```

확인 결과 `.37`이 Main PC Zenoh Router로 연결.

```text
10.10.141.37 → 10.10.141.15:7447
```

추가로 Main PC Python/FastAPI 프로세스가 반대로 `.37:7447`에 연결하는 경로도 확인.

```text
10.10.141.15 → 10.10.141.37:7447
```

즉:

```text
              ┌──────────────┐
              │ 10.10.141.37 │
              └──────┬───────┘
                     │
             Zenoh connection
                     │
              ┌──────▼───────┐
              │ Main PC      │
              │ zenohd       │
              └──────────────┘
```

뿐만 아니라 FastAPI도 `.37`을 직접 발견하여 연결하고 있었음.

---

# 6. `.37` 장비 확인

네트워크 장비 여부 확인.

확인된 정보:

```text
IP  : 10.10.141.37
MAC : 9c:6b:00:17:4b:73
```

MAC Vendor 조회 결과:

```text
ASRock Incorporation
```

따라서 `.37`은 단순한 가상 주소가 아니라 실제 네트워크 장비임을 확인.

해당 장비에서 Zenoh `7447` 포트를 사용하고 있는 정황도 확인.

---

# 7. 문제 3 - FastAPI Zenoh 자동 Discovery

초기 FastAPI Zenoh 설정:

```python
conf = zenoh.Config()

conf.insert_json5(
    "connect/endpoints",
    '["tcp/127.0.0.1:7447"]'
)

zenoh_session = zenoh.open(conf)
```

의도는:

```text
FastAPI
   ↓
127.0.0.1:7447
   ↓
Main PC zenohd
```

였음.

하지만 Zenoh의 기본 Peer/Scouting 동작 때문에 주변 Zenoh Peer를 추가로 발견할 수 있었음.

실제로 FastAPI Python 프로세스가:

```text
127.0.0.1:7447
```

뿐 아니라:

```text
10.10.141.37:7447
192.168.100.56:7447
```

등 다른 Zenoh Endpoint까지 발견해 연결하는 현상 확인.

즉 실제 구조가:

```text
                 ┌─ Main zenohd
FastAPI ─────────┼─ 10.10.141.37
                 └─ 192.168.100.56
```

형태로 변하고 있었음.

---

# 8. FastAPI Zenoh 연결 고정

FastAPI가 Main PC의 `zenohd`에만 연결하도록 변경.

## 최종 설정

```python
conf = zenoh.Config()

conf.insert_json5(
    "mode",
    '"client"'
)

conf.insert_json5(
    "connect/endpoints",
    '["tcp/127.0.0.1:7447"]'
)

conf.insert_json5(
    "scouting/multicast/enabled",
    "false"
)

conf.insert_json5(
    "scouting/gossip/enabled",
    "false"
)

zenoh_session = zenoh.open(conf)
```

변경 내용:

```text
mode = client
connect = tcp/127.0.0.1:7447
multicast scouting = false
gossip scouting = false
```

## 결과

FastAPI 연결이 다음 하나로 고정됨.

```text
FastAPI
   ↓
127.0.0.1:7447
   ↓
Main PC zenohd
```

`.37`, `.56` 등 다른 Zenoh Peer에 FastAPI가 직접 연결하는 현상 제거.

---

# 9. `.37` 차단

`.37`은 승인되지 않은 Zenoh 장비로 판단하여 Main PC에서 차단.

이후 연결 상태를 다시 확인.

정상적으로 기대하는 연결:

```text
10.10.141.226 → Robot1
10.10.141.246 → Robot2
10.10.141.221 → Robot3
127.0.0.1     → FastAPI
```

`.37` 연결이 제거된 것을 확인.

> `.37`이 오래된 telemetry를 최초 생성한 장비였는지,
> 다른 Zenoh Peer의 데이터를 relay한 것인지는
> `.37` 내부 프로세스까지 조사하지 않았기 때문에 확정하지 않음.
>
> 다만 `.37`이 비정상 Zenoh 경로에 참여하고 있었던 것은 확인됨.

---

# 10. Domain 분리 후에도 발생한 문제

ROS Domain을 분리한 뒤 로봇 간 DDS 직접 Discovery는 해결.

하지만 각 Zenoh Bridge가 같은 Main Zenoh Router에 연결되면서 다른 로봇의 Zenoh ROS Interface가 다시 Local DDS로 들어오는 문제가 남음.

예:

Robot1에서:

```text
/robot1/...
/robot2/...
/robot3/...
```

가 모두 보이는 현상.

중요한 점:

```text
ROS Domain 분리 실패 X
Zenoh Bridge가 다른 Domain의 Interface를 다시 DDS로 전달 O
```

즉 구조적으로:

```text
Robot2 DDS
   ↓
Robot2 Bridge
   ↓
Main Zenoh
   ↓
Robot1 Bridge
   ↓
Robot1 DDS
```

가 가능했던 상태.

---

# 11. Bridge Namespace 적용

목표는 로봇 내부 ROS Topic을 그대로 유지하면서 Main PC에서만 Robot ID를 구분하는 것.

원하는 구조:

```text
Robot1 Local DDS       Zenoh / Main PC

/telemetry       →     robot1/telemetry
/goal            ←     robot1/goal
/odom            →     robot1/odom
/scan            →     robot1/scan
/cmd_vel         ←     robot1/cmd_vel
```

Bridge Namespace 사용.

```bash
zenoh-bridge-ros2dds \
    -e tcp/10.10.141.15:7447 \
    -n /robot1 \
    client
```

주의:

```text
-n robot1     X
-n /robot1    O
```

Namespace는 `/`로 시작해야 함.

---

# 12. Agent와 Bridge 이중 Namespace 문제

초기에는 `robot_agent` 자체에도 namespace를 적용하고 Bridge에도 namespace를 적용.

결과:

```text
/robot1/robot1/telemetry
```

같은 이중 Namespace 발생.

또 FastAPI의:

```text
robot1/goal
```

과 실제 ROS Topic 경로가 맞지 않으면서 Goal 통신도 깨짐.

## 수정

`robot_agent`에서는 ROS namespace 제거.

Agent는 Local DDS에서:

```text
/telemetry
/goal
```

만 사용.

Robot ID는 ROS namespace가 아니라 parameter로 전달.

```python
node.declare_parameter('robot_id', 'unknown_robot')
robot_id = node.get_parameter('robot_id').value
```

Bridge만:

```text
-n /robot1
```

사용.

최종:

```text
Local ROS DDS              Zenoh

/telemetry        ↔        robot1/telemetry
/goal             ↔        robot1/goal
```

---

# 13. Bridge Namespace만으로 해결되지 않은 문제

`-n /robot1`을 적용해도 다른 Robot의 Topic이 Local DDS에 들어오는 현상이 남음.

원인:

```text
-n = Namespace/Scope
```

이지:

```text
-n = 다른 Robot Topic 차단
```

기능이 아니기 때문.

따라서 Bridge 자체에서 다른 Robot Namespace를 필터링할 필요가 있었음.

---

# 14. 공통 `bridge.json5` 적용

Robot마다 별도의 Config를 만드는 대신 하나의 공통 Regex Filter 사용.

파일:

```text
~/Logistics_FMS/robots/src/zenoh_pkg/config/bridge.json5
```

내용:

```json5
{
  plugins: {
    ros2dds: {
      deny: {
        publishers: [
          "^/robot[0-9]+/.*$",
          "^/rosout$",
          "^/parameter_events$"
        ],
        subscribers: [
          "^/robot[0-9]+/.*$"
        ],
        service_servers: [
          "^/robot[0-9]+/.*$"
        ],
        service_clients: [
          "^/robot[0-9]+/.*$"
        ],
        action_servers: [
          "^/robot[0-9]+/.*$"
        ],
        action_clients: [
          "^/robot[0-9]+/.*$"
        ]
      }
    }
  }
}
```

핵심 Regex:

```text
^/robot[0-9]+/.*$
```

다른 Robot Namespace를 가진 Interface가 Local DDS로 재유입되는 것을 차단.

동시에:

```text
/rosout
/parameter_events
```

같은 불필요한 ROS 기본 Topic의 외부 전달도 제한.

---

# 15. 최종 Launch 구조

파일:

```text
zenoh_pkg/launch/zenoh.launch.py
```

```python
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration, PythonExpression, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():

    robot_id = LaunchConfiguration('robot_id')

    bridge_namespace = PythonExpression([
        "'/' + '", robot_id, "'"
    ])

    config_file = PathJoinSubstitution([
        FindPackageShare('zenoh_pkg'),
        'config',
        'bridge.json5'
    ])

    return LaunchDescription([

        DeclareLaunchArgument(
            'robot_id',
            default_value='robot1'
        ),

        Node(
            package='zenoh_pkg',
            executable='robot_agent',
            name='robot_agent',
            output='screen',
            parameters=[
                {
                    'robot_id': robot_id
                }
            ]
        ),

        ExecuteProcess(
            cmd=[
                'zenoh-bridge-ros2dds',
                '-c',
                config_file,
                '-e',
                'tcp/10.10.141.15:7447',
                '-n',
                bridge_namespace,
                'client'
            ],
            output='screen'
        ),
    ])
```

실행:

```bash
ros2 launch zenoh_pkg zenoh.launch.py robot_id:=robot1
```

```bash
ros2 launch zenoh_pkg zenoh.launch.py robot_id:=robot2
```

```bash
ros2 launch zenoh_pkg zenoh.launch.py robot_id:=robot3
```

Robot4 추가 시:

```bash
ros2 launch zenoh_pkg zenoh.launch.py robot_id:=robot4
```

공통 Regex를 사용하므로 별도 Bridge Config 수정 필요 없음.

---

# 16. 최종 ROS Domain 설정

## Main PC

```bash
export ROS_DOMAIN_ID=15
```

## Robot1

```bash
export ROS_DOMAIN_ID=30
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

## Robot2

```bash
export ROS_DOMAIN_ID=31
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

## Robot3

```bash
export ROS_DOMAIN_ID=32
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

`ROS_LOCALHOST_ONLY=1`은 사용하지 않음.

테스트 과정에서 해당 설정 사용 시 Zenoh Bridge까지 DDS Discovery가 되지 않는 문제가 발생했기 때문.

---

# 17. 최종 FastAPI Zenoh 설정

```python
conf = zenoh.Config()

conf.insert_json5(
    "mode",
    '"client"'
)

conf.insert_json5(
    "connect/endpoints",
    '["tcp/127.0.0.1:7447"]'
)

conf.insert_json5(
    "scouting/multicast/enabled",
    "false"
)

conf.insert_json5(
    "scouting/gossip/enabled",
    "false"
)

zenoh_session = zenoh.open(conf)
```

Telemetry:

```python
zenoh_subscriber = zenoh_session.declare_subscriber(
    "**/telemetry",
    zenoh_telemetry_listener
)
```

Goal:

```python
target_topic = f"{cmd.robot_id}/goal"
```

예:

```text
robot1/goal
robot2/goal
robot3/goal
```

`rt/` Prefix는 추가하지 않음.

---

# 18. 최종 정상 상태

Robot1에서:

```bash
ros2 topic list
```

예상:

```text
/goal
/telemetry
/odom
/scan
/cmd_vel
...
/rosout
/parameter_events
```

Robot1 Local DDS에 다음 Topic이 보이면 안 됨.

```text
/robot2/...
/robot3/...
```

Robot2/3도 동일.

반면 Main PC Zenoh에서는:

```text
robot1/...
robot2/...
robot3/...
```

로 각각 구분되어야 함.

---

# 19. 최종 통신 구조

```text
┌───────────────────────────────────────┐
│ Robot1                                │
│ ROS_DOMAIN_ID=30                      │
│                                       │
│ /odom                                 │
│ /scan                                 │
│ /cmd_vel                              │
│ /goal                                 │
│ /telemetry                            │
│        ↕                              │
│ zenoh-bridge-ros2dds                  │
│ namespace=/robot1                     │
└───────────────┬───────────────────────┘
                │
                │ Zenoh TCP
                │
                ▼
        ┌─────────────────┐
        │ Main PC         │
        │ 10.10.141.15    │
        │                 │
        │ zenohd :7447    │
        │       ↕         │
        │ FastAPI         │
        │ 127.0.0.1:7447  │
        └─────────────────┘
                ▲
                │
        ┌───────┴────────┐
        │                │
     Robot2           Robot3
   Domain 31         Domain 32
   /robot2 Zenoh     /robot3 Zenoh
```

핵심:

```text
Robot 내부
    ↓
ROS 2 DDS

Robot 외부
    ↓
Zenoh

Main PC
    ↓
Zenoh Router + FastAPI
```

---

# 20. 문제별 원인 및 해결 요약

| 문제 | 원인 | 확인 방법 | 해결 |
|---|---|---|---|
| Robot Topic이 서로 보임 | 동일 ROS Domain | `ros2 topic list`, `topic info -v` | Domain 30/31/32 분리 |
| Bridge endpoint 증가 | DDS + Zenoh 중복 경로 | Publisher/Subscriber 개수 확인 | DDS Domain 분리 |
| 오래된 좌표 수신 | Zenoh 단계에서 stale 데이터 유입 | `zenoh_monitor.py` | 비정상 Zenoh 경로 제거 |
| `.37` 연결 | Unknown Zenoh Peer | `ss -ntp \| grep 7447` | `.37` 차단 |
| FastAPI가 `.37/.56` 연결 | Zenoh Auto Discovery | `ss -ntp` | client mode + scouting OFF |
| DB에 잘못된 좌표 저장 | 잘못된 Zenoh 데이터를 DB가 저장 | Zenoh 직접 Monitor 비교 | Zenoh 원인 제거 |
| `/robot1/robot1/...` | Agent + Bridge 이중 Namespace | `ros2 topic list` | Agent Namespace 제거 |
| 다른 Robot Topic 재유입 | Bridge가 Zenoh Interface를 DDS로 재전달 | 각 Robot `topic list` | `bridge.json5` deny filter |
| `ROS_LOCALHOST_ONLY=1` 사용 시 Bridge 실패 | Localhost 제한으로 Bridge Discovery 차단 | ROS Topic 확인 | 사용하지 않음 |

---

# 21. 문제 해결 과정 요약

전체 해결 과정:

```text
웹에서 로봇 위치 깜빡임
        ↓
DB 문제 의심
        ↓
zenoh_monitor.py로 Zenoh 직접 확인
        ↓
DB 이전부터 잘못된 데이터 존재 확인
        ↓
Zenoh 연결 상태 조사
        ↓
10.10.141.37 발견
        ↓
FastAPI도 .37에 직접 연결된 것 확인
        ↓
Zenoh Auto Discovery 확인
        ↓
FastAPI client mode 고정
multicast/gossip OFF
        ↓
.37 비정상 연결 제거
        ↓
로봇 DDS 구조 확인
        ↓
3대 모두 같은 ROS_DOMAIN_ID 사용 확인
        ↓
30 / 31 / 32로 분리
        ↓
DDS 직접 교차 Discovery 제거
        ↓
Zenoh를 통해 다른 Robot Topic이
Local DDS로 재유입되는 문제 발견
        ↓
Bridge namespace 적용
        ↓
Agent + Bridge 이중 namespace 문제 발생
        ↓
Agent namespace 제거
Bridge namespace만 유지
        ↓
-n은 Filter가 아니라는 것 확인
        ↓
bridge.json5 deny filter 적용
        ↓
Robot별 Local DDS 격리 성공
        ↓
최종 구조 확정
```

---

# 22. 최종 결론

문제는 하나가 아니라 크게 3개의 문제가 동시에 존재했던 복합 문제.

### 1. DDS 구조 문제

```text
Robot1/2/3가 같은 ROS_DOMAIN_ID 사용
```

때문에 로봇끼리 DDS로 직접 Discovery되고 여러 Zenoh Bridge가 동일 ROS Interface를 발견.

해결:

```text
Robot1 = Domain 30
Robot2 = Domain 31
Robot3 = Domain 32
```

---

### 2. Zenoh Network 문제

```text
10.10.141.37
```

이라는 승인되지 않은 Zenoh Peer가 Main Router와 연결되어 있었음.

또 FastAPI가 Zenoh Auto Discovery를 통해 해당 Peer에 직접 연결.

해결:

```text
Zenoh mode = client
connect = 127.0.0.1:7447
multicast = false
gossip = false
```

FastAPI를 Main Zenoh Router 하나에만 연결.

---

### 3. Zenoh Bridge 재유입 문제

DDS Domain을 분리한 뒤에도 같은 Zenoh Router에 연결된 Bridge들이 다른 Robot의 ROS Interface를 Local DDS로 다시 전달.

해결:

```text
Bridge Namespace
+
공통 bridge.json5 deny filter
```

적용.

---

# 23. 최종 설계 원칙

현재 구조는 아래 원칙으로 고정.

```text
1. Robot 내부 통신은 ROS 2 DDS

2. Robot 간 DDS 직접 Discovery 금지

3. Robot ↔ Main PC 통신은 Zenoh

4. Robot마다 ROS_DOMAIN_ID 분리

5. Robot Agent는 ROS Namespace 사용하지 않음

6. Robot 구분은 Zenoh Bridge Namespace에서 수행

7. 다른 Robot Namespace는 Bridge Filter로 Local DDS 유입 차단

8. FastAPI는 Main PC zenohd 하나에만 연결

9. Zenoh multicast/gossip Auto Discovery 사용하지 않음

10. 기존 TurtleBot3/Nav2 ROS Topic 구조는 변경하지 않음
```

최종적으로:

```text
Robot 내부 = DDS
Robot 외부 = Zenoh
Main PC = 중앙 FMS
```

구조로 정리됨.