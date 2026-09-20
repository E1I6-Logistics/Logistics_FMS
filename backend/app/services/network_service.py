# Zenoh Peer / Firewall 연결 관리

# 타입 힌트 지연 평가 기능 사용
from __future__ import annotations

# IP 주소 형식 검증 기능 사용
import ipaddress
# Linux 명령 실행 기능 사용
import subprocess

from ..config import KNOWN_DEVICES


# ============================================================
# Runtime 상태
# ============================================================

# 차단된 장치 IP 목록 관리
blocked_devices: set[str] = set()

# 확인된 장치 IP 목록 관리
seen_devices: set[str] = set(
    KNOWN_DEVICES.keys()
)


# ============================================================
# IP 검증
# ============================================================

# 입력 IP 주소 형식 검증 기능
def valid_ip(
    ip: str,
) -> str:

    return str(
        ipaddress.ip_address(ip)
    )


# ============================================================
# Linux socket 조회
# ============================================================

# Linux ss 명령을 이용한 TCP 연결 상태 조회 기능
def _run_ss() -> str:

    result = subprocess.run(
        [
            "ss",
            "-Hnt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    return result.stdout


# ============================================================
# Zenoh 연결 Peer 조회
# ============================================================

# Zenoh 7447 포트에 연결된 Peer IP 조회 기능
def zenoh_peers() -> set[str]:

    peers: set[str] = set()

    # TCP 연결 목록을 한 줄씩 분석
    for line in _run_ss().splitlines():

        columns = line.split()

        if len(columns) < 5:
            continue

        # ESTABLISHED 상태 연결만 사용
        if columns[0] != "ESTAB":
            continue

        local_addr = columns[3]

        peer_addr = columns[4]

        # Zenoh 기본 포트 7447 연결만 사용
        if not local_addr.endswith(
            ":7447"
        ):
            continue

        ip = (
            peer_addr
            .rsplit(":", 1)[0]
            .strip("[]")
        )

        if ip in (
            "127.0.0.1",
            "::1",
        ):
            continue

        # 연결된 Peer IP 목록에 추가
        peers.add(ip)

    seen_devices.update(
        peers
    )

    return peers


# ============================================================
# Firewall
# ============================================================

# 특정 Robot IP의 Zenoh 통신 차단 및 허용 기능
def firewall(
    action: str,
    ip: str,
) -> None:

    ip = valid_ip(ip)

    base = [
        "sudo",
        "iptables",
    ]

    rule = [
        "INPUT",
        "-s",
        ip,
        "-p",
        "tcp",
        "--dport",
        "7447",
        "-j",
        "REJECT",
    ]

    # --------------------------------------------------------
    # Block
    # --------------------------------------------------------

    # iptables 차단 규칙 추가 기능
    if action == "block":

        check = subprocess.run(
            base
            + ["-C"]
            + rule,
            capture_output=True,
        )

        if check.returncode != 0:

            subprocess.run(
                base
                + ["-I"]
                + rule,
                check=True,
            )

        blocked_devices.add(
            ip
        )

        return

    # --------------------------------------------------------
    # Allow
    # --------------------------------------------------------

    # iptables 차단 규칙 제거 기능
    if action == "allow":

        while (
            subprocess.run(
                base
                + ["-C"]
                + rule,
                capture_output=True,
            ).returncode
            == 0
        ):

            subprocess.run(
                base
                + ["-D"]
                + rule,
                check=True,
            )

        blocked_devices.discard(
            ip
        )

        return

    raise ValueError(
        f"지원하지 않는 firewall action: {action}"
    )


# ============================================================
# Frontend 연결 상태
# ============================================================

# Frontend 전달용 장치 연결 상태 목록 생성 기능
def device_snapshot() -> list[dict]:

    # 현재 연결된 Zenoh Peer 목록 조회
    connected = zenoh_peers()

    devices = []

    all_devices = (
        seen_devices
        | blocked_devices
    )

    for ip in sorted(
        all_devices
    ):

        blocked = (
            ip in blocked_devices
        )

        online = (
            ip in connected
            and not blocked
        )

        # 장치별 연결 및 차단 상태 정보 생성
        devices.append(
            {
                "ip": ip,

                "name":
                    KNOWN_DEVICES.get(
                        ip,
                        "Unknown",
                    ),

                "known":
                    ip in KNOWN_DEVICES,

                "connected":
                    online,

                "blocked":
                    blocked,

                "state":
                    (
                        "BLOCKED"
                        if blocked
                        else (
                            "CONNECTED"
                            if online
                            else "OFFLINE"
                        )
                    ),
            }
        )

    return devices