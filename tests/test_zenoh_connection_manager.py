from __future__ import annotations

from backend.app.services.zenoh_connection_manager import ZenohConnectionManager


def test_transient_admin_failure_retains_robot_as_degraded(monkeypatch):
    manager = ZenohConnectionManager()
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
    manager = ZenohConnectionManager()
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

