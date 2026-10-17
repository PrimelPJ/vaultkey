"""
vaultkey.rotation_engine
------------------------
Core rotation orchestration. Pulls the current secret, delegates
credential generation and target update to the appropriate adapter,
then writes the new value back to Secrets Manager.

Idempotency: if the secret was rotated within ROTATION_WINDOW_HOURS,
the engine skips rotation and returns a no-op result.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .adapters.rds import RDSMasterAdapter, RDSUserAdapter
from .adapters.api_key import APIKeyAdapter
from .notifier import Notifier
from ..utils.aws_clients import get_client

logger = logging.getLogger(__name__)

ADAPTER_REGISTRY: dict[str, type] = {
    "rds_master": RDSMasterAdapter,
    "rds_user":   RDSUserAdapter,
    "api_key":    APIKeyAdapter,
}

DEFAULT_ROTATION_WINDOW_HOURS = 24


@dataclass
class RotationResult:
    success: bool
    message: str
    skipped: bool = False


class RotationEngine:
    """
    Orchestrates a full rotation cycle for a single secret.

    Usage:
        engine = RotationEngine(strategy="api_key")
        result = engine.rotate("arn:aws:secretsmanager:...")
    """

    def __init__(self, strategy: str = "api_key") -> None:
        if strategy not in ADAPTER_REGISTRY:
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                f"Valid options: {list(ADAPTER_REGISTRY)}"
            )
        self.strategy = strategy
        self.adapter = ADAPTER_REGISTRY[strategy]()
        self.sm = get_client("secretsmanager")
        self.notifier = Notifier(
            topic_arn=os.environ.get("SNS_TOPIC_ARN", "")
        )
        self.window_hours = int(os.environ.get("ROTATION_WINDOW_HOURS", DEFAULT_ROTATION_WINDOW_HOURS))

    def rotate(self, secret_arn: str) -> RotationResult:
        """Execute a full rotation for the given secret ARN."""
        logger.info("Starting rotation for %s using %s", secret_arn, self.strategy)

        try:
            meta = self._describe_secret(secret_arn)
        except ClientError as exc:
            msg = f"Failed to describe secret: {exc}"
            logger.error(msg)
            self.notifier.notify(secret_arn, success=False, message=msg)
            return RotationResult(success=False, message=msg)

        if self._within_rotation_window(meta):
            msg = f"Secret rotated within the last {self.window_hours}h; skipping."
            logger.info(msg)
            return RotationResult(success=True, message=msg, skipped=True)

        try:
            current_secret = self._get_secret_value(secret_arn)
            new_secret = self.adapter.generate_secret(current_secret)
            self.adapter.update_target(new_secret)
            self._put_secret_value(secret_arn, new_secret)
        except Exception as exc:
            msg = f"Rotation failed: {exc}"
            logger.exception(msg)
            self.notifier.notify(secret_arn, success=False, message=msg)
            return RotationResult(success=False, message=msg)

        msg = f"Successfully rotated {secret_arn}"
        logger.info(msg)
        self.notifier.notify(secret_arn, success=True, message=msg)
        return RotationResult(success=True, message=msg)

    def _describe_secret(self, secret_arn: str) -> dict[str, Any]:
        return self.sm.describe_secret(SecretId=secret_arn)

    def _get_secret_value(self, secret_arn: str) -> dict[str, Any]:
        resp = self.sm.get_secret_value(SecretId=secret_arn)
        raw = resp.get("SecretString") or resp.get("SecretBinary", "{}")
        return json.loads(raw)

    def _put_secret_value(self, secret_arn: str, value: dict[str, Any]) -> None:
        self.sm.put_secret_value(
            SecretId=secret_arn,
            SecretString=json.dumps(value),
        )

    def _within_rotation_window(self, meta: dict[str, Any]) -> bool:
        last_changed = meta.get("LastChangedDate")
        if not last_changed:
            return False
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.window_hours)
        return last_changed > cutoff
