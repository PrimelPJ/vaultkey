"""
vaultkey.notifier
-----------------
SNS notification wrapper. Publishes rotation events so downstream
consumers (email, Slack via SNS filter, PagerDuty) can react.

Message schema:
    {
        "event":      "ROTATION_SUCCESS" | "ROTATION_FAILURE",
        "secret_arn": "arn:aws:secretsmanager:...",
        "message":    "Human-readable description",
        "timestamp":  "2024-01-15T10:30:00Z"
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .utils.aws_clients import get_client

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, topic_arn: str) -> None:
        self.topic_arn = topic_arn
        self._sns = None

    @property
    def sns(self) -> Any:
        if self._sns is None:
            self._sns = get_client("sns")
        return self._sns

    def notify(self, secret_arn: str, success: bool, message: str) -> None:
        if not self.topic_arn:
            logger.warning("SNS_TOPIC_ARN not set; skipping notification.")
            return

        event_type = "ROTATION_SUCCESS" if success else "ROTATION_FAILURE"
        payload = {
            "event":      event_type,
            "secret_arn": secret_arn,
            "message":    message,
            "timestamp":  datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            self.sns.publish(
                TopicArn=self.topic_arn,
                Subject=f"[vaultkey] {event_type}",
                Message=json.dumps(payload, indent=2),
                MessageAttributes={
                    "event_type": {
                        "DataType":    "String",
                        "StringValue": event_type,
                    }
                },
            )
            logger.info("Notification published: %s", event_type)
        except Exception as exc:
            # Notification failure must not abort the rotation result
            logger.error("Failed to publish SNS notification: %s", exc)
