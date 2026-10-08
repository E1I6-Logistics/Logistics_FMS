"""웹과 같은 API로 시나리오 하나 실행: python3 tests/traffic_scenarios.py cycle"""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="traffic_scenarios.json에 정의된 name")
    args = parser.parse_args()
    try:
        config = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
        base_url = config["base_url"].rstrip("/")

        def request(path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            req = Request(base_url + path, data=data, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as response:
                return json.load(response)

        run = request("/api/scenarios/run", {"name": args.scenario})
        print(f"[{run['mode']}] {run['description']}", flush=True)
        previous = None
        while True:
            state = request("/api/scenarios/status")
            if state["run_id"] != run["run_id"]:
                raise ValueError("다른 실행으로 상태가 변경되어 결과를 확인할 수 없습니다.")
            display = (state["state"], state["robots"], state["message"])
            if display != previous:
                print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
                previous = display
            if state["state"] not in ("running", "stopping"):
                return 0 if state["state"] == "completed" else 1
            time.sleep(.5)
    except HTTPError as exc:
        print(exc.read().decode(), flush=True)
    except (ValueError, KeyError, OSError, URLError) as exc:
        print(f"오류: {exc}", flush=True)
        print("실행 접수 후 연결이 끊기면 서버 테스트는 계속됩니다. 웹에서 상태/정지를 확인하세요.")
    except KeyboardInterrupt:
        print("상태 조회 종료. 서버 테스트는 계속됩니다. 중단하려면 웹 비상정지를 사용하세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
