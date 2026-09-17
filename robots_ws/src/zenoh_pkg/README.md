# zenoh_pkg

ROS2 로봇과 메인 PC FMS 간 **Zenoh 통신**을 위한 패키지입니다.

## 주요 기능

- `robot_agent.py` 실행
- `zenoh-bridge-ros2dds` 실행
- Namespace를 이용한 로봇 ID 구분
- 로봇 상태 `telemetry` 송신
- 메인 PC의 `goal` 명령 수신

---

## 빌드

```bash
cd ~/robot_ws
colcon build --symlink-install
source install/setup.bash
```

---

## 실행

### Robot1

```bash
ros2 launch zenoh_pkg zenoh.launch.py ns:=robot1
```

### Robot2

```bash
ros2 launch zenoh_pkg zenoh.launch.py ns:=robot2
```

### Robot3

```bash
ros2 launch zenoh_pkg zenoh.launch.py ns:=robot3
```

Namespace를 지정하지 않으면 기본값은 `noname_robot`입니다.

```bash
ros2 launch zenoh_pkg zenoh.launch.py
```

---

## Launch 구성

Launch 파일을 실행하면 아래 두 프로세스가 함께 실행됩니다.

```text
robot_agent
+
zenoh-bridge-ros2dds -e tcp/10.10.141.15:7447 client
```

Zenoh Bridge는 메인 PC의 Zenoh Router(`10.10.141.15:7447`)에 연결됩니다.

---

## ROS Domain 설정

각 로봇은 서로 다른 `ROS_DOMAIN_ID`를 사용합니다.

```text
Main PC : 15
Robot1  : 30
Robot2  : 31
Robot3  : 32
```

각 로봇의 `~/.bashrc`에 설정합니다.

### Robot1

```bash
export ROS_DOMAIN_ID=30
```

### Robot2

```bash
export ROS_DOMAIN_ID=31
```

### Robot3

```bash
export ROS_DOMAIN_ID=32
```

### Main PC:

```bash
export ROS_DOMAIN_ID=15
```

설정 후 적용:

```bash
source ~/.bashrc
```

---

## 주요 ROS2 Topic

Namespace에 따라 Topic 이름이 자동으로 결정됩니다.

```text
Robot1
/robot1/telemetry
/robot1/goal

Robot2
/robot2/telemetry
/robot2/goal

Robot3
/robot3/telemetry
/robot3/goal
```

---

## 통신 구조

```text
Robot1 (Domain 30) ─┐
Robot2 (Domain 31) ─┼── Zenoh ── Main PC (10.10.141.15)
Robot3 (Domain 32) ─┘
```

각 로봇은 서로 다른 ROS Domain을 사용하며, 메인 PC FMS와의 통신은 Zenoh를 통해 수행합니다.