"""실행 중인 웹 시뮬레이션 테스트: python3 tests/traffic_scenarios.py [시나리오명]

설정은 같은 폴더의 traffic_scenarios.json, 그래프는 routes/test.geojson만 사용한다.
"""

import argparse
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.changed = False

    def get(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.url + path, data=data,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(f"{path}: {exc.read().decode()}") from exc

    def check_mode(self):
        if self.get("/api/mode").get("mode") != "simulation":
            raise ValueError("웹에서 시뮬레이션 모드를 선택한 뒤 실행하세요.")

    def command(self, name, **payload):
        self.check_mode()
        self.changed = True
        result = self.get("/api/command/" + name, payload)
        if result.get("success") is not True or result.get("mode") != "simulation":
            raise ValueError(f"명령 실패: {result}")
        return result


def placement(robots, specs, nodes):
    """빈 노드부터 배치. 서로 자리가 바뀌었으면 여유 노드를 임시로 사용한다."""
    positions = {r["robot_id"]: next((n for n, xy in nodes.items()
                 if math.dist((r["x"], r["y"]), xy) < 1e-6), None) for r in robots}
    targets = {r["id"]: str(r["start"]) for r in specs}
    pending = [rid for rid in targets if positions[rid] != targets[rid]]
    moves = []
    while pending:
        rid = next((r for r in pending if targets[r] not in positions.values()), None)
        if rid is not None:
            node = targets[rid]
            pending.remove(rid)
        else:
            rid = pending[0]
            node = next((n for n in nodes if n not in positions.values()
                         and n not in targets.values()), None)
            if node is None:
                raise ValueError("초기 배치용 빈 노드가 없습니다. 시뮬레이션을 초기화하세요.")
        moves.append((rid, node))
        positions[rid] = node
    return moves


def validate(scenarios, nodes, robot_ids):
    if not scenarios or len({s["name"] for s in scenarios}) != len(scenarios):
        raise ValueError("시나리오 이름은 중복 없이 하나 이상 필요합니다.")
    for scenario in scenarios:
        specs = scenario["robots"]
        if len(specs) != len(robot_ids) or {r["id"] for r in specs} != robot_ids:
            raise ValueError(f"{scenario['name']}: 서버의 모든 로봇을 한 번씩 지정하세요.")
        starts = [str(r["start"]) for r in specs]
        if len(set(starts)) != len(starts):
            raise ValueError(f"{scenario['name']}: 시작 노드는 서로 달라야 합니다.")
        for robot in specs:
            for key in ("start", "goal"):
                if key == "goal" and robot[key] is None:
                    continue
                if str(robot[key]) not in nodes:
                    raise ValueError(f"{scenario['name']}: test.geojson에 없는 노드 {robot[key]}")
        if not any(r["goal"] is not None for r in specs):
            raise ValueError(f"{scenario['name']}: 이동 목적지가 하나 이상 필요합니다.")


def run(client, scenario, nodes, timeout):
    specs = scenario["robots"]
    print(f"\n[{scenario['name']}] {scenario['description']}", flush=True)
    for robot in specs:
        client.command("stop", robot_id=robot["id"])
    for rid, node in placement(client.get("/api/robots"), specs, nodes):
        x, y = nodes[node]
        client.command("goal", robot_id=rid, target_x=x, target_y=y)
    # 좌표 재설정 여부와 무관하게 모든 로봇을 동일한 정지 상태로 맞춘다.
    for robot in specs:
        client.command("stop", robot_id=robot["id"])
    states = {r["robot_id"]: r for r in client.get("/api/robots")}
    if any(states[r["id"]]["status"] != "IDLE"
           or math.dist((states[r["id"]]["x"], states[r["id"]]["y"]), nodes[str(r["start"])]) > 1e-6
           for r in specs):
        raise ValueError("초기 배치 확인 실패. 다른 명령이 실행 중인지 확인하세요.")

    goals = {r["id"]: str(r["goal"]) for r in specs if r["goal"] is not None}
    waiting = set()
    started = time.monotonic()
    for rid, goal in goals.items():
        response = client.command("goal-node", robot_id=rid, node_id=goal)
        if response["status"] == "WAITING":
            waiting.add(rid)
        print(f"  {rid} → {goal}: {response['status']}", flush=True)
    print(f"  일괄 전송: {time.monotonic() - started:.3f}초", flush=True)

    previous = None
    while True:
        client.check_mode()
        states = {r["robot_id"]: r for r in client.get("/api/robots")}
        waiting.update(rid for rid, r in states.items() if r["status"] == "WAITING")
        elapsed = time.monotonic() - started
        snapshot = [(rid, r["status"], r["current_node"],
                     (r.get("route") or {}).get("node_ids")) for rid, r in states.items()]
        if snapshot != previous:
            print(f"  {elapsed:.1f}s {snapshot}", flush=True)
            previous = snapshot
        if all(states[rid]["status"] == "IDLE" and str(states[rid]["current_node"]) == goal
               and states[rid].get("goal_node") is None for rid, goal in goals.items()):
            print(f"  완료 ({elapsed:.1f}초), 대기 관측: {', '.join(sorted(waiting)) or '없음'}", flush=True)
            return
        if elapsed >= timeout:
            raise ValueError(f"{scenario['name']}: {timeout}초 내 미완료. 시간 초과만으로 교착을 확정하지 않습니다.")
        time.sleep(.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", help="생략하면 JSON의 모든 시나리오를 순서대로 실행")
    args = parser.parse_args()
    client = None
    robot_ids = set()
    try:
        config = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
        scenarios = config["scenarios"]
        if args.scenario:
            scenarios = [s for s in scenarios if s["name"] == args.scenario]
            if not scenarios:
                raise ValueError(f"알 수 없는 시나리오: {args.scenario}")
        timeout = float(config["timeout_seconds"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds는 유한한 양수여야 합니다.")
        graph = json.loads((ROOT / "routes/test.geojson").read_text(encoding="utf-8"))
        nodes = {str(f["properties"]["id"]): f["geometry"]["coordinates"][:2]
                 for f in graph["features"] if f.get("geometry", {}).get("type") == "Point"}
        client = Client(config["base_url"])
        client.check_mode()
        if client.get("/api/route/graph") != graph:
            raise ValueError("서버 그래프가 현재 routes/test.geojson과 다릅니다. 서버 설정을 확인하세요.")
        robot_ids = {r["robot_id"] for r in client.get("/api/robots")}
        validate(scenarios, nodes, robot_ids)
        for scenario in scenarios:
            run(client, scenario, nodes, timeout)
        return 0
    except (ValueError, KeyError, TypeError, OSError, URLError, KeyboardInterrupt) as exc:
        print(f"\n중단: {exc or '사용자 중단'}", flush=True)
        if client is not None and client.changed:
            for rid in sorted(robot_ids):
                try:
                    client.command("stop", robot_id=rid)
                except (ValueError, OSError, URLError) as stop_error:
                    print(f"정지 확인 실패: {stop_error}", flush=True)
                    break
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
