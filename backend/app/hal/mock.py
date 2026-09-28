import asyncio
import logging
import sys
import threading
import time
from typing import Optional, Dict, Any

from .base import ActuatorDriver

logger = logging.getLogger("hal.actuator")

# ANSI escape codes for prominent demo console visibility
GREEN = "\033[1;32m"
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
RESET = "\033[0m"


class MockActuatorDriver(ActuatorDriver):
    """
    Mock Actuator Driver for Hardware Abstraction Layer (HAL).
    Simulates a 5V optoisolated relay (PC817) and 12V fail-secure solenoid door lock
    on GPIO 12 without requiring physical hardware.
    
    Provides:
      - Synchronous and asynchronous trigger handling
      - High-visibility console logs for academic live demonstrations
      - Server-Sent Events (SSE) notification dispatched to the examiner monitor
      - Non-blocking 5.0-second auto-lock countdown cycle
    """

    def __init__(self, default_gpio_pin: int = 12):
        self.gpio_pin = default_gpio_pin
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_simulation(self) -> bool:
        return True

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the primary asyncio event loop for threadsafe task dispatching."""
        self._main_loop = loop

    def _get_room_state(self, room_number: Optional[str]) -> Dict[str, Any]:
        key = str(room_number) if room_number else "GLOBAL"
        with self._lock:
            if key not in self._states:
                self._states[key] = {
                    "is_unlocked": False,
                    "relay_state": "LOW",
                    "unlock_until": 0.0,
                    "task": None,
                    "room_number": room_number
                }
            return self._states[key]

    def _emit_sse_event(self, room_number: Optional[str], event_name: str, payload: dict) -> None:
        """Dispatches an SSE event to the room subscribers on the examiner web monitor."""
        if not room_number:
            return
        try:
            from ..stream_esp32 import emit_room_event
            emit_room_event(str(room_number), event_name, payload)
        except Exception as e:
            logger.debug(f"[HAL ACTUATOR] SSE emit error: {e}")

    def unlock_door(self, *args, **kwargs) -> Any:
        """
        Triggers door unlock for the specified duration (default 5.0s).
        Flexible signature to support:
          - actuator.unlock_door(duration=5)
          - actuator.unlock_door(duration=5, room_number="1151")
          - actuator.unlock_door(room_number="1151", duration=5)
          - actuator.unlock_door("1151", duration=5)
          - actuator.unlock_door("1151", 5)
        """
        duration = 5.0
        room_number = None

        # Parse args and kwargs
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

        state = self._get_room_state(room_number)

        # Update state
        with self._lock:
            state["is_unlocked"] = True
            state["relay_state"] = "HIGH"
            state["unlock_until"] = time.time() + duration

        # 1. Console Log: Required format for demonstration
        # [HAL ACTUATOR] >>> Relay TRIGGERED: GPIO 12 HIGH -> Unlocking door for 5.0 seconds....
        trigger_log = f"[HAL ACTUATOR] >>> Relay TRIGGERED: GPIO {self.gpio_pin} HIGH -> Unlocking door for {duration:.1f} seconds...."
        print(f"{GREEN}{trigger_log}{RESET}", flush=True)
        sys.stdout.flush()
        logger.info(trigger_log)

        # 2. Emit SSE event to the examiner web monitor that the door is unlocked
        sse_payload = {
            "status": "UNLOCKED",
            "relay": "HIGH",
            "gpio": self.gpio_pin,
            "duration": duration,
            "room_number": room_number,
            "message": f"Вратата е отключена за {duration:.1f} сек."
        }
        self._emit_sse_event(room_number, "door_unlocked", sse_payload)
        self._emit_sse_event(room_number, "actuator_status", sse_payload)

        # 3. Schedule asynchronous relocking after duration
        return self._schedule_relock(duration, room_number)

    def _schedule_relock(self, duration: float, room_number: Optional[str]):
        """Schedules the relock callback after duration seconds in an asynchronous or threadsafe manner."""
        # Try running within existing event loop if called in async context
        try:
            loop = asyncio.get_running_loop()
            if loop and loop.is_running():
                return loop.create_task(self._async_relock_task(duration, room_number))
        except RuntimeError:
            pass

        # Try scheduling on registered main event loop
        if self._main_loop and self._main_loop.is_running():
            try:
                return asyncio.run_coroutine_threadsafe(
                    self._async_relock_task(duration, room_number),
                    self._main_loop
                )
            except Exception as e:
                logger.debug(f"[HAL ACTUATOR] Failed to dispatch to main loop: {e}")

        # Fallback to daemon timer thread (guarantees completion even in sync worker threads or unit tests)
        def _thread_relock():
            time.sleep(duration)
            self._do_release(room_number)

        timer = threading.Thread(target=_thread_relock, daemon=True)
        timer.start()
        return timer

    async def _async_relock_task(self, duration: float, room_number: Optional[str]):
        await asyncio.sleep(duration)
        self._do_release(room_number)

    def _do_release(self, room_number: Optional[str]):
        state = self._get_room_state(room_number)
        with self._lock:
            state["is_unlocked"] = False
            state["relay_state"] = "LOW"
            state["unlock_until"] = 0.0

        # Required console log format:
        # [HAL ACTUATOR] >>> Relay RELEASED: GPIO 12 LOW -> Door locked..
        release_log = f"[HAL ACTUATOR] >>> Relay RELEASED: GPIO {self.gpio_pin} LOW -> Door locked.."
        print(f"{CYAN}{release_log}{RESET}", flush=True)
        sys.stdout.flush()
        logger.info(release_log)

        # Emit SSE relock event
        sse_payload = {
            "status": "LOCKED",
            "relay": "LOW",
            "gpio": self.gpio_pin,
            "room_number": room_number,
            "message": "Вратата е заключена"
        }
        self._emit_sse_event(room_number, "door_locked", sse_payload)
        self._emit_sse_event(room_number, "actuator_status", sse_payload)

    def lock_door(self, room_number: Optional[str] = None) -> None:
        """Immediately locks the door."""
        self._do_release(room_number)

    def get_status(self, room_number: Optional[str] = None) -> Dict[str, Any]:
        state = self._get_room_state(room_number)
        now = time.time()
        is_unlocked = state.get("is_unlocked", False) and (state.get("unlock_until", 0.0) > now)
        return {
            "driver": "MockActuatorDriver",
            "is_simulation": True,
            "gpio_pin": self.gpio_pin,
            "status": "UNLOCKED" if is_unlocked else "LOCKED",
            "relay_state": "HIGH" if is_unlocked else "LOW",
            "room_number": room_number,
            "seconds_remaining": max(0.0, state.get("unlock_until", 0.0) - now) if is_unlocked else 0.0
        }
