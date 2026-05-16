"""
vaultkey.adapters.base
----------------------
Abstract base class for secret rotation adapters.

To add a new secret type, subclass TargetAdapter and implement
both abstract methods, then register the class in rotation_engine.ADAPTER_REGISTRY.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TargetAdapter(ABC):
    """
    Defines the two-step contract for rotating a secret:
    1. generate_secret  -- produce a new credential value
    2. update_target    -- push that credential to the target system

    Both methods receive/return plain dicts that map directly to
    the Secrets Manager SecretString JSON payload.
    """

    @abstractmethod
    def generate_secret(self, current: dict[str, Any]) -> dict[str, Any]:
        """
        Generate a new secret value.

        Args:
            current: The existing secret dict retrieved from Secrets Manager.

        Returns:
            A new secret dict to be written back to Secrets Manager.
        """

    @abstractmethod
    def update_target(self, new_secret: dict[str, Any]) -> None:
        """
        Apply the new credential to the target system before persisting it.

        This is called *before* writing to Secrets Manager so that a failure
        here does not leave Secrets Manager and the target out of sync.

        Args:
            new_secret: The new credential dict (output of generate_secret).

        Raises:
            Exception: Any exception signals to the engine that the rotation
                       should be rolled back and the failure recorded.
        """
