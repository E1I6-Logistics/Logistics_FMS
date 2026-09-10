import asyncio
import io
import json
import re
import struct
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from PIL import Image
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, JSONResponse
from pydantic import BaseModel
import zenoh

from .database.database import (
    init_db,
    upsert_robot_state,
    get_all_robots,
)

# ============================================================
# 경로 설정
# ============================================================
BASE_DIR = Path(__file__).resolve().parents[2]

MAP_DIR = BASE_DIR / "maps"
ROUTE_DIR = BASE_DIR / "routes"

MAP_YAML_PATH = MAP_DIR / "my_map.yaml"
ROUTE_GRAPH_PATH = ROUTE_DIR / "test.geojson"
# ============================================================
# WebSocket 연결 관리자
# ============================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)


manager = ConnectionManager()
zenoh_session = None
zenoh_subscriber = None
loop = None
zenoh_publishers = {}


# ============================================================
# 정적 지도 / Route Graph 유틸
# ============================================================
def load_map_metadata():
    if not MAP_YAML_PATH.exists():
        raise FileNotFoundError(
            f"Map YAML 파일 없음: {MAP_YAML_PATH}"
        )

    with open(MAP_YAML_PATH, "r", encoding="utf-8") as f:
        map_yaml = yaml.safe_load(f)

    image_name = map_yaml["image"]

    image_path = Path(image_name)

    if not image_path.is_absolute():
        image_path = MAP_DIR / image_name

    if not image_path.exists():
        raise FileNotFoundError(
            f"Map 이미지 파일 없음: {image_path}"
        )

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
    if not ROUTE_GRAPH_PATH.exists():
        raise FileNotFoundError(
            f"Route Graph 파일이 없습니다: {ROUTE_GRAPH_PATH}"
        )

    with ROUTE_GRAPH_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def pgm_to_png_bytes() -> bytes:
    map_info = load_map_metadata()
    image_path = Path(map_info["image_path"])

    with Image.open(image_path) as img:
        # 지도 원본의 grayscale 값을 그대로 유지해서 PNG로만 변환한다.
        converted = img.convert("L")
        output = io.BytesIO()
        converted.save(output, format="PNG")
        return output.getvalue()


# ============================================================
# Zenoh 텔레메트리 수신
# ============================================================
def zenoh_telemetry_listener(sample):
    try:
        topic = str(sample.key_expr)
        raw_bytes = sample.payload.to_bytes()

        # ROS2 std_msgs/String CDR 데이터에서 JSON 문자열 부분 추출
        text = raw_bytes.decode("utf-8", errors="ignore")
        json_match = re.search(r"\{.*\}", text)
        if not json_match:
            return

        data = json.loads(json_match.group(0))

        parts = [p for p in topic.split("/") if p and p != "rt"]
        robot_id = data.get("robot_id", parts[0] if parts else "robot1")

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

        if loop is not None:
            asyncio.run_coroutine_threadsafe(
                upsert_robot_state(robot_id, x, y, yaw, battery, status),
                loop,
            )
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "telemetry", "data": telemetry}),
                loop,
            )

    except Exception as e:
        print(f"Zenoh 파싱 에러: {e}")


# ============================================================
# FastAPI lifespan
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop, zenoh_session, zenoh_subscriber

    loop = asyncio.get_running_loop()
    await init_db()

    # 맵/그래프 파일 확인
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

    # Zenoh가 잠시 꺼져 있어도 지도 UI 자체는 실행 가능하도록 처리
    try:
        conf = zenoh.Config()
        conf.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7447"]')
        zenoh_session = zenoh.open(conf)
        zenoh_subscriber = zenoh_session.declare_subscriber(
            "**/telemetry", zenoh_telemetry_listener
        )
        print(f" -> FMS Zenoh 수신 세션 활성화 완료! (ZID: {zenoh_session.zid()})")
    except Exception as e:
        zenoh_session = None
        zenoh_subscriber = None
        print(f" -> [WARN] Zenoh 연결 실패. 웹 지도/API만 실행합니다: {e}")

    yield

    if zenoh_subscriber is not None:
        zenoh_subscriber.undeclare()
    if zenoh_session is not None:
        zenoh_session.close()


app = FastAPI(title="Local FMS / ACS Hub", lifespan=lifespan)

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
@app.get("/api/map/info")
async def get_map_info():
    try:
        info = load_map_metadata()
        # 브라우저가 직접 서버 내부 파일 경로를 알 필요는 없으므로 제거
        info.pop("yaml_path", None)
        info.pop("image_path", None)
        info["image_url"] = "/api/map/image"
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/map/image")
async def get_map_image():
    try:
        return Response(content=pgm_to_png_bytes(), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/route/graph")
async def get_route_graph():
    try:
        return load_route_graph()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Robot API
# ============================================================
@app.get("/api/robots")
async def fetch_robots():
    robots = await get_all_robots()
    for r in robots:
        if "updated_at" in r and r["updated_at"]:
            r["updated_at"] = r["updated_at"].isoformat()
    return robots


class CommandPayload(BaseModel):
    robot_id: str
    target_x: float
    target_y: float


@app.post("/api/command/goal")
async def send_goal(cmd: CommandPayload):
    if not zenoh_session:
        return {"status": "ERROR", "message": "Zenoh session inactive"}

    target_topic = f"{cmd.robot_id}/goal"

    if target_topic not in zenoh_publishers:
        zenoh_publishers[target_topic] = zenoh_session.declare_publisher(target_topic)

    json_str = json.dumps({"x": cmd.target_x, "y": cmd.target_y})
    utf8_bytes = json_str.encode("utf-8") + b"\x00"

    # ROS 2 std_msgs/msg/String CDR 직렬화
    cdr_header = b"\x00\x01\x00\x00"
    length_prefix = struct.pack("<I", len(utf8_bytes))
    cdr_payload = cdr_header + length_prefix + utf8_bytes

    zenoh_publishers[target_topic].put(cdr_payload)

    return {
        "status": "SUCCESS",
        "topic": target_topic,
        "payload": json_str,
    }


# ============================================================
# Dashboard WebSocket
# ============================================================
@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 연결 유지. 프론트에서 메시지를 보내지 않아도 WebSocket은 열린 상태로 유지됨.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

