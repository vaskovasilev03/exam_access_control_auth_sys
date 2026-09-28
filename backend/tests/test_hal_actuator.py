import asyncio
import io
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

from app.hal.base import ActuatorDriver
from app.hal.mock import MockActuatorDriver
from app.hal.physical import PhysicalRelayActuatorDriver
from app.hal.actuator import get_actuator
from app.stream_esp32 import subscribe_room_events, unsubscribe_room_events


class HalActuatorTestCase(unittest.TestCase):
    """
    Test suite for the Hardware Abstraction Layer (HAL) and Actuator Drivers.
    Verifies MockActuatorDriver simulation, log formatting, SSE dispatches,
    and graceful hardware fallbacks.
    """

    def setUp(self):
        self.mock_driver = MockActuatorDriver(default_gpio_pin=12)

    def test_mock_driver_properties(self):
        """Driver must identify as simulation and initialize in LOCKED state."""
        self.assertTrue(self.mock_driver.is_simulation)
        status = self.mock_driver.get_status(room_number="1151")
        self.assertEqual(status["status"], "LOCKED")
        self.assertEqual(status["relay_state"], "LOW")
        self.assertEqual(status["gpio_pin"], 12)

    def test_mock_unlock_console_logs(self):
        """
        Console logs must match the exact thesis requirements:
        Trigger: [HAL ACTUATOR] >>> Relay TRIGGERED: GPIO 12 HIGH -> Unlocking door for 5.0 seconds....
        Release: [HAL ACTUATOR] >>> Relay RELEASED: GPIO 12 LOW -> Door locked..
        """
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output
        try:
            # Short duration for unit test execution
            self.mock_driver.unlock_door(duration=0.2, room_number="1151")
            time.sleep(0.3)
        finally:
            sys.stdout = old_stdout

        output = captured_output.getvalue()
        self.assertIn("[HAL ACTUATOR] >>> Relay TRIGGERED: GPIO 12 HIGH -> Unlocking door for 0.2 seconds....", output)
        self.assertIn("[HAL ACTUATOR] >>> Relay RELEASED: GPIO 12 LOW -> Door locked..", output)

    def test_mock_unlock_default_five_seconds_signature(self):
        """Tests standard signature actuator.unlock_door(duration=5)."""
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output
        try:
            self.mock_driver.unlock_door(duration=5)
            # Immediate status check
            status = self.mock_driver.get_status()
            self.assertEqual(status["status"], "UNLOCKED")
            self.assertEqual(status["relay_state"], "HIGH")
            # Immediate relock to clean up
            self.mock_driver.lock_door()
        finally:
            sys.stdout = old_stdout

        output = captured_output.getvalue()
        self.assertIn("[HAL ACTUATOR] >>> Relay TRIGGERED: GPIO 12 HIGH -> Unlocking door for 5.0 seconds....", output)
        self.assertIn("[HAL ACTUATOR] >>> Relay RELEASED: GPIO 12 LOW -> Door locked..", output)

    def test_mock_sse_events_emission(self):
        """Verifies that unlocking and locking dispatch SSE events to the room."""
        room = "TEST_HAL_ROOM"
        queue = subscribe_room_events(room)
        try:
            self.mock_driver.unlock_door(duration=0.2, room_number=room)
            time.sleep(0.3)

            events_received = []
            while not queue.empty():
                events_received.append(queue.get_nowait())

            event_names = [e.get("event") for e in events_received]
            self.assertIn("door_unlocked", event_names)
            self.assertIn("actuator_status", event_names)
            self.assertIn("door_locked", event_names)

            # Check payload structure
            unlocked_evt = next(e for e in events_received if e.get("event") == "door_unlocked")
            self.assertEqual(unlocked_evt["data"]["status"], "UNLOCKED")
            self.assertEqual(unlocked_evt["data"]["gpio"], 12)
            self.assertEqual(unlocked_evt["data"]["relay"], "HIGH")

            locked_evt = next(e for e in events_received if e.get("event") == "door_locked")
            self.assertEqual(locked_evt["data"]["status"], "LOCKED")
            self.assertEqual(locked_evt["data"]["relay"], "LOW")
        finally:
            unsubscribe_room_events(room, queue)

    def test_physical_driver_fallback_when_no_esp32_online(self):
        """Physical driver should safely fall back to Mock simulation if room has no active ESP32 IP."""
        phys_driver = PhysicalRelayActuatorDriver(gpio_pin=12)
        self.assertFalse(phys_driver.is_simulation)

        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output
        try:
            # When room has no registered ESP32, delegates to mock
            phys_driver.unlock_door(duration=0.2, room_number="NON_EXISTENT_ROOM_999")
            time.sleep(0.3)
        finally:
            sys.stdout = old_stdout

        output = captured_output.getvalue()
        self.assertIn("No physical ESP32 node registered", output)
        self.assertIn("[HAL ACTUATOR] >>> Relay TRIGGERED: GPIO 12 HIGH -> Unlocking door for 0.2 seconds....", output)

    @patch("httpx.Client")
    def test_physical_driver_remote_esp32_http_dispatch(self, mock_client_cls):
        """Verifies HTTP GET/POST dispatch to remote ESP32 node over Wi-Fi."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {"ESP32_IP": "192.168.68.53"}):
            phys_driver = PhysicalRelayActuatorDriver(gpio_pin=12)
            phys_driver.unlock_door(duration=5.0, room_number="1151")

            time.sleep(0.1)
            # Verify HTTP call made to http://192.168.68.53/unlock?duration=5.0
            mock_client.get.assert_called_with("http://192.168.68.53/unlock?duration=5.0")


    def test_actuator_factory_simulation_mode(self):
        """get_actuator must return MockActuatorDriver when simulation=True."""
        with patch.dict(os.environ, {"SIMULATION_MODE": "True"}):
            driver = get_actuator(simulation=True)
            self.assertIsInstance(driver, MockActuatorDriver)
            self.assertTrue(driver.is_simulation)


if __name__ == "__main__":
    unittest.main()
