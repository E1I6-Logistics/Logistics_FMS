# 비동기 처리(asyncio), 파일 경로(Path), 웹 서버(FastAPI), 시스템 명령어(subprocess, iptables 등)를 위한 파이썬 기본 및 외부 모듈을 가져옵니다.
import asyncio
import io
import json
import re
import struct
import subprocess
import ipaddress
from contextlib import asynccontextmanager
from pathlib import Path

# 지도 파일을 읽기 위한 yaml, 이미지를 웹으로 전송하기 위한 PIL(Pillow), 그리고 로봇 통신을 위한 zenoh 모듈입니다.
import yaml
from PIL import Image
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, JSONResponse
from pydantic import BaseModel
import zenoh

# 로봇의 상태를 저장하고 조회하기 위해 내부 데이터베이스(SQLite 등) 모듈을 가져옵니다.
from .database.database import (
    init_db,
    upsert_robot_state,
    get_all_robots,
)

# ============================================================
# 경로 설정
# ============================================================
# 현재 파일(main.py)의 위치를 기준으로 2단계 상위 폴더를 최상위 디렉토리(BASE_DIR)로 지정합니다.
BASE_DIR = Path(__file__).resolve().parents[2]

# 로봇이 주행할 정적 지도(Map) 파일들과 경로(Route Graph) 파일들이 위치할 경로를 설정합니다.
MAP_DIR = BASE_DIR / "maps"
ROUTE_DIR = BASE_DIR / "routes"

MAP_YAML_PATH = MAP_DIR / "my_map.yaml"
ROUTE_GRAPH_PATH = ROUTE_DIR / "test.geojson"

# 로봇 수동 조작(cmd_vel) 시 안전을 위해 서버단에서 제한하는 최대 직진(Linear) 및 회전(Angular) 속도입니다.
CMD_VEL_MAX_LINEAR = 0.5
CMD_VEL_MAX_ANGULAR = 2.0

# ============================================================
# WebSocket 연결 관리자
# ============================================================
# 웹 대시보드(클라이언트 브라우저)들과의 실시간 WebSocket 통신 세션을 관리하는 클래스입니다.
class ConnectionManager:
    def __init__(self):
        # 현재 연결되어 있는 웹 소켓 클라이언트들의 목록을 저장합니다.
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        # 클라이언트가 접속을 요청하면 수락하고 목록에 추가합니다.
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        # 클라이언트의 연결이 끊어지면 목록에서 제거합니다.
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # 접속 중인 모든 웹 클라이언트에게 로봇의 상태(위치, 배터리 등)를 실시간으로 뿌려주는(Broadcast) 함수입니다.
        dead_connections = []
        for connection in self.active_connections:
            try:
                # JSON 형태로 데이터를 전송합니다.
                await connection.send_json(message)
            except Exception:
                # 전송 중 에러가 발생한(죽은) 연결은 추려서 나중에 리스트에서 삭제합니다.
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)


# 위에서 정의한 클래스의 인스턴스를 생성하여 전역적으로 사용합니다.
manager = ConnectionManager()
# Zenoh 통신 세션과 구독자, 그리고 비동기 루프를 저장할 전역 변수들입니다.
zenoh_session = None
zenoh_subscriber = None
loop = None
# 각 토픽별로 퍼블리셔(발행자)를 캐싱(저장)해두어 통신 지연을 방지하기 위한 딕셔너리입니다.
zenoh_publishers = {}

# 관리자가 승인한(알고 있는) 정상 로봇들의 IP 주소와 ID 매핑 목록입니다.
KNOWN_DEVICES = {
    "10.10.141.226": "robot1",
    "10.10.141.246": "robot2",
    "10.10.141.221": "robot3",
}
# 방화벽 정책에 의해 차단된 IP 목록과, 한 번이라도 통신이 감지된 전체 IP 목록을 저장합니다.
blocked_devices = set()
seen_devices = set(KNOWN_DEVICES.keys())

