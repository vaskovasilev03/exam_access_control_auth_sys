import asyncio
import logging
import os
import sys
import threading
import time
from typing import Optional, Dict, Any

import httpx

from .base import ActuatorDriver
from .mock import MockActuatorDriver

logger = logging.getLogger("hal.actuator.esp32")

GREEN = "\033[1;32m"
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
RESET = "\033[0m"


class PhysicalRelayActuatorDriver(ActuatorDriver):
    """
    Physical Relay Actuator Driver for Distributed Edge IoT Architecture.
    Communicates over Wi-Fi/HTTP with the peripheral ESP32-S3-CAM node installed at the exam hall.
    
    When an admission is granted (status == GRANTED or TWIN_PASSED), this driver sends a network
    command to the ESP32 endpoint:
        GET/POST http://<esp32_ip>/unlock?duration=5.0
    The ESP32 firmware then drives GPIO 12 HIGH to activate the 5V optoisolated relay (PC817)
    and 12V solenoid lock, while illuminating the green status LED on GPIO 13.
    
    If the physical ESP32 node is offline or unassigned, it gracefully delegates to MockActuatorDriver.
    """

    def __init__(self, gpio_pin: int = 12):
        self.gpio_pin = gpio_pin
        self._mock_fallback = MockActuatorDriver(default_gpio_pin=gpio_pin)
        self._lock = threading.Lock()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        logger.info(f"[HAL ACTUATOR] Initialized PhysicalRelayActuatorDriver (ESP32 Network Actuator, GPIO={gpio_pin})")

    @property
    def is_simulation(self) -> bool:
        return False

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop
        if self._mock_fallback:
            self._mock_fallback.set_event_loop(loop)

    def _resolve_esp32_ip(self, room_number: Optional[str]) -> Optional[str]:
        """Looks up the registered IP address of the ESP32-CAM node for the target hall."""
        if not room_number:
            return os.getenv("ESP32_IP")

        try:
            from ..stream_esp32 import ACTIVE_CAMERAS
            ip = ACTIVE_CAMERAS.get(str(room_number))
            if ip:
                return ip
        except Exception:
            pass

        return os.getenv("ESP32_IP")

    def unlock_door(self, *args, **kwargs) -> Any:
        """
        Transmits remote unlock command to the ESP32-CAM over the network.
        Falls back cleanly to simulation if no physical node is online.
        """
        duration = 5.0
        room_number = None

        if "duration" in kwargs:
            duration = float(kwargs["duration"])
        if "room_number" in kwargs:
            room_number = str(kwargs["room_number"])

        if args:
            first = args[0]
            if isinstance(first, (int, float)):
                duration = float(first)
                if len(args) > 1 and isinstance(args[1], str):
                    room_number = str(args[1])
            elif isinstance(first, str):
                room_number = first
                if len(args) > 1 and isinstance(args[1], (int, float)):
                    duration = float(args[1])

        esp32_ip = self._resolve_esp32_ip(room_number)

        if not esp32_ip:
            notice = f"[HAL ACTUATOR] No physical ESP32 node registered for Room {room_number or 'default'}. Falling back to Mock simulation."
            print(f"{YELLOW}{notice}{RESET}", flush=True)
            logger.warning(notice)
            return self._mock_fallback.unlock_door(*args, **kwargs)

        # Trigger HTTP request to ESP32-CAM endpoint: http://<esp32_ip>/unlock?duration=5
        clean_ip = esp32_ip.replace("http://", "").replace("https://", "").rstrip("/")
        unlock_url = f"http://{clean_ip}/unlock?duration={duration:.1f}"

        def _send_network_unlock():
            try:
                with httpx.Client(timeout=2.5) as client:
                    resp = client.get(unlock_url)
                    if resp.status_code == 200:
                        success_log = f"[HAL ACTUATOR] >>> Remote ESP32 Relay TRIGGERED: {unlock_url} -> GPIO {self.gpio_pin} HIGH ({duration:.1f}s)"
                        print(f"{GREEN}{success_log}{RESET}", flush=True)
                        logger.info(success_log)
                    else:
                        raise RuntimeError(f"ESP32 returned HTTP status {resp.status_code}")
            except Exception as e:
                err_log = f"[HAL ACTUATOR] Failed to reach ESP32 at {unlock_url}: {e}. Switching to Mock simulation."
                print(f"{YELLOW}{err_log}{RESET}", flush=True)
                logger.warning(err_log)
                self._mock_fallback.unlock_door(*args, **kwargs)

        # Dispatch network call in background thread
        worker = threading.Thread(target=_send_network_unlock, daemon=True)
        worker.start()

        # Emit immediate SSE event to the examiner web monitor
        self._emit_sse(room_number, "door_unlocked", {
            "status": "UNLOCKED",
            "relay": "HIGH",
            "gpio": self.gpio_pin,
            "duration": duration,
            "room_number": room_number,
            "esp32_ip": clean_ip,
            "message": f"Вратата е отключена през ESP32 ({clean_ip}) за {duration:.1f} сек."
        })
        self._emit_sse(room_number, "actuator_status", {
            "status": "UNLOCKED",
            "relay": "HIGH",
            "gpio": self.gpio_pin,
            "duration": duration,
            "room_number": room_number,
            "esp32_ip": clean_ip
        })

        # Relock scheduling for SSE synchronization
        def _schedule_sse_relock():
            time.sleep(duration)
            self.lock_door(room_number)

        t = threading.Thread(target=_schedule_sse_relock, daemon=True)
        t.start()
        return t

    def lock_door(self, room_number: Optional[str] = None) -> None:
        """Notifies the UI and logs that the physical relay on the ESP32 has returned to LOW."""
        release_log = f"[HAL ACTUATOR] >>> Remote ESP32 Relay RELEASED: GPIO {self.gpio_pin} LOW -> Door locked.."
        print(f"{CYAN}{release_log}{RESET}", flush=True)
        logger.info(release_log)

        self._emit_sse(room_number, "door_locked", {
            "status": "LOCKED",
            "relay": "LOW",
            "gpio": self.gpio_pin,
            "room_number": room_number,
            "message": "Вратата е заключена"
        })
        self._emit_sse(room_number, "actuator_status", {
            "status": "LOCKED",
            "relay": "LOW",
            "gpio": self.gpio_pin,
            "room_number": room_number
        })

    def _emit_sse(self, room_number: Optional[str], event_name: str, payload: dict):
        if not room_number:
            return
        try:
            from ..stream_esp32 import emit_room_event
            emit_room_event(str(room_number), event_name, payload)
        except Exception as e:
            logger.debug(f"[HAL ACTUATOR] SSE emit error: {e}")

    def get_status(self, room_number: Optional[str] = None) -> Dict[str, Any]:
        esp32_ip = self._resolve_esp32_ip(room_number)
        return {
            "driver": "PhysicalRelayActuatorDriver",
            "mode": "ESP32_NETWORK_HTTP",
            "is_simulation": False,
            "gpio_pin": self.gpio_pin,
            "esp32_ip": esp32_ip,
            "target_url": f"http://{esp32_ip}/unlock" if esp32_ip else None,
            "status": "READY" if esp32_ip else "NO_ESP32_ASSIGNED",
            "room_number": room_number
        }
