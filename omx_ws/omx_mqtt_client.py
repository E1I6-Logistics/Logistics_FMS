#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt


# =============================================================
# Argument
# =============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--robot-id",
    required=True,
    help="OMX ID (예: omx1)",
)

parser.add_argument(
    "--broker-ip",
    required=True,
    help="FMS MQTT Broker IP",
)

args = parser.parse_args()

robot_id = args.robot_id
broker_ip = args.broker_ip
broker_port = 1883

PICKUP_ITEMS = {
    "omx1": ("A", "B"),
    "omx2": ("C", "D"),
}
WORKSTATION_IDS = ("omx3", "omx4")

if robot_id not in PICKUP_ITEMS and robot_id not in WORKSTATION_IDS:
    parser.error("robot-id는 omx1, omx2, omx3, omx4 중 하나여야 합니다.")


# =============================================================
# Path
# =============================================================

directory = Path(__file__).resolve().parent

state_path = Path(
    os.environ.get(
        "OMX_INVENTORY_STATE_PATH",
        "~/.local/state/lerobot/omx_inventory.json",
    )
).expanduser()

new_order_script = directory / "omx_new_order.sh"


# =============================================================
# MQTT / OMX 상태
# =============================================================

client = mqtt.Client()

job_lock = threading.Lock()

current_job_id = None
current_state = "NOT_IMPLEMENTED" if robot_id in WORKSTATION_IDS else "IDLE"
current_orders = None


# =============================================================
# MQTT Publish
# =============================================================

def publish(topic, payload):
    message = json.dumps(payload)

    client.publish(
        topic,
        message,
    )

    print(
        f"[SEND] {topic}: {payload}",
        flush=True,
    )


def send_status():
    publish(
        f"{robot_id}/status",
        {
            "state": current_state,
        },
    )


def send_ack(job_id, accepted=True):
    publish(
        f"{robot_id}/ack",
        {
            "job_id": job_id,
            "accepted": accepted,
        },
    )


def send_progress(job_id, current, total):
    publish(
        f"{robot_id}/progress",
        {
            "job_id": job_id,
            "current": current,
            "total": total,
        },
    )


def send_result(job_id, success, message=""):
    publish(
        f"{robot_id}/result",
        {
            "job_id": job_id,
            "success": success,
            "message": message,
        },
    )


# =============================================================
# FMS items -> OMX 주문 변환
# =============================================================

def make_orders(items):

    if not isinstance(items, dict):
        raise ValueError(
            "items는 객체 형식이어야 합니다."
        )

    allowed_items = PICKUP_ITEMS.get(robot_id)

    if allowed_items is None:
        raise ValueError("작업대 하차 동작은 아직 구현되지 않았습니다.")

    if any(item not in allowed_items for item in items):
        raise ValueError(f"{robot_id}에서 처리하지 않는 품목이 있습니다.")

    orders = []

    for item in allowed_items:

        quantity = items.get(item, 0)

        if isinstance(quantity, bool):
            raise ValueError(
                f"{item} 수량이 올바르지 않습니다."
            )

        try:
            quantity = int(quantity)

        except (TypeError, ValueError):
            raise ValueError(
                f"{item} 수량이 올바르지 않습니다."
            )

        if quantity < 0 or quantity > 8:
            raise ValueError(
                f"{item} 수량은 0~8이어야 합니다."
            )

        if quantity > 0:
            orders.append(
                (item, quantity)
            )

    if not orders:
        raise ValueError(
            f"실행할 {'/'.join(allowed_items)} 주문이 없습니다."
        )

    return orders


# =============================================================
# 시간 출력
# =============================================================

def elapsed(seconds):

    h, rem = divmod(
        max(0, int(seconds)),
        3600,
    )

    m, s = divmod(
        rem,
        60,
    )

    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


# =============================================================
# OMX 실제 주문 실행
# =============================================================