def _valid_ip(ip: str) -> str:
    # 입력된 문자열이 유효한 IP 주소 형태인지 검증합니다. (해킹/인젝션 방지)
    return str(ipaddress.ip_address(ip))

def _run_ss():
    # 리눅스 'ss' 명령어를 실행하여 현재 서버의 네트워크 소켓 연결 상태를 텍스트로 캡처해 옵니다.
    result = subprocess.run(["ss", "-Hnt"], capture_output=True, text=True, check=False)
    return result.stdout

def _zenoh_peers():
    # 'ss' 명령어로 캡처한 네트워크 상태 중, Zenoh 포트(7447)로 접속된 외부 기기들의 IP만 추출하여 반환하는 함수입니다.
    peers = set()
    for line in _run_ss().splitlines():
        cols = line.split()
        if len(cols) < 5 or cols[0] != "ESTAB": # 연결이 성립(ESTABLISHED)된 소켓만 찾습니다.
            continue
        local_addr, peer_addr = cols[3], cols[4]
        if not local_addr.endswith(":7447"):
            continue
        # 외부 기기의 IP 주소만 파싱합니다.
        ip = peer_addr.rsplit(":", 1)[0].strip("[]")
        if ip not in ("127.0.0.1", "::1"):
            peers.add(ip)
    # 감지된 IP들을 known 리스트에 업데이트합니다.
    seen_devices.update(peers)
    return peers

def _firewall(action: str, ip: str):
    # 리눅스 iptables 방화벽을 시스템 명령어로 조작하여 특정 IP의 Zenoh(7447) 접속을 물리적으로 차단(block)하거나 허용(allow)합니다.
    ip = _valid_ip(ip)
    base = ["sudo", "iptables"]
    # 7447번 포트로 들어오는 해당 IP의 TCP 패킷을 거절(REJECT)하는 규칙입니다.
    rule = ["INPUT", "-s", ip, "-p", "tcp", "--dport", "7447", "-j", "REJECT"]
    if action == "block":
        # 규칙이 이미 있는지 확인(-C) 후, 없으면 삽입(-I)합니다.
        check = subprocess.run(base + ["-C"] + rule, capture_output=True)
        if check.returncode != 0:
            subprocess.run(base + ["-I"] + rule, check=True)
        blocked_devices.add(ip)
    elif action == "allow":
        # 규칙이 존재한다면 삭제(-D)하여 차단을 해제합니다. 여러 번 중복되었을 수 있으니 루프를 돕니다.
        while subprocess.run(base + ["-C"] + rule, capture_output=True).returncode == 0:
            subprocess.run(base + ["-D"] + rule, check=True)
        blocked_devices.discard(ip)

def device_snapshot():
    # 현재 네트워크에 물려있는 기기들의 접속/차단/오프라인 상태를 정리하여 JSON(딕셔너리 리스트)으로 만들어 반환합니다. 웹 관리자 대시보드에서 사용됩니다.
    connected = _zenoh_peers()
    devices = []
    for ip in sorted(seen_devices | blocked_devices):
        blocked = ip in blocked_devices
        devices.append({
            "ip": ip,
            "name": KNOWN_DEVICES.get(ip, "Unknown"),
            "known": ip in KNOWN_DEVICES,
            "connected": ip in connected and not blocked,
            "blocked": blocked,
            "state": "BLOCKED" if blocked else ("CONNECTED" if ip in connected else "OFFLINE"),
        })
    return devices


