"""
vaultkey.handler
----------------
Lambda entrypoint. Triggered by EventBridge on a cron schedule or
invoked directly with a JSON payload containing the target secret ARN.

Event schema:
    {
        "secret_arn": "arn:aws:secretsmanager:...",
        "strategy":   "rds_master" | "rds_user" | "api_key"   (optional, overrides env)
    }
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .rotation_engine import RotationEngine, RotationResult
from ..utils.audit import AuditLogger

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Main Lambda handler. Resolves the secret ARN from the event or
    from an SNS/EventBridge envelope, then delegates to RotationEngine.
    """
    logger.info("vaultkey invoked", extra={"event": json.dumps(event)})

    secret_arn = _resolve_secret_arn(event)
    strategy = event.get("strategy") or os.environ.get("ROTATION_STRATEGY", "api_key")

    if not secret_arn:
        return _response(400, "secret_arn is required")

    engine = RotationEngine(strategy=strategy)
    audit = AuditLogger(
        table_name=os.environ.get("AUDIT_TABLE", "vaultkey-audit"),
        request_id=context.aws_request_id,
    )

    result: RotationResult = engine.rotate(secret_arn)

    audit.record(
        secret_arn=secret_arn,
        strategy=strategy,
        success=result.success,
        message=result.message,
    )

    status = 200 if result.success else 500
    return _response(status, result.message)


def _resolve_secret_arn(event: dict[str, Any]) -> str | None:
    """
    Handles three event shapes:
    1. Direct invocation:  {"secret_arn": "arn:..."}
    2. EventBridge detail: {"detail": {"secret_arn": "arn:..."}}
    3. SNS envelope:       {"Records": [{"Sns": {"Message": "{\"secret_arn\": ...}"}}]}
    """
    if "secret_arn" in event:
        return event["secret_arn"]

    if "detail" in event and "secret_arn" in event["detail"]:
        return event["detail"]["secret_arn"]

    records = event.get("Records", [])
    if records and records[0].get("EventSource") == "aws:sns":
        try:
            msg = json.loads(records[0]["Sns"]["Message"])
            return msg.get("secret_arn")
        except (json.JSONDecodeError, KeyError):
            pass

    return None


def _response(status: int, message: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "body": json.dumps({"message": message}),
    }