def execute_orders(job_id, orders):

    started = time.monotonic()

    total_quantity = sum(
        qty
        for _, qty in orders
    )

    completed_before = 0

    print(
        "[ORDER] 주문 순서: "
        + " -> ".join(
            f"{item} {qty}개"
            for item, qty in orders
        ),
        flush=True,
    )

    for index, (item, qty) in enumerate(
        orders,
        1,
    ):

        # omx2의 물리 모델은 로컬 A/B 명령을 각각 C/D 품목에 사용한다.
        local_item = {"C": "A", "D": "B"}.get(item, item)

        print(
            f"[ORDER] [{index}/{len(orders)}] "
            f"{item} {qty}개 등록",
            flush=True,
        )

        # 기존 OMX 주문 등록 스크립트 사용
        result = subprocess.run(
            [
                "bash",
                str(new_order_script),
                local_item,
                str(qty),
            ]
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"{item} 주문 등록 실패"
            )

        if not state_path.exists():
            raise RuntimeError(
                f"상태 파일이 없습니다: {state_path}"
            )

        accepted = json.loads(
            state_path.read_text()
        )

        token = accepted[
            "order_started_at_epoch"
        ]

        last_progress = None

        # -----------------------------------------------------
        # OMX inventory 상태 감시
        # -----------------------------------------------------

        while True:

            state = json.loads(
                state_path.read_text()
            )

            current_order = (
                state.get("order_item"),
                state.get("order_quantity"),
                state.get(
                    "order_started_at_epoch"
                ),
            )

            expected_order = (
                local_item,
                qty,
                token,
            )

            if current_order != expected_order:
                raise RuntimeError(
                    "주문 상태가 외부에서 변경되었습니다."
                )

            done = int(
                state["order_completed"]
            )

            remaining = int(
                state["remaining"]
            )

            total_completed = (
                completed_before + done
            )

            # 진행 상태가 바뀌었을 때만 progress 전송
            if total_completed != last_progress:

                send_progress(
                    job_id,
                    total_completed,
                    total_quantity,
                )

                print(
                    f"[ORDER] {item} "
                    f"완료={done}/{qty}, "
                    f"전체="
                    f"{total_completed}/"
                    f"{total_quantity}",
                    flush=True,
                )

                last_progress = (
                    total_completed
                )

            # 해당 품목 작업 완료
            if remaining == 0:

                if done != qty:
                    raise RuntimeError(
                        f"{item} 완료 수량 불일치: "
                        f"완료={done}, 주문={qty}"
                    )

                print(
                    f"[ORDER] "
                    f"{item} 주문 완료",
                    flush=True,
                )

                completed_before += qty

                break

            time.sleep(0.5)

    print(
        "[ORDER] 전체 주문 완료 | "
        f"총 소요시간: "
        f"{elapsed(time.monotonic() - started)}",
        flush=True,
    )


def execute_unload(job_id, items):
    # omx3/omx4의 실제 하차 동작을 구현할 자리. 구현 전에는 호출하지 않는다.
    pass


# =============================================================
# 실제 작업 Thread
# =============================================================

def run_job(job_id, orders):

    global current_job_id
    global current_state
    global current_orders

    success = False
    result_message = ""

    try:

        current_state = "WORKING"

        send_status()

        execute_orders(
            job_id,
            orders,
        )

        success = True

    except Exception as exc:

        print(
            f"[ORDER] 작업 실패: {exc}",
            flush=True,
        )

        result_message = str(exc)

    finally:
        # 작업이 끝난 뒤 상태를 먼저 정리해야 Result 직후의 다음 Command를 받을 수 있다.
        current_job_id = None
        current_orders = None
        current_state = "IDLE"

        try:
            send_status()
        finally:
            job_lock.release()

        if success:
            print(
                f"[ORDER] Job 완료: {job_id}",
                flush=True,
            )

        send_result(
            job_id,
            success,
            "Order completed" if success else result_message,
        )


# =============================================================
# MQTT Command 처리
# =============================================================