# ============================================================
# 정적 지도 / Route Graph 유틸
# ============================================================
def load_map_metadata():
    # ROS에서 사용하는 YAML 포맷의 맵 정보 파일(my_map.yaml)을 읽어와 해상도, 기준점(origin) 등을 파싱합니다.
    if not MAP_YAML_PATH.exists():
        raise FileNotFoundError(
            f"Map YAML 파일 없음: {MAP_YAML_PATH}"
        )

    with open(MAP_YAML_PATH, "r", encoding="utf-8") as f:
        map_yaml = yaml.safe_load(f)

    image_name = map_yaml["image"]
    image_path = Path(image_name)

    # 경로가 상대경로인 경우 절대경로로 맞춰줍니다.
    if not image_path.is_absolute():
        image_path = MAP_DIR / image_name

    if not image_path.exists():
        raise FileNotFoundError(
            f"Map 이미지 파일 없음: {image_path}"
        )

    # PIL을 이용해 맵 이미지 파일(보통 PGM 형태)을 열어 가로, 세로 픽셀 크기를 구합니다.
    with Image.open(image_path) as img:
        width, height = img.size

    return {
        "yaml_path": str(MAP_YAML_PATH),
        "image_path": str(image_path),
        "image_name": image_path.name,
        "resolution": float(map_yaml["resolution"]),
        "origin": map_yaml["origin"],
        "negate": int(map_yaml.get("negate", 0)),
        "occupied_thresh": float(
            map_yaml.get("occupied_thresh", 0.65)
        ),
        "free_thresh": float(
            map_yaml.get("free_thresh", 0.25)
        ),
        "width": width,
        "height": height,
    }


def load_route_graph() -> dict:
    # 로봇들이 이동할 수 있는 경로와 노드 정보를 담고 있는 GeoJSON 파일(test.geojson)을 읽어서 반환합니다.
    if not ROUTE_GRAPH_PATH.exists():
        raise FileNotFoundError(
            f"Route Graph 파일이 없습니다: {ROUTE_GRAPH_PATH}"
        )

    with ROUTE_GRAPH_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def pgm_to_png_bytes() -> bytes:
    # ROS에서 사용하는 PGM 형태의 흑백 지도 이미지는 웹 브라우저에서 바로 띄우기 힘듭니다. 
    # 따라서 이 함수는 PGM 파일을 읽어 웹 친화적인 PNG 포맷의 바이트 데이터로 변환하여 메모리 위에서(io.BytesIO) 반환해 줍니다.
    map_info = load_map_metadata()
    image_path = Path(map_info["image_path"])

    with Image.open(image_path) as img:
        converted = img.convert("L") # 흑백(Grayscale) 모드로 변환합니다.
        output = io.BytesIO()
        converted.save(output, format="PNG")
        return output.getvalue()

def make_twist_stamped_cdr(linear_x: float, angular_z: float) -> bytes:
    # 매우 중요한 통신 직렬화 함수입니다! 
    # 이 서버(FastAPI)는 ROS 2 라이브러리(rclpy 등)가 없기 때문에 ROS 2 메시지를 생성할 수 없습니다.
    # 따라서 ROS 2의 DDS 통신 규약인 'CDR(Common Data Representation)' 포맷에 맞게, 
    # 파이썬의 struct 모듈을 사용해 수동으로 바이트(Byte) 배열을 조립합니다. 
    # 결과적으로 로봇이 받는 데이터는 완벽한 geometry_msgs/TwistStamped 메시지로 인식됩니다.
    """
    geometry_msgs/msg/TwistStamped

    Header:
      builtin_interfaces/Time stamp
        int32 sec
        uint32 nanosec
      string frame_id

    Twist:
      Vector3 linear
      Vector3 angular
    """

    # CDR header
    # CDR 포맷임을 알리는 4바이트 헤더입니다 (리틀 엔디안).
    cdr_header = b"\x00\x01\x00\x00"

    # Header.stamp
    sec = 0
    nanosec = 0

    # Header.frame_id = ""
    # ROS2 string은 NULL 포함 길이 prefix
    frame_id = b"\x00"
    frame_id_length = len(frame_id)

    # 시간 정보(sec, nanosec)와 문자열 길이(frame_id_length)를 정수 형태로 패킹합니다.
    body = struct.pack(
        "<iII",
        sec,
        nanosec,
        frame_id_length
    )

    body += frame_id

    # 8-byte alignment
    # CDR 규격상 8바이트 정렬(Alignment)을 맞춰야 하므로, 남는 공간에 NULL 패딩을 채워 넣습니다.
    padding = (8 - (len(body) % 8)) % 8
    body += b"\x00" * padding

    # Twist
    # Twist 데이터(직진x,y,z / 회전x,y,z 총 6개의 double 형 데이터)를 8바이트씩(총 48바이트) 직렬화하여 붙입니다.
    body += struct.pack(
        "<6d",
        linear_x, 0.0, 0.0,
        0.0, 0.0, angular_z
    )

    return cdr_header + body

