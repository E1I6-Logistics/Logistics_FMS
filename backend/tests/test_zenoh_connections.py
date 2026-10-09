import unittest
from unittest.mock import patch

from backend.app.services.zenoh_connection_manager import ZenohConnectionManager


class ZenohConnectionTest(unittest.TestCase):
    def test_rest_failure_is_not_an_empty_snapshot(self):
        manager = ZenohConnectionManager()
        with patch.object(manager, "_get_sessions", return_value={"zid": "192.0.2.1"}), \
             patch.object(manager, "_get_robot_routes", return_value={"zid": "robot1"}):
            first = manager.connections()
        with patch.object(manager, "_get_sessions", side_effect=TimeoutError):
            with self.assertRaises(ConnectionError):
                manager.connections()
        self.assertEqual(manager.last_successful(), first)

    def test_successful_empty_snapshot_is_not_cached_as_previous_robots(self):
        manager = ZenohConnectionManager()
        with patch.object(manager, "_get_sessions", return_value={"zid": "192.0.2.1"}), \
             patch.object(manager, "_get_robot_routes", return_value={"zid": "robot1"}):
            manager.connections()
        with patch.object(manager, "_get_sessions", return_value={}), \
             patch.object(manager, "_get_robot_routes", return_value={}):
            self.assertEqual(manager.connections(), [])


if __name__ == "__main__":
    unittest.main()
