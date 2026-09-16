from __future__ import annotations

import asyncio

from contextlib import (
    asynccontextmanager,
)

from fastapi import FastAPI

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from .config import (
    CORS_ORIGINS,
)

from .database.database import (
    close_db,
    init_db,
)

from .routers.commands import (
    router as commands_router,
)

from .routers.connections import (
    router as connections_router,
)

from .routers.map import (
    router as map_router,
)

from .routers.robots import (
    router as robots_router,
)

from .routers.websocket import (
    router as websocket_router,
)

from .services.map_service import (
    load_map_metadata,
)

from .services.route_graph import (
    graph_summary,
)

from .services.ros_gateway import (
    ros_gateway,
)

from .services.zenoh_service import (
    start_zenoh,
    stop_zenoh,
)

KNOWN_DEVICES = {
    "10.10.141.221": "robot1",
    "10.10.141.226": "robot2",
    "10.10.141.246": "robot3",
}
blocked_devices = set()
seen_devices = set(KNOWN_DEVICES.keys())

def _valid_ip(ip: str) -> str:
    return str(ipaddress.ip_address(ip))

def _run_ss():
    result = subprocess.run(["ss", "-Hnt"], capture_output=True, text=True, check=False)
    return result.stdout

def _zenoh_peers():
    peers = set()
    for line in _run_ss().splitlines():
        cols = line.split()
        if len(cols) < 5 or cols[0] != "ESTAB":
            continue
        local_addr, peer_addr = cols[3], cols[4]
        if not local_addr.endswith(":7447"):
            continue
        ip = peer_addr.rsplit(":", 1)[0].strip("[]")
        if ip not in ("127.0.0.1", "::1"):
            peers.add(ip)
    seen_devices.update(peers)
    return peers

def _firewall(action: str, ip: str):
    ip = _valid_ip(ip)
    base = ["sudo", "iptables"]
    rule = ["INPUT", "-s", ip, "-p", "tcp", "--dport", "7447", "-j", "REJECT"]
    if action == "block":
        check = subprocess.run(base + ["-C"] + rule, capture_output=True)
        if check.returncode != 0:
            subprocess.run(base + ["-I"] + rule, check=True)
        blocked_devices.add(ip)
    elif action == "allow":
        while subprocess.run(base + ["-C"] + rule, capture_output=True).returncode == 0:
            subprocess.run(base + ["-D"] + rule, check=True)
        blocked_devices.discard(ip)

def device_snapshot():
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
# FastAPI Lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    # ========================================================
    # PostgreSQL
    # ========================================================

    await init_db()

    print(
        " -> Database 초기화 완료"
    )

    # ========================================================
    # Map
    # ========================================================

    try:

        info = load_map_metadata()

        print(
            " -> Map 로드 완료: "
            f"{info['image_name']} "
            f"({info['width']}x"
            f"{info['height']}, "
            f"resolution="
            f"{info['resolution']})"
        )

    except Exception as exc:

        print(
            " -> [WARN] "
            "Map 로드 실패: "
            f"{exc}"
        )

    # ========================================================
    # Route Graph
    # ========================================================

    try:

        summary = graph_summary()

        print(
            " -> Route Graph 로드 완료: "
            f"nodes={summary['nodes']}, "
            f"edges={summary['edges']}, "
            "edges_without_coordinates="
            f"{summary['edges_without_coordinates']}"
        )

    except Exception as exc:

        print(
            " -> [WARN] "
            "Route Graph 로드 실패: "
            f"{exc}"
        )

    # ========================================================
    # Native Zenoh
    #
    # FMS 전용 데이터
    # telemetry / heartbeat / status 등
    # ========================================================

    start_zenoh(
        asyncio.get_running_loop()
    )

    # ========================================================
    # ROS Gateway
    #
    # Topic / Service / Action
    # ========================================================

    try:

        ros_gateway.start()

    except Exception as exc:

        print(
            " -> [WARN] "
            "ROS Gateway 시작 실패: "
            f"{exc}"
        )

    # ========================================================
    # FastAPI Start
    # ========================================================

    try:

        yield

    finally:

        # ====================================================
        # Shutdown
        # ====================================================

        try:

            ros_gateway.stop()

        except Exception as exc:

            print(
                " -> [WARN] "
                "ROS Gateway 종료 오류: "
                f"{exc}"
            )

        try:

            stop_zenoh()

        except Exception as exc:

            print(
                " -> [WARN] "
                "Zenoh 종료 오류: "
                f"{exc}"
            )

        try:

            await close_db()

        except Exception as exc:

            print(
                " -> [WARN] "
                "Database 종료 오류: "
                f"{exc}"
            )

        print(
            " -> FMS Backend 종료 완료"
        )


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(

    title=(
        "E1I6 Logistics FMS API"
    ),

    version="2.0.0",

    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(

    CORSMiddleware,

    allow_origins=
        CORS_ORIGINS,

    allow_credentials=
        False,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ],
)


# ============================================================
# Routers
# ============================================================

app.include_router(
    map_router
)

app.include_router(
    robots_router
)

app.include_router(
    commands_router
)

app.include_router(
    connections_router
)

app.include_router(
    websocket_router
)


# ============================================================
# Root
# ============================================================

@app.get("/")
async def root():

    print(
        f" -> GOAL TX: {target_topic} "
        f"payload={json_str}"
    )

    return {

        "service":
            "E1I6 Logistics FMS API",

        "version":
            "2.0.0",

        "status":
            "ok",

        "architecture":
            "Native Zenoh + ROS Gateway",

        "docs":
            "/docs",
    }



class DevicePayload(BaseModel):
    ip: str


@app.get("/api/connections")
async def get_connections():
    return {"devices": device_snapshot()}


@app.post("/api/connections/block")
async def block_connection(payload: DevicePayload):
    try:
        ip = _valid_ip(payload.ip)
        seen_devices.add(ip)
        _firewall("block", ip)
        return {"status": "SUCCESS", "ip": ip, "devices": device_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/connections/allow")
async def allow_connection(payload: DevicePayload):
    try:
        ip = _valid_ip(payload.ip)
        seen_devices.add(ip)
        _firewall("allow", ip)
        return {"status": "SUCCESS", "ip": ip, "devices": device_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Health Check
# ============================================================

@app.get("/health")
async def health():

    from .services.zenoh_service import (
        status_snapshot,
    )

    return {

        "status":
            "ok",

        "ros_gateway":
            ros_gateway.status_snapshot(),

        "native_zenoh":
            status_snapshot(),
    }