# ============================================================
# Zenoh 텔레메트리 수신
# ============================================================
def zenoh_telemetry_listener(sample):
    # 로봇들(robot_agent_test.py)이 "telemetry" 토픽으로 보내는 데이터를 서버가 Zenoh를 통해 수신하면 트리거되는 콜백 함수입니다.
    try:
        topic = str(sample.key_expr) # 예: "robot1/telemetry"
        raw_bytes = sample.payload.to_bytes()

        # ROS 2 std_msgs/String CDR 데이터에서 JSON 문자열 부분 추출
        # 수신한 데이터도 ROS 2의 String 구조체(CDR 포맷)이므로, 앞쪽의 헤더를 무시하고 순수 텍스트(JSON 형태)만 정규표현식으로 추출합니다.
        text = raw_bytes.decode("utf-8", errors="ignore")
        json_match = re.search(r"\{.*\}", text)
        if not json_match:
            return

        data = json.loads(json_match.group(0))

        # 토픽 이름에서 네임스페이스("robot1")를 파싱하거나, JSON 내부의 로봇 ID를 사용해 누구의 데이터인지 식별합니다.
        parts = [p for p in topic.split("/") if p and p != "rt"]
        robot_id = data.get("robot_id", parts[0] if parts else "robot1")

        # 로봇의 상태 정보들을 안전하게 float/string 변수로 파싱합니다.
        x = float(data.get("x", 0.0))
        y = float(data.get("y", 0.0))
        yaw = float(data.get("yaw", 0.0))
        battery = float(data.get("battery", 100.0))
        status = data.get("status", "ONLINE")

        telemetry = {
            "robot_id": robot_id,
            "x": x,
            "y": y,
            "yaw": yaw,
            "battery": battery,
            "status": status,
        }

        # 이 콜백은 Zenoh의 백그라운드 스레드에서 실행되므로, FastAPI의 비동기 메인 이벤트 루프에 안전하게 작업을 던져줍니다(threadsafe).
        if loop is not None:
            # 1. 수신한 데이터를 데이터베이스에 최신 상태로 업데이트(upsert) 합니다.
            asyncio.run_coroutine_threadsafe(
                upsert_robot_state(robot_id, x, y, yaw, battery, status),
                loop,
            )
            # 2. 웹 대시보드 클라이언트들에게 방금 받은 로봇의 상태를 실시간(WebSocket)으로 뿌려줍니다.
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "telemetry", "data": telemetry}),
                loop,
            )

    except Exception as e:
        print(f"Zenoh 파싱 에러: {e}")