def on_command(data):

    global current_job_id
    global current_state
    global current_orders

    job_id = data.get("job_id")
    items = data.get("items")

    if not job_id:

        print(
            "[MQTT] job_id가 없습니다.",
            flush=True,
        )

        return

    if robot_id in WORKSTATION_IDS:
        print(
            f"[MQTT] {robot_id} 하차 동작은 아직 구현되지 않았습니다.",
            flush=True,
        )
        send_ack(job_id, False)
        return

    print()
    print("==============================")
    print("COMMAND RECEIVED")
    print("==============================")
    print(f"Job   : {job_id}")
    print(f"Items : {items}")
    print("==============================")


    # =========================================================
    # 현재 실행 중인 job과 동일
    # =========================================================

    if current_job_id == job_id:

        try:
            same_orders = tuple(make_orders(items)) == current_orders
        except ValueError:
            same_orders = False

        if not same_orders:
            print(
                f"[MQTT] 같은 Job ID에 다른 주문이 들어왔습니다: {job_id}",
                flush=True,
            )
            send_ack(job_id, False)
            return

        print(
            f"[MQTT] 이미 실행 중인 Job: "
            f"{job_id}",
            flush=True,
        )

        send_ack(
            job_id,
            True,
        )

        return


    # =========================================================
    # 다른 작업 진행 중
    # =========================================================

    if not job_lock.acquire(
        blocking=False
    ):

        print(
            f"[MQTT] OMX BUSY - "
            f"주문 거절: {job_id}",
            flush=True,
        )

        send_ack(
            job_id,
            False,
        )

        return


    # =========================================================
    # 주문 검증
    # =========================================================

    try:

        orders = make_orders(
            items
        )

    except Exception as exc:

        print(
            f"[MQTT] 주문 검증 실패: "
            f"{exc}",
            flush=True,
        )

        send_ack(
            job_id,
            False,
        )

        send_result(
            job_id,
            False,
            str(exc),
        )

        job_lock.release()

        return


    # =========================================================
    # 주문 접수
    # =========================================================

    current_job_id = job_id
    current_orders = tuple(orders)
    current_state = "WORKING"

    send_ack(
        job_id,
        True,
    )

    # MQTT callback이 막히지 않도록
    # 실제 OMX 작업은 별도 Thread에서 실행
    worker = threading.Thread(
        target=run_job,
        args=(
            job_id,
            orders,
        ),
        daemon=True,
    )

    worker.start()


# =============================================================
# MQTT Callback
# =============================================================

def on_connect(
    client,
    userdata,
    flags,
    rc,
):

    print(
        f"[MQTT] Connected: {rc}",
        flush=True,
    )

    topic = (
        f"{robot_id}/command"
    )

    client.subscribe(
        topic
    )

    print(
        f"[MQTT] Subscribe: "
        f"{topic}",
        flush=True,
    )

    send_status()


def on_disconnect(
    client,
    userdata,
    rc,
):

    print(
        f"[MQTT] Disconnected: {rc}",
        flush=True,
    )


def on_message(
    client,
    userdata,
    msg,
):

    try:

        data = json.loads(
            msg.payload.decode()
        )

    except Exception as exc:

        print(
            f"[MQTT] JSON Error: {exc}",
            flush=True,
        )

        return

    if msg.topic == (
        f"{robot_id}/command"
    ):

        on_command(
            data
        )


client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message


# =============================================================
# Main
# =============================================================

def main():

    print("==============================")
    print("OMX MQTT Client")
    print("==============================")
    print(f"OMX ID      : {robot_id}")
    print(f"Broker      : {broker_ip}")
    print(f"Broker Port : {broker_port}")
    print(f"Order Script: {new_order_script}")
    print(f"State File  : {state_path}")
    print("==============================")

    if robot_id in PICKUP_ITEMS and not new_order_script.exists():

        raise FileNotFoundError(
            f"omx_new_order.sh가 없습니다: "
            f"{new_order_script}"
        )

    client.connect(
        broker_ip,
        broker_port,
        60,
    )

    client.loop_start()

    try:

        while True:

            # FMS 연결 확인용 heartbeat
            send_status()

            time.sleep(2)

    except KeyboardInterrupt:

        print(
            "\n[MQTT] Stopping...",
            flush=True,
        )

    finally:

        client.loop_stop()

        client.disconnect()


if __name__ == "__main__":
    main()
