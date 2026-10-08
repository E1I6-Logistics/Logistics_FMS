#!/usr/bin/env bash
set -Eeuo pipefail

ITEM="${1:-}"
QUANTITY="${2:-}"
CAPACITY="${3:-8}"
STATE_PATH="${OMX_INVENTORY_STATE_PATH:-$HOME/.local/state/lerobot/omx_inventory.json}"

if [[ -z "$ITEM" ]] || [[ ! "$QUANTITY" =~ ^[0-9]+$ ]] || (( QUANTITY < 0 || QUANTITY > CAPACITY )); then
  echo "사용법: $0 물건이름 주문수량 [전체재고수량]  (예: $0 A 2, 대기: $0 WAIT 0)" >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - "$STATE_PATH" "$CAPACITY" "$QUANTITY" "$ITEM" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
capacity = int(sys.argv[2])
quantity = int(sys.argv[3])
item = sys.argv[4].upper()
if item not in {"A", "B", "WAIT"} or (item == "WAIT") != (quantity == 0):
    raise SystemExit("주문은 A 1~8 또는 B 1~8, 대기는 WAIT 0으로 입력하세요.")
if quantity > 0 and path.exists():
    previous = json.loads(path.read_text())
    if int(previous.get("remaining", 0)) > 0:
        raise SystemExit("진행 중인 주문이 있습니다. 완료 후 다음 주문을 입력하세요.")
state = {
    "capacity": capacity,
    "total_completed": capacity - quantity,
    "remaining": quantity,
    "order_item": item,
    "order_quantity": quantity,
    "order_completed": 0,
    "order_started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "order_started_at_epoch": time.time(),
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
}
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
if quantity == 0:
    print(f"Waiting mode set: state={path}")
else:
    print(f"New order accepted: item={item}, quantity={quantity}, state={path}")
PY
