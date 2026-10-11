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

# =============================================================
# 공통 실행 파일에서 OMX별 학습 모델 선택
#
# 실제 MQTT 주문 이름:
#   omx1: A/B -> 재고 A/B (모델만 교체: A->B, B->A)
#   omx2: C/D -> 재고 A/B (C->C 모델, D->D 모델)
# omx_mqtt_client.py는 기존 C->A, D->B 변환을 그대로 사용한다.
# =============================================================

ORDER_MODELS_FILE=""
POLICY_PATH=""

if [[ "$ROBOT_ID" == "omx1" || "$ROBOT_ID" == "omx2" ]]; then
  # 원본 모델 설정 JSON을 덮어쓰지 않는다.
  MODEL_CONFIG_DIR="${OMX_MODEL_CONFIG_DIR:-$HOME/.local/state/lerobot}"
  mkdir -p "$MODEL_CONFIG_DIR"
  ORDER_MODELS_FILE="$MODEL_CONFIG_DIR/omx_order_models_${ROBOT_ID}_active.json"

  if [[ "$ROBOT_ID" == "omx1" ]]; then
    SOURCE_MODELS_FILE="$SCRIPT_DIR/omx_order_models.json"
  else
    SOURCE_MODELS_FILE="$SCRIPT_DIR/omx_cd_order_models.json"
  fi

  # 모델 매핑 파일에 등록된 정확한 모델 경로를 사용한다.
  # omx2 파일은 C/D 키와 A/B 키 형식을 모두 허용한다.
  # 잘못된 경로일 때 LeRobot을 실행하기 전에 오류를 출력한다.
  POLICY_PATH="$(python3 - "$ROBOT_ID" "$SOURCE_MODELS_FILE" "$ORDER_MODELS_FILE" "$SCRIPT_DIR" <<'PYTHON'
import json
import sys
from pathlib import Path

robot_id, source_name, target_name, directory_name = sys.argv[1:]
source = Path(source_name)
target = Path(target_name)
base_dir = Path(directory_name)

if not source.is_file():
    raise SystemExit(f"[ERROR] 모델 설정 파일 없음: {source}")

try:
    models = json.loads(source.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"[ERROR] 모델 설정 읽기 실패: {exc}")

if not isinstance(models, dict):
    raise SystemExit("[ERROR] 모델 설정은 JSON 객체여야 합니다.")

if robot_id == "omx1":
    # A 주문 -> 원본 B 모델, B 주문 -> 원본 A 모델
    names = ("B", "A")
else:
    # 기존 MQTT 클라이언트는 C->A, D->B로 로컬 재고를 입력한다.
    # 이에 맞춰 C 모델을 A 슬롯, D 모델을 B 슬롯에 배치한다.
    if "C" in models and "D" in models:
        names = ("C", "D")
    elif "A" in models and "B" in models:
        names = ("A", "B")
    else:
        raise SystemExit(
            "[ERROR] omx_cd_order_models.json에 C/D 또는 A/B 항목이 필요합니다."
        )

active = {}
for local_item, source_item in zip(("A", "B"), names):
    entry = models.get(source_item)
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise SystemExit(f"[ERROR] 모델 {source_item}에 path 문자열이 없습니다.")

    model_path = Path(entry["path"]).expanduser()
    if not model_path.is_absolute():
        model_path = base_dir / model_path
    model_path = model_path.resolve()

    if not (model_path / "config.json").is_file():
        raise SystemExit(f"[ERROR] 모델 {source_item} 파일을 찾을 수 없습니다: {model_path}/config.json")

    active[local_item] = dict(entry)
    active[local_item]["path"] = str(model_path)
    order_name = local_item if robot_id == "omx1" else ("C" if local_item == "A" else "D")
    print(f"[MODEL] {robot_id} 주문 {order_name} -> {source_item} 모델: {model_path}", file=sys.stderr)

target.write_text(json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(active["A"]["path"])
PYTHON
)"

  echo "[MODEL] $ROBOT_ID 모델 설정: $SOURCE_MODELS_FILE"
  echo "[MODEL] 실행 매핑 파일: $ORDER_MODELS_FILE"
  echo "[MODEL] 초기 Policy: $POLICY_PATH"
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
  --strategy.order_models_file="$ORDER_MODELS_FILE" \
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
  --policy.path="$POLICY_PATH" \
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
