from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from backend.app.services.zenoh_connection_manager import ZenohConnectionManager


def test_transient_admin_failure_retains_robot_as_degraded(monkeypatch):
    manager = ZenohConnectionManager(cache_ttl_seconds=0)
    monkeypatch.setattr(manager, "_get_sessions", lambda: {"z1": "10.0.0.11"})
    monkeypatch.setattr(manager, "_get_robot_routes", lambda: {"z1": "robot1"})

    connected = manager.connections()
    assert connected[0]["connected"] is True

    def fail():
        raise TimeoutError("router timeout")

    monkeypatch.setattr(manager, "_get_sessions", fail)
    degraded = manager.connections()

    assert degraded[0]["name"] == "robot1"
    assert degraded[0]["connected"] is False
    assert degraded[0]["state"] == "DEGRADED"


def test_robot_recovers_after_admin_query_recovers(monkeypatch):
    manager = ZenohConnectionManager(cache_ttl_seconds=0)
    monkeypatch.setattr(manager, "_get_sessions", lambda: {"z1": "10.0.0.11"})
    monkeypatch.setattr(manager, "_get_robot_routes", lambda: {"z1": "robot1"})
    manager.connections()

    def fail():
        raise TimeoutError("router timeout")

    monkeypatch.setattr(manager, "_get_sessions", fail)
    manager.connections()
    monkeypatch.setattr(manager, "_get_sessions", lambda: {"z1": "10.0.0.11"})

    recovered = manager.connections()
    assert recovered[0]["connected"] is True
    assert recovered[0]["state"] == "CONNECTED"


def test_connection_detection_only_queries_logitle_pose_routes(monkeypatch):
    manager = ZenohConnectionManager(cache_ttl_seconds=0)
    paths: list[str] = []

    def fake_get_json(path: str):
        paths.append(path)
        return []

    monkeypatch.setattr(manager, "_get_json", fake_get_json)

    manager.connections()

    assert paths == ["/@/local/router", "/@/*/ros2/route/**/logitle_pose"]


def test_logitle_pose_route_maps_bridge_to_robot(monkeypatch):
    manager = ZenohConnectionManager(cache_ttl_seconds=0)

    monkeypatch.setattr(
        manager,
        "_get_json",
        lambda _path: [
            {
                "key": "@/z1/ros2/route/topic/pub/robot2/logitle_pose",
                "value": {},
            }
        ],
    )

    assert manager._get_robot_routes() == {"z1": "robot2"}


def test_cached_snapshot_avoids_repeated_admin_queries(monkeypatch):
    manager = ZenohConnectionManager(cache_ttl_seconds=60)
    calls = {"sessions": 0, "routes": 0}

    def sessions():
        calls["sessions"] += 1
        return {"z1": "10.0.0.11"}

    def routes():
        calls["routes"] += 1
        return {"z1": "robot1"}

    monkeypatch.setattr(manager, "_get_sessions", sessions)
    monkeypatch.setattr(manager, "_get_robot_routes", routes)

    first = manager.connections()
    second = manager.connections()

    assert first == second
    assert calls == {"sessions": 1, "routes": 1}


def test_concurrent_requests_share_one_admin_refresh(monkeypatch):
    manager = ZenohConnectionManager(cache_ttl_seconds=0)
    entered = Event()
    release = Event()
    counter_lock = Lock()
    calls = {"sessions": 0, "routes": 0}

    def sessions():
        with counter_lock:
            calls["sessions"] += 1
        entered.set()
        assert release.wait(timeout=2)
        return {"z1": "10.0.0.11"}

    def routes():
        with counter_lock:
            calls["routes"] += 1
        return {"z1": "robot1"}

    monkeypatch.setattr(manager, "_get_sessions", sessions)
    monkeypatch.setattr(manager, "_get_robot_routes", routes)

    with ThreadPoolExecutor(max_workers=8) as executor:
        refreshing = executor.submit(manager.connections)
        assert entered.wait(timeout=2)
        followers = [executor.submit(manager.connections) for _ in range(7)]
        follower_results = [future.result(timeout=2) for future in followers]
        release.set()
        refreshed = refreshing.result(timeout=2)

    assert all(result == [] for result in follower_results)
    assert refreshed[0]["name"] == "robot1"
    assert calls == {"sessions": 1, "routes": 1}