# ============================================================
# FastAPI lifespan
# ============================================================
# FastAPI 웹 서버가 시작될 때와 종료될 때 한 번씩 실행되는 생명주기 관리자(lifespan)입니다.
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop, zenoh_session, zenoh_subscriber

    loop = asyncio.get_running_loop()
    # 서버 시작 시 DB 테이블을 생성하거나 초기화합니다.
    await init_db()

    # 맵/그래프 파일 로드 확인
    # 지도 및 라우트 파일들이 정상적으로 있는지 서버 기동 시점에 미리 체크합니다.
    try:
        map_info = load_map_metadata()
        print(
            " -> Map 로드 확인 완료: "
            f"{map_info['image_name']} "
            f"({map_info['width']}x{map_info['height']}, "
            f"resolution={map_info['resolution']})"
        )
    except Exception as e:
        print(f" -> [WARN] Map 로드 실패: {e}")

    try:
        graph = load_route_graph()
        features = graph.get("features", [])
        node_count = sum(
            1 for f in features if f.get("geometry", {}).get("type") == "Point"
        )
        edge_count = sum(
            1
            for f in features
            if f.get("geometry", {}).get("type") in ("LineString", "MultiLineString")
        )
        print(f" -> Route Graph 로드 확인 완료: nodes={node_count}, edges={edge_count}")
    except Exception as e:
        print(f" -> [WARN] Route Graph 로드 실패: {e}")

    # Zenoh 연결 및 구독자 등록 (GC 소멸 방지: zenoh_subscriber 변수에 할당)
    # 로컬 PC에 띄워둔 Zenoh 라우터(127.0.0.1:7447)와 연결을 맺고 통신 준비를 마칩니다.
    try:
        conf = zenoh.Config()
        conf.insert_json5("mode", '"client"')
        conf.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7447"]')
        conf.insert_json5("scouting/multicast/enabled", "false")
        conf.insert_json5("scouting/gossip/enabled", "false")
        zenoh_session = zenoh.open(conf)
        
        # 모든 로봇으로부터 "telemetry"가 포함된 토픽을 수신할 수 있도록 구독(Subscribe)을 설정합니다.
        zenoh_subscriber = zenoh_session.declare_subscriber(
            "**/telemetry",
            zenoh_telemetry_listener
        )
        
        # ===== [추가] 로봇 1, 2, 3을 위한 퍼블리셔를 미리 생성하여 브리지 라우팅 지연 방지 =====
        # 토픽을 쏠 때마다 Publisher 객체를 생성하면 지연이 발생할 수 있으므로, 시작 단계에서 미리 뚫어놓습니다(캐싱).
        for i in range(1, 4):
            topic = f"robot{i}/goal"
            zenoh_publishers[topic] = zenoh_session.declare_publisher(topic)
        # =========================================================================

        print(f" -> FMS Zenoh 수신 세션 활성화 완료! (ZID: {zenoh_session.zid()})")

    except Exception as e:
        zenoh_session = None
        zenoh_subscriber = None
        print(f" -> [WARN] Zenoh 연결 실패. 웹 지도/API만 실행합니다: {e}")

    # 이 yield 구문에서 앱이 실행되며, yield 이후의 코드는 앱이 종료될 때 실행됩니다.
    yield

    # 웹 서버가 종료될 때 리소스 누수(Memory Leak)를 막기 위해 Zenoh 세션을 깔끔하게 닫습니다.
    if zenoh_subscriber is not None:
        zenoh_subscriber.undeclare()
    if zenoh_session is not None:
        zenoh_session.close()


# FastAPI 애플리케이션 객체를 생성합니다. 위에서 만든 lifespan 함수를 연결해 줍니다.
app = FastAPI(title="Local FMS / ACS Hub", lifespan=lifespan)

