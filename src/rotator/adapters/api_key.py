"""
vaultkey.adapters.api_key
-------------------------
Generic adapter for rotating arbitrary API keys and tokens.

This adapter generates a cryptographically secure random key and
is intended as a base for third-party service integrations. Override
`update_target` to push the new key to your specific service.

Expected secret shape (flexible):
    {
        "api_key": "old-key-value",
        "service": "my-service"   (optional, for logging)
    }
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from .base import TargetAdapter

logger = logging.getLogger(__name__)

DEFAULT_KEY_BYTES = 32  # 256-bit key → 43-char base64url string


class APIKeyAdapter(TargetAdapter):
    """
    Generates a new URL-safe random API key.

    update_target is a no-op here since generic API keys are typically
    registered on the consuming side (the application picks up the new
    value from Secrets Manager). Override this class to push the key
    to an external service.

    Example override:
        class StripeKeyAdapter(APIKeyAdapter):
            def update_target(self, new_secret):
                stripe.APIKey.create(key=new_secret["api_key"])
    """

    def __init__(self, key_bytes: int = DEFAULT_KEY_BYTES) -> None:
        self.key_bytes = key_bytes

    def generate_secret(self, current: dict[str, Any]) -> dict[str, Any]:
        new_key = secrets.token_urlsafe(self.key_bytes)
        logger.info(
            "Generated new API key for service=%s",
            current.get("service", "unknown"),
        )
        return {**current, "api_key": new_key}

    def update_target(self, new_secret: dict[str, Any]) -> None:
        """
        No-op for the generic adapter.

        Applications should subscribe to the SNS rotation event and
        reload credentials from Secrets Manager on notification.
        Override this method to push the new key to an external API.
        """
        service = new_secret.get("service", "unknown")
        logger.info(
            "update_target called for generic API key adapter (service=%s). "
            "No external update performed. Override this method for push-based rotation.",
            service,
        )
