from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class ActuatorDriver(ABC):
    """
    Hardware Abstraction Layer (HAL) interface for door lock and relay actuators.
    Defines the contract for controlling door release mechanisms (solenoid locks, electromagnetic catches).
    Separates the physical hardware driver from simulation/mock implementations.
    """

    @property
    @abstractmethod
    def is_simulation(self) -> bool:
        """Returns True if this driver is running in simulation / mock mode."""
        pass

    @abstractmethod
    def unlock_door(self, *args, **kwargs) -> Any:
        """
        Triggers the actuator to unlock the door for the given duration in seconds.
        Flexible signature supporting:
          - unlock_door(duration=5)
          - unlock_door(duration=5, room_number='1151')
          - unlock_door(room_number='1151', duration=5)
          - unlock_door('1151', duration=5)
          - unlock_door('1151', 5)
        """
        pass

    @abstractmethod
    def lock_door(self, room_number: Optional[str] = None) -> Any:
        """Immediately locks the door and resets relay state."""
        pass

    @abstractmethod
    def get_status(self, room_number: Optional[str] = None) -> Dict[str, Any]:
        """Returns the current state of the actuator for the specified room or default."""
        pass