# 다른 도메인(웹 프론트엔드 포트 등)에서 이 API 서버로 접근할 수 있도록 CORS 정책을 개방합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 정적 Map / Route Graph API
# ============================================================
# 웹 프론트엔드에 지도의 메타데이터(크기, 해상도 등)를 JSON 형태로 제공하는 GET API입니다.
@app.get("/api/map/info")
async def get_map_info():
    try:
        info = load_map_metadata()
        info.pop("yaml_path", None)
        info.pop("image_path", None)
        info["image_url"] = "/api/map/image"
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 위에서 만든 pgm_to_png_bytes 함수를 호출하여, 브라우저가 지도를 화면에 그릴 수 있도록 PNG 이미지를 내려주는 GET API입니다.
@app.get("/api/map/image")
async def get_map_image():
    try:
        return Response(content=pgm_to_png_bytes(), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 노드(포인트)와 엣지(선)로 구성된 경로 데이터를 프론트엔드에 전달해주는 GET API입니다.
@app.get("/api/route/graph")
async def get_route_graph():
    try:
        return load_route_graph()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Robot API
# ============================================================
# DB에 저장된 모든 로봇의 가장 최근 상태 리스트를 가져오는 GET API입니다.
@app.get("/api/robots")
async def fetch_robots():
    robots = await get_all_robots()
    for r in robots:
        # 날짜 형태의 객체는 JSON 응답을 위해 문자열 포맷(ISO)으로 치환합니다.
        if "updated_at" in r and r["updated_at"]:
            r["updated_at"] = r["updated_at"].isoformat()
    return robots


# 사용자가 웹에서 로봇을 클릭해 목적지를 지시할 때 서버로 들어오는 JSON 바디 형태를 정의합니다 (Pydantic 모델 사용).
class CommandPayload(BaseModel):
    robot_id: str
    target_x: float
    target_y: float


# 대시보드(웹)에서 로봇에게 "특정 좌표로 이동하라"는 명령을 내릴 때 호출되는 POST API입니다.
@app.post("/api/command/goal")
async def send_goal(cmd: CommandPayload):
    if not zenoh_session:
        return {
            "status": "ERROR",
            "message": "Zenoh session inactive"
        }

    # Bridge namespace 구조에 맞춘 Zenoh key: robot1/goal, robot2/goal ...
    # 보낼 토픽의 주소를 'robot1/goal' 형태로 구성합니다. 이 데이터는 Zenoh 브릿지를 타고 로봇 내부의 '/goal' 토픽으로 배달됩니다.
    target_topic = f"{cmd.robot_id}/goal"

    # 퍼블리셔가 캐싱되어 있지 않다면 새로 만들어서 딕셔너리에 추가합니다.
    if target_topic not in zenoh_publishers:
        zenoh_publishers[target_topic] = zenoh_session.declare_publisher(target_topic)

    # 로봇 쪽에 구현된 로직(robot_agent_test.py)에 맞춰 딕셔너리를 JSON 문자열로 변환합니다.
    json_str = json.dumps({
        "x": cmd.target_x,
        "y": cmd.target_y
    })

    # ROS 2의 std_msgs/String 구조체 규격(CDR)에 맞게 텍스트 뒤에 널 문자(\x00)를 붙입니다.
    utf8_bytes = json_str.encode("utf-8") + b"\x00"

    # ROS 2 std_msgs/msg/String CDR 직렬화 헤더
    # FastAPI는 ROS 패키지가 없기 때문에, 문자열 데이터 앞단에 직접 CDR 헤더(4바이트)와 페이로드의 길이(4바이트)를 바이너리로 붙여줍니다. 
    # 이렇게 조작하여 쏘면 수신하는 로봇단의 ROS 2 시스템은 이를 정상적인 String 메시지로 착각하고 수신하게 됩니다.
    cdr_header = b"\x00\x01\x00\x00"
    length_prefix = struct.pack("<I", len(utf8_bytes))
    cdr_payload = cdr_header + length_prefix + utf8_bytes

    # 완성된 바이트 데이터를 Zenoh를 통해 전송합니다.
    zenoh_publishers[target_topic].put(cdr_payload)

    print(
        f" -> GOAL TX: {target_topic} "
        f"payload={json_str}"
    )

    return {
        "status": "SUCCESS",
        "topic": target_topic,
        "payload": json_str,
    }



# 방화벽 관리를 위해 특정 디바이스의 IP를 담아올 모델 구조입니다.
class DevicePayload(BaseModel):
    ip: str


# 현재 네트워크에 연결된 기기 상태와 방화벽 목록을 리턴하는 GET API입니다. (네트워크 보안 메뉴에서 사용)
@app.get("/api/connections")
async def get_connections():
    return {"devices": device_snapshot()}


# 특정 IP의 접속을 차단하라는 요청을 처리하는 POST API입니다.
@app.post("/api/connections/block")
async def block_connection(payload: DevicePayload):
    try:
        ip = _valid_ip(payload.ip)
        seen_devices.add(ip)
        # 시스템 방화벽에 차단 룰(REJECT)을 주입합니다.
        _firewall("block", ip)
        return {"status": "SUCCESS", "ip": ip, "devices": device_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 특정 IP의 차단을 해제하라는 요청을 처리하는 POST API입니다.
@app.post("/api/connections/allow")
async def allow_connection(payload: DevicePayload):
    try:
        ip = _valid_ip(payload.ip)
        seen_devices.add(ip)
        # 시스템 방화벽에서 룰을 제거하여 다시 Zenoh 통신이 가능하도록 허용합니다.
        _firewall("allow", ip)
        return {"status": "SUCCESS", "ip": ip, "devices": device_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Dashboard WebSocket
# ============================================================
# 프론트엔드가 접속하여 실시간 텔레메트리(위치 정보 등) 데이터를 스트리밍 받기 위한 WebSocket 엔드포인트입니다.
@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    # 클라이언트가 접속하면 ConnectionManager(manager)에 등록합니다.
    await manager.connect(websocket)
    try:
        while True:
            # 연결을 유지하기 위한 무한 루프입니다. 서버는 받기만 하고, 전송 작업은 telemetry 수신 콜백 쪽(manager.broadcast)에서 처리합니다.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# 관리자가 웹에서 조이스틱을 움직여 로봇을 직접 수동 조작(Teleoperation)할 때 사용하는 WebSocket 연결입니다.
@app.websocket("/ws/cmd_vel")
async def cmd_vel_websocket(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            # 프론트엔드 조이스틱에서 날아오는 직진/회전 속도(JSON) 데이터를 지속적으로 수신합니다.
            data = await websocket.receive_json()

            robot_id = str(data.get("robot_id", "")).strip()
            linear_x = float(data.get("linear_x", 0.0))
            angular_z = float(data.get("angular_z", 0.0))

            # 해킹이나 잘못된 입력(예: robot_id가 'robot1' 형태가 아닌 경우)을 걸러냅니다.
            if not re.fullmatch(r"robot[0-9]+", robot_id):
                continue

            # 테스트 중 과도한 속도 명령 방지
            # 조이스틱이 오작동하더라도 맨 위에서 설정한 최대 속도(CMD_VEL_MAX)를 넘지 못하도록 클램핑(제한)합니다. 매우 중요한 안전장치입니다.
            linear_x = max(-CMD_VEL_MAX_LINEAR, min(CMD_VEL_MAX_LINEAR, linear_x))
            angular_z = max(-CMD_VEL_MAX_ANGULAR, min(CMD_VEL_MAX_ANGULAR, angular_z))

            if zenoh_session is None:
                continue

            # 보내야 할 토픽의 이름 (예: "robot2/cmd_vel")
            topic = f"{robot_id}/cmd_vel"

            if topic not in zenoh_publishers:
                zenoh_publishers[topic] = zenoh_session.declare_publisher(topic)

            # 위에서 설명한 직렬화 함수를 이용해 파이썬 숫자들을 ROS 2의 TwistStamped 바이트 구조체(CDR)로 변환합니다.
            payload = make_twist_stamped_cdr(
                linear_x,
                angular_z
            )

            # 변환된 바이트를 로봇에게 전송하여 즉각적으로 모터를 굴리도록 만듭니다.
            zenoh_publishers[topic].put(payload)

    except WebSocketDisconnect:
        # 조이스틱 연결(웹소켓)이 끊겼을 때 발생하는 예외 처리입니다.
        pass

    except Exception as e:
        print(f"CMD_VEL WebSocket Error: {e}")

    finally:
        # 연결 끊기면 정지 명령
        # 이 부분이 가장 중요한 페일세이프(Fail-Safe) 로직입니다! 
        # 브라우저 창이 닫히거나 인터넷이 끊겨서 웹소켓 연결이 해제되면, 로봇이 마지막 속도 그대로 계속 폭주(직진)하는 것을 막기 위해 강제로 속도를 '0(정지)'으로 쏴줍니다.
        try:
            if 'robot_id' in locals() and robot_id and zenoh_session:
                topic = f"{robot_id}/cmd_vel"

                if topic not in zenoh_publishers:
                    zenoh_publishers[topic] = zenoh_session.declare_publisher(topic)

                zenoh_publishers[topic].put(
                    make_twist_stamped_cdr(0.0, 0.0)
                )
        except Exception:
            pass