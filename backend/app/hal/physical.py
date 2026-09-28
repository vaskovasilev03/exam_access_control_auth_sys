import asyncio
import logging
import os
import sys
import threading
import time
from typing import Optional, Dict, Any

from .base import ActuatorDriver
from .mock import MockActuatorDriver

logger = logging.getLogger("hal.actuator.physical")

GREEN = "\033[1;32m"
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
RESET = "\033[0m"


class PhysicalRelayActuatorDriver(ActuatorDriver):
    """
    Physical Relay Actuator Driver for target production environment.
    Controls a 5V optoisolated relay (PC817) on GPIO 12 driving a 12V DC fail-secure
    solenoid lock with 1N4007 flyback diode protection.
    
    If physical GPIO hardware is unavailable (e.g. development machine or container),
    gracefully falls back to MockActuatorDriver simulation.
    """

    def __init__(self, gpio_pin: int = 12):
        self.gpio_pin = gpio_pin
        self._gpio_available = False
        self._mock_fallback: Optional[MockActuatorDriver] = None
        self._lock = threading.Lock()
        self._init_hardware()

    def _init_hardware(self):
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.OUT, initial=GPIO.LOW)
            self._gpio = GPIO
            self._gpio_available = True
            print(f"{GREEN}[HAL ACTUATOR] Physical GPIO initialized on pin {self.gpio_pin} (Target Production Mode){RESET}", flush=True)
            logger.info(f"[HAL ACTUATOR] Physical GPIO initialized on pin {self.gpio_pin}")
        except Exception as e:
            self._gpio_available = False
            self._mock_fallback = MockActuatorDriver(default_gpio_pin=self.gpio_pin)
            print(f"{YELLOW}[HAL ACTUATOR] Physical GPIO hardware not detected ({e}). Gracefully delegating to MockActuatorDriver.{RESET}", flush=True)
            logger.warning(f"[HAL ACTUATOR] Physical GPIO hardware not detected ({e}). Using MockActuatorDriver.")

    @property
    def is_simulation(self) -> bool:
        return not self._gpio_available

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._mock_fallback:
            self._mock_fallback.set_event_loop(loop)

    def unlock_door(self, *args, **kwargs) -> Any:
        if not self._gpio_available and self._mock_fallback:
            return self._mock_fallback.unlock_door(*args, **kwargs)

        duration = 5.0
        room_number = None
        if "duration" in kwargs:
            duration = float(kwargs["duration"])
        if "room_number" in kwargs:
            room_number = str(kwargs["room_number"])
        if args:
            if isinstance(args[0], (int, float)):
                duration = float(args[0])
                if len(args) > 1 and isinstance(args[1], str):
                    room_number = str(args[1])
            elif isinstance(args[0], str):
                room_number = args[0]
                if len(args) > 1 and isinstance(args[1], (int, float)):
                    duration = float(args[1])

        # Physical hardware activation
        try:
            self._gpio.output(self.gpio_pin, self._gpio.HIGH)
            trigger_log = f"[HAL ACTUATOR] >>> Physical Relay TRIGGERED: GPIO {self.gpio_pin} HIGH -> Unlocking door for {duration:.1f} seconds...."
            print(f"{GREEN}{trigger_log}{RESET}", flush=True)
            logger.info(trigger_log)

            # SSE Notification
            self._emit_sse(room_number, "door_unlocked", {
                "status": "UNLOCKED",
                "relay": "HIGH",
                "gpio": self.gpio_pin,
                "duration": duration,
                "room_number": room_number,
                "message": f"Вратата е отключена за {duration:.1f} сек."
            })

            def _relock():
                time.sleep(duration)
                self.lock_door(room_number)

            t = threading.Thread(target=_relock, daemon=True)
            t.start()
            return t
        except Exception as e:
            logger.error(f"[HAL ACTUATOR] Physical GPIO error during unlock: {e}")
            if self._mock_fallback:
                return self._mock_fallback.unlock_door(*args, **kwargs)

    def lock_door(self, room_number: Optional[str] = None) -> None:
        if not self._gpio_available and self._mock_fallback:
            return self._mock_fallback.lock_door(room_number)

        try:
            self._gpio.output(self.gpio_pin, self._gpio.LOW)
            release_log = f"[HAL ACTUATOR] >>> Physical Relay RELEASED: GPIO {self.gpio_pin} LOW -> Door locked.."
            print(f"{CYAN}{release_log}{RESET}", flush=True)
            logger.info(release_log)

            self._emit_sse(room_number, "door_locked", {
                "status": "LOCKED",
                "relay": "LOW",
                "gpio": self.gpio_pin,
                "room_number": room_number,
                "message": "Вратата е заключена"
            })
        except Exception as e:
            logger.error(f"[HAL ACTUATOR] Physical GPIO error during lock: {e}")

    def _emit_sse(self, room_number: Optional[str], event_name: str, payload: dict):
        if not room_number:
            return
        try:
            from ..stream_esp32 import emit_room_event
            emit_room_event(str(room_number), event_name, payload)
        except Exception as e:
            logger.debug(f"[HAL ACTUATOR] SSE emit error: {e}")

    def get_status(self, room_number: Optional[str] = None) -> Dict[str, Any]:
        if not self._gpio_available and self._mock_fallback:
            return self._mock_fallback.get_status(room_number)

        return {
            "driver": "PhysicalRelayActuatorDriver",
            "is_simulation": False,
            "gpio_pin": self.gpio_pin,
            "status": "READY",
            "room_number": room_number
        }
