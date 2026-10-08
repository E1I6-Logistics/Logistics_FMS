#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"


# =============================================================
# Argument
# =============================================================

ROBOT_ID=""
BROKER_IP=""
BROKER_PORT="1883"


while [[ $# -gt 0 ]]; do

  case "$1" in

    --robot-id)

      ROBOT_ID="$2"
      shift 2
      ;;

    --broker-ip)

      BROKER_IP="$2"
      shift 2
      ;;

    *)

      echo "알 수 없는 argument: $1"
      exit 1
      ;;

  esac

done


if [[ -z "$ROBOT_ID" ]]; then

  echo "--robot-id가 필요합니다."
  exit 1

fi


if [[ -z "$BROKER_IP" ]]; then

  echo "--broker-ip가 필요합니다."
  exit 1

fi

case "$ROBOT_ID" in
  omx1|omx2|omx3|omx4) ;;
  *)
    echo "--robot-id는 omx1, omx2, omx3, omx4 중 하나여야 합니다." >&2
    exit 1
    ;;
esac


# =============================================================
# Python venv
# =============================================================

if [[ -f .venv/bin/activate ]]; then

  source .venv/bin/activate

else

  source "$HOME/venv/.venv/bin/activate"

fi


# 같은 OMX를 두 번 실행해 동일 Command를 중복 처리하지 않는다.
exec 9>"/tmp/omx_${ROBOT_ID}.lock"
if ! flock -n 9; then
  echo "이미 실행 중인 OMX입니다: $ROBOT_ID" >&2
  exit 1
fi

# 픽업 OMX만 재고·주문 상태를 지우고 대기 상태에서 시작한다.
if [[ "$ROBOT_ID" == "omx1" || "$ROBOT_ID" == "omx2" ]]; then
  bash "$SCRIPT_DIR/omx_new_order.sh" WAIT 0
fi


# =============================================================
# Process PID
# =============================================================

ROLLOUT_PID=""
MQTT_PID=""

CLEANUP_DONE=0


# =============================================================
# 종료 처리
# =============================================================

cleanup() {

  if [[ "$CLEANUP_DONE" -eq 1 ]]; then
    return
  fi

  CLEANUP_DONE=1

  echo
  echo "================================"
  echo "OMX 종료 중..."
  echo "================================"


  if [[ -n "$MQTT_PID" ]]; then

    if kill -0 "$MQTT_PID" 2>/dev/null; then

      echo "MQTT Client 종료"

      kill "$MQTT_PID" \
        2>/dev/null || true

    fi

  fi


  if [[ -n "$ROLLOUT_PID" ]]; then

    if kill -0 "$ROLLOUT_PID" 2>/dev/null; then

      echo "LeRobot Rollout 종료"

      kill "$ROLLOUT_PID" \
        2>/dev/null || true

    fi

  fi


  if [[ -n "$MQTT_PID" ]]; then

    wait "$MQTT_PID" \
      2>/dev/null || true

  fi


  if [[ -n "$ROLLOUT_PID" ]]; then

    wait "$ROLLOUT_PID" \
      2>/dev/null || true

  fi

}


trap cleanup EXIT INT TERM


# =============================================================
# 시작 정보
# =============================================================

echo "================================"
echo "OMX 시작"
echo "================================"
echo "OMX ID      : $ROBOT_ID"
echo "Broker IP   : $BROKER_IP"
echo "Broker Port : $BROKER_PORT"
echo "================================"


# =============================================================
# LeRobot Rollout 실행
# =============================================================

echo
echo "================================"
echo "LeRobot Rollout 시작"
echo "================================"

if [[ "$ROBOT_ID" == "omx1" || "$ROBOT_ID" == "omx2" ]]; then

ROBOT_PORT="${OMX_ROBOT_PORT:-/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_4256A5C6503059384C2E3120FF08242F-if00}"
FRONT_CAMERA_SERIAL="${OMX_FRONT_CAMERA_SERIAL:-920312071050}"
WRIST_CAMERA_PATH="${OMX_WRIST_CAMERA_PATH:-/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-1080p-S1_SN0001-video-index0}"


lerobot-rollout \
  --strategy.type=base \
  --strategy.order_models_file=omx_order_models.json \
  --strategy.auto_restart_on_home=true \
  --strategy.inventory_capacity=8 \
  --strategy.inventory_reset_on_start=false \
  --strategy.keep_alive_when_inventory_empty=true \
  --strategy.home_tolerance=7 \
  --strategy.home_leave_tolerance=12 \
  --strategy.home_hold_s=0.3 \
  --strategy.min_cycle_s=5 \
  --robot.type=omx_follower \
  --robot.port="$ROBOT_PORT" \
  --robot.id=omx_follower_arm \
  --robot.cameras="{front: {type: intelrealsense, serial_number_or_name: '$FRONT_CAMERA_SERIAL', width: 640, height: 480, fps: 30, use_rgb: true, use_depth: false, warmup_s: 5}, wrist: {type: opencv, index_or_path: '$WRIST_CAMERA_PATH', width: 640, height: 480, fps: 30, processing_fps: 30}}" \
  --policy.path=outputs/train/warehouse_all_200_two_cycles_v3_act_250k/checkpoints/150000/pretrained_model \
  --task="Pick up the topmost item, place it in the basket, and return to the initial pose" \
  --fps=30 \
  --duration=0 \
  --interpolation_multiplier=1 \
  --display_data=false &


ROLLOUT_PID=$!


echo "LeRobot PID: $ROLLOUT_PID"

else
  echo "$ROBOT_ID 하차 동작은 아직 구현되지 않아 LeRobot을 시작하지 않습니다."
fi


# =============================================================
# MQTT Client 실행
# =============================================================

echo
echo "================================"
echo "MQTT Client 시작"
echo "================================"


python3 "$SCRIPT_DIR/omx_mqtt_client.py" \
  --robot-id "$ROBOT_ID" \
  --broker-ip "$BROKER_IP" &


MQTT_PID=$!


echo "MQTT PID: $MQTT_PID"


# =============================================================
# Process 감시
# =============================================================

echo
echo "================================"
echo "OMX 실행 중"
echo "================================"


while true; do

  # -----------------------------------------------------------
  # LeRobot 죽음 감지
  # -----------------------------------------------------------

  if [[ -n "$ROLLOUT_PID" ]] && ! kill -0 "$ROLLOUT_PID" 2>/dev/null; then

    echo
    echo "[ERROR] LeRobot Rollout 종료 감지"

    wait "$ROLLOUT_PID" \
      2>/dev/null || true

    exit 1

  fi


  # -----------------------------------------------------------
  # MQTT Client 죽음 감지
  # -----------------------------------------------------------

  if ! kill -0 "$MQTT_PID" 2>/dev/null; then

    echo
    echo "[ERROR] MQTT Client 종료 감지"

    wait "$MQTT_PID" \
      2>/dev/null || true

    exit 1

  fi


  sleep 1

done
