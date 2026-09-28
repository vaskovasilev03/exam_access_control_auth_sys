import os
import logging
from typing import Optional

from .base import ActuatorDriver
from .mock import MockActuatorDriver
from .physical import PhysicalRelayActuatorDriver

logger = logging.getLogger("hal.actuator")

_ACTUATOR_INSTANCE: Optional[ActuatorDriver] = None


def get_actuator(simulation: Optional[bool] = None, gpio_pin: int = 12) -> ActuatorDriver:
    """
    Factory function for obtaining the door actuator driver instance.
    
    If simulation is True (or if SIMULATION_MODE=True in .env/environment),
    returns MockActuatorDriver.
    Otherwise returns PhysicalRelayActuatorDriver.
    """
    global _ACTUATOR_INSTANCE

    if simulation is None:
        sim_env = os.getenv("SIMULATION_MODE", "true").strip().lower()
        simulation = sim_env in ("true", "1", "yes", "enabled")

    if _ACTUATOR_INSTANCE is None:
        if simulation:
            _ACTUATOR_INSTANCE = MockActuatorDriver(default_gpio_pin=gpio_pin)
            logger.info(f"[HAL ACTUATOR] Initialized MockActuatorDriver (SIMULATION_MODE=True, GPIO={gpio_pin})")
        else:
            _ACTUATOR_INSTANCE = PhysicalRelayActuatorDriver(gpio_pin=gpio_pin)
            logger.info(f"[HAL ACTUATOR] Initialized PhysicalRelayActuatorDriver (GPIO={gpio_pin})")

    return _ACTUATOR_INSTANCE


# Default singleton instance ready for use across modules
actuator: ActuatorDriver = get_actuator()
