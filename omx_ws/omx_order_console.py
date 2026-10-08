"""Console-owned sequential orders; does not send robot actions."""
import json
import os
import subprocess
import time
from pathlib import Path


def parse_orders(line):
    tokens = line.split()
    if not tokens or len(tokens) % 2:
        raise ValueError('예: A 2 B 3 (품목과 수량을 쌍으로 입력하세요)')
    orders = []
    totals = {}
    for item, quantity in zip(tokens[::2], tokens[1::2]):
        item = item.upper()
        if item not in ('A', 'B') or not quantity.isascii() or not quantity.isdecimal():
            raise ValueError('품목은 A/B, 수량은 1~8로 입력하세요.')
        quantity = int(quantity)
        totals[item] = totals.get(item, 0) + quantity
        if not 1 <= quantity <= 8 or totals[item] > 8:
            raise ValueError('한 번 입력하는 주문에서 품목별 총수량은 1~8이어야 합니다.')
        orders.append((item, quantity))
    return orders


def elapsed(seconds):
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def execute_orders(orders, directory, state_path):
    started = time.monotonic()
    print('주문 순서: ' + ' → '.join(f'{item} {qty}개' for item, qty in orders), flush=True)
    for index, (item, qty) in enumerate(orders, 1):
        result = subprocess.run(['bash', str(directory / 'omx_new_order.sh'), item, str(qty)])
        if result.returncode:
            raise RuntimeError('주문 등록 실패. 남은 주문은 전달하지 않았습니다.')
        accepted = json.loads(state_path.read_text())
        token = accepted['order_started_at_epoch']
        last = None
        while True:
            state = json.loads(state_path.read_text())
            if (state.get('order_item'), state.get('order_quantity'), state.get('order_started_at_epoch')) != (item, qty, token):
                raise RuntimeError('주문 상태가 외부에서 변경되었습니다. 남은 주문 전달을 중단합니다.')
            done = int(state['order_completed'])
            remaining = int(state['remaining'])
            seconds = int(time.time() - token)
            current = (done, remaining, seconds)
            if current != last:
                print(f'[{index}/{len(orders)} {item}] 주문: {qty} | 완료: {done} | 남음: {remaining} | 경과: {elapsed(seconds)}', flush=True)
                last = current
            if remaining == 0:
                if done != qty:
                    raise RuntimeError('완료 수량이 일치하지 않습니다. 남은 주문 전달을 중단합니다.')
                print(f'[{item}] 주문 완료 | 작업시간: {elapsed(seconds)}', flush=True)
                break
            time.sleep(0.5)
    print(f'전체 주문 완료 | 총 소요시간: {elapsed(time.monotonic() - started)}', flush=True)


def main():
    directory = Path(__file__).resolve().parent
    state_path = Path(os.environ.get('OMX_INVENTORY_STATE_PATH', '~/.local/state/lerobot/omx_inventory.json')).expanduser()
    print('주문 콘솔입니다. 예: A 2 또는 A 2 B 3 / 종료: q')
    while True:
        try:
            line = input('물건과 수량 입력> ').strip()
            if line.lower() in ('q', 'quit'):
                return
            orders = parse_orders(line)
        except (EOFError, KeyboardInterrupt):
            print('\n콘솔을 종료합니다.')
            return
        except ValueError as exc:
            print(exc)
            continue
        try:
            execute_orders(orders, directory, state_path)
        except KeyboardInterrupt:
            print('\n감시 및 남은 주문 전달을 중단했습니다. 이미 등록된 주문은 취소되지 않았습니다.')
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            print(f'주문 중단: {exc}')


if __name__ == '__main__':
    main()
