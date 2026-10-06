# 경로 예약 로직 이관

`mock_data.py`의 예약·교착 해소·주행 허가 정책은
`backend/app/services/traffic_manager.py`의 `TrafficManager`로 이관했다.
점유 변환은 `occupancy.py`로 분리했다. 기존 `pathfinding.py`와
`reservation.py`는 그대로 사용한다.

## 책임 구분

| 구성 요소 | 책임 |
| --- | --- |
| `TrafficManager` | 요청 ID·순서, 예약 확정·해제, 대기 재시도, 교착 관계 탐색, 양보 및 원래 목적지 재개, 구간 허가 검사, 수동 조작 제한 |
| `occupancy.py` | 좌표의 노드·통로 판정, 방향별 edge ID를 공통 물리 자원으로 변환 |
| `MockFmsStore` | 가상 로봇 초기화, tick과 좌표 보간, 즉시 위치 변경, mock 연결·API 응답·화면 상태 |
| 향후 실물 실행기 | 위치·점유 갱신, 구간 명령 전송, 정지·도착 확인, 피드백의 요청 ID 검증 |

`TrafficManager`는 mock이나 ROS를 import하지 않으며, 생성 시 지도 파일을 읽거나
로봇을 생성하지 않는다. 그래프·현재 시각·로봇 상태·예약표를 외부에서 전달받는다.
`mock_data.py`를 제거해도 두 신규 모듈과 기존 탐색·예약 모듈은 독립적으로 남는다.

## 생성 및 상태 계약

```python
traffic = TrafficManager(
    robots,
    reservations,
    speed_mps=planning_speed,
    safety_margin=reservation_margin,
)
```

`robots`는 `{robot_id: state_dict}` 형태의 공유 상태다. ROS `Robot` 객체를 직접
받는 어댑터는 이번 범위에 포함하지 않았다. 다음 필드가 필요하다.

| 필드 | 의미 |
| --- | --- |
| `robot_id`, `x`, `y`, `yaw` | 식별자와 유효한 지도 좌표·방향 |
| `status` | 정책 상태: `IDLE`, `WAITING`, `NAVIGATING` 등 |
| `current_node`, `occupied_node`, `occupied_edge` | 현재 점유. 노드 또는 통로 중 하나를 확인할 수 있어야 함 |
| `route`, `goal_node`, `navigation_id` | 실행 경로, 원래 목적지, 현재 요청 ID. 초기값 `None` |
| `request_order`, `stop_requested` | 접수 순서와 명시적 정지 여부. 초기값 `None`, `False` |

상태 dict의 위치·점유 변경과 관련 정책 호출은 `with traffic.lock:` 안에서 함께
처리한다. 매핑을 교체하지 말고 같은 객체를 유지한다. 지도 좌표·점유는 실행기가
갱신하며, 서비스는 좌표를 보간하지 않는다. 교착 후보 검증 중에는 **복사본**의
위치만 가상으로 바꾼다.

각 서비스에 전용 예약표를 전달한다. `reset_after_stop()`은 그 예약표 전체와
계획 상태를 초기화하지만 로봇 위치·점유를 지우지 않는다. 속도와 여유 시간은
생성 시 지정하며 활성 예약이 있는 동안 변경하지 않는다.

## 실행기 연결 지점

1. 기존 실행의 정지와 점유 갱신 후 `request_navigation_after_stop()`으로 접수한다.
2. `retry_waiting()`을 주기 또는 상태 변화에 따라 호출해 재예약과 교착 해소를 진행한다.
3. 각 구간 실행 전에 `check_segment_permission()`에 현재 시각과 예상 도착 시각을 전달한다.
4. 확인된 통로 점유는 `confirm_edge_occupancy()`, 다음 노드 도착은
   `confirm_node_arrival()`로 반영한다. 도착 API 호출 전에 실행기가 위치도 갱신한다.
5. 재계획은 정지 확인 후 `wait_for_reservation_after_stop()`, 명시적 취소는
   `cancel_navigation_after_stop()`으로 처리한다. 실제 점유는 계속 보존한다.

허가 결과는 상태와 예약표를 변경하지 않는 `SegmentPermission`이다.

| `decision` | 의미 |
| --- | --- |
| `allowed` | 현재 요청·구간 예약, 출발시각, 실제 점유, 예상 도착시간 검사 통과 |
| `waiting` | 계획된 출발시각을 기다림. 예약 유지 |
| `replan` | 예약 누락·다른 로봇 점유·시간표 초과 등. 실제 정지 확인 없이 예약을 해제하면 안 됨 |

예약표와 `now`, `expected_arrival_at`은 동일한 단조 증가 시각 기준을 사용한다.
예상 도착 시각은 실행기가 계산한다. mock은 기존 계산과 동일하게 현재 tick의
이동량을 반영한다. 실제 실행기의 관측 기반 도착 추정은 별도 구현 대상이다.

`validate_manual_velocity()`는 예약 주행·대기·양보 중 비영속도 명령을 거부한다.
영속도 명령은 허용하되 `False`를 반환하므로 호출자가 기존 주행 상태를 덮어쓰지 않는다.

## 이관 범위와 남은 실물 연결 작업

이번 작업은 기존 정책을 보존하는 분리다. `retry_waiting()`에서 우선 요청이
종료·취소·교체되면 양보 중인 경로를 정리하고 원래 목표를 재계획하는 기존 동작도
유지했다. mock은 같은 잠금에서 즉시 정지할 수 있다. 실물 연결 시에는 이 전환으로
영향받는 실행의 정지를 확인하는 절차를 추가해야 한다. Python 잠금 자체가 물리적
정지를 보장하지 않는다.

AMCL 오차·차체 크기를 반영한 점유 추정, 지연·연결 단절 처리, 구간별 ROS 명령,
늦게 도착한 이전 요청 피드백 차단은 이번 변경에서 구현하지 않았다.
`locate_occupancy()`의 기본 허용 오차는 기존 `1e-6m`이며 인자로 조정할 수 있다.
단, 기존 `plan_timed()`와 `build_schedule()`도 정확한 노드 좌표를 요구하므로
점유 판정 오차만 넓혀서 실물에 바로 연결하는 것은 충분하지 않다.
