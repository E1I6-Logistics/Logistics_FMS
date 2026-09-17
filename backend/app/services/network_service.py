from __future__ import annotations

import ipaddress
import subprocess

from ..config import KNOWN_DEVICES
from ..config import ROBOT_MODE


# ============================================================
# Runtime 상태
# ============================================================

blocked_devices: set[str] = set()

seen_devices: set[str] = set(
    KNOWN_DEVICES.keys()
)


# ============================================================
# IP 검증
# ============================================================

def valid_ip(
    ip: str,
) -> str:

    return str(
        ipaddress.ip_address(ip)
    )


# ============================================================
# Linux socket 조회
# ============================================================

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

def zenoh_peers() -> set[str]:

    peers: set[str] = set()

    for line in _run_ss().splitlines():

        columns = line.split()

        if len(columns) < 5:
            continue

        if columns[0] != "ESTAB":
            continue

        local_addr = columns[3]

        peer_addr = columns[4]

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

        peers.add(ip)

    seen_devices.update(
        peers
    )

    return peers


# ============================================================
# Firewall
# ============================================================

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

def device_snapshot() -> list[dict]:

    connected = set(KNOWN_DEVICES) if ROBOT_MODE == "simulation" else zenoh_peers()

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