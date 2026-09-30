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
    help="OMX Robot ID (ex: omx1)",
)

parser.add_argument(
    "--broker-ip",
    required=True,
    help="Main PC MQTT Broker IP",
)

parser.add_argument(
    "--broker-port",
    type=int,
    default=1883,
    help="MQTT Broker Port",
)

args = parser.parse_args()


robot_id = args.robot_id
broker_ip = args.broker_ip
broker_port = args.broker_port


# =============================================================
# MQTT
# =============================================================

client = mqtt.Client()


# 현재 작업
current_job_id = None


# =============================================================
# 공통 Publish
# =============================================================


def publish(topic, payload):

    message = json.dumps(payload)

    client.publish(
        topic,
        message,
    )

    print(f"[MQTT] Published {topic}: " f"{payload}")


# =============================================================
# Main -> OMX 명령 수신
# =============================================================


def on_command(data):

    global current_job_id

    current_job_id = data["job_id"]
    items = data["items"]

    print()
    print("==========================")
    print("New OMX Command")
    print("==========================")
    print(f"Job ID : {current_job_id}")
    print(f"Items  : {items}")
    print("==========================")

    # =========================================================
    # 여기서 실제 로봇팔 동작 시작
    # =========================================================

    print("[OMX] Robot arm started")

    # Main에게 작업 시작 응답
    send_ack(
        current_job_id,
        True,
    )


# =============================================================
# OMX -> Main
# =============================================================


def send_ack(
    job_id,
    accepted=True,
):

    topic = f"{robot_id}/ack"

    payload = {
        "job_id": job_id,
        "accepted": accepted,
    }

    publish(
        topic,
        payload,
    )


def send_progress(
    job_id,
    current,
    total,
):

    topic = f"{robot_id}/progress"

    payload = {
        "job_id": job_id,
        "current": current,
        "total": total,
    }

    publish(
        topic,
        payload,
    )


def send_result(
    job_id,
    success,
    message="",
):

    topic = f"{robot_id}/result"

    payload = {
        "job_id": job_id,
        "success": success,
        "message": message,
    }

    publish(
        topic,
        payload,
    )


def send_status():

    topic = f"{robot_id}/status"

    payload = {
        "state": "online",
    }

    publish(
        topic,
        payload,
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

    command_topic = f"{robot_id}/command"

    client.subscribe(command_topic)

    print(f"[MQTT] Subscribe: " f"{command_topic}")

    # 접속 직후 자신의 존재 알림
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
# Main
# =============================================================

print("==========================")
print("OMX MQTT Client")
print("==========================")
print(f"Robot ID   : {robot_id}")
print(f"Broker IP  : {broker_ip}")
print(f"Broker Port: {broker_port}")
print("==========================")


client.connect(
    broker_ip,
    broker_port,
    60,
)

client.loop_start()


# =============================================================
# Heartbeat
# =============================================================

try:

    while True:

        send_status()

        time.sleep(2)

except KeyboardInterrupt:

    print("[OMX] Stopping...")

finally:

    client.loop_stop()
    client.disconnect()
