import argparse
import json
import time

import paho.mqtt.client as mqtt

# =============================================================
# Argument
# =============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--robot-id",
    required=True,
)

parser.add_argument(
    "--broker-ip",
    required=True,
)

parser.add_argument(
    "--broker-port",
    type=int,
    default=1883,
)

args = parser.parse_args()


robot_id = args.robot_id
broker_ip = args.broker_ip
broker_port = args.broker_port


# =============================================================
# MQTT
# =============================================================

client = mqtt.Client()

current_job_id = None


# =============================================================
# Publish
# =============================================================


def publish(topic, payload):

    message = json.dumps(payload)

    client.publish(
        topic,
        message,
    )

    print(f"[SEND] {topic}: {payload}")


# =============================================================
# OMX -> Main
# =============================================================


def send_status():

    publish(
        f"{robot_id}/status",
        {
            "state": "online",
        },
    )


def send_ack(
    job_id,
    accepted=True,
):

    publish(
        f"{robot_id}/ack",
        {
            "job_id": job_id,
            "accepted": accepted,
        },
    )


def send_progress(
    job_id,
    current,
    total,
):

    publish(
        f"{robot_id}/progress",
        {
            "job_id": job_id,
            "current": current,
            "total": total,
        },
    )


def send_result(
    job_id,
    success,
    message="",
):

    publish(
        f"{robot_id}/result",
        {
            "job_id": job_id,
            "success": success,
            "message": message,
        },
    )


# =============================================================
# Command 처리
# =============================================================


def on_command(data):

    global current_job_id

    current_job_id = data["job_id"]
    items = data["items"]

    print()
    print("==============================")
    print("COMMAND RECEIVED")
    print("==============================")
    print(f"Job   : {current_job_id}")
    print(f"Items : {items}")
    print("==============================")

    # 작업 시작
    send_ack(
        current_job_id,
        True,
    )

    # =========================================================
    # 테스트용 가짜 작업
    #
    # 나중에는 이 부분을 실제 OMX 로봇팔 동작으로 교체
    # =========================================================

    total = sum(items.values())

    for current in range(
        1,
        total + 1,
    ):

        time.sleep(1)

        send_progress(
            current_job_id,
            current,
            total,
        )

    # 작업 성공
    send_result(
        current_job_id,
        True,
        "Test completed",
    )


# =============================================================
# MQTT Callback
# =============================================================


def on_connect(
    client,
    userdata,
    flags,
    rc,
):

    print(f"[MQTT] Connected: {rc}")

    topic = f"{robot_id}/command"

    client.subscribe(topic)

    print(f"[MQTT] Subscribe: {topic}")

    send_status()


def on_message(
    client,
    userdata,
    msg,
):

    try:

        data = json.loads(msg.payload.decode())

    except Exception as e:

        print(f"[MQTT] JSON Error: {e}")

        return

    if msg.topic == f"{robot_id}/command":

        on_command(data)


client.on_connect = on_connect
client.on_message = on_message


# =============================================================
# 실행
# =============================================================

print("==============================")
print("OMX MQTT Client")
print("==============================")
print(f"Robot ID    : {robot_id}")
print(f"Broker      : {broker_ip}")
print(f"Broker Port : {broker_port}")
print("==============================")


client.connect(
    broker_ip,
    broker_port,
    60,
)

client.loop_start()


try:

    while True:

        send_status()

        time.sleep(2)


except KeyboardInterrupt:

    print("Stopping...")


finally:

    client.loop_stop()
    client.disconnect()
