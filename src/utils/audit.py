"""
vaultkey.utils.audit
--------------------
DynamoDB audit logger. Records every rotation attempt with full metadata
to satisfy SOC 2 CC6.1 and ISO 27001 A.9.4 audit trail requirements.

Table schema (provisioned by SAM template):
    PK:  secret_arn   (String)  -- partition key
    SK:  timestamp    (String)  -- sort key (ISO 8601 UTC)
    Attributes:
        strategy, success, message, request_id, ttl
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from .aws_clients import get_client

logger = logging.getLogger(__name__)

_AUDIT_TTL_DAYS = 365  # 1-year retention, configurable via env


class AuditLogger:
    def __init__(self, table_name: str, request_id: str = "") -> None:
        self.table_name = table_name
        self.request_id = request_id
        self._dynamo = None

    @property
    def dynamo(self) -> Any:
        if self._dynamo is None:
            self._dynamo = get_client("dynamodb")
        return self._dynamo

    def record(
        self,
        secret_arn: str,
        strategy: str,
        success: bool,
        message: str,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        ttl = int(time.time()) + _AUDIT_TTL_DAYS * 86400

        item = {
            "secret_arn":  {"S": secret_arn},
            "timestamp":   {"S": now.isoformat()},
            "strategy":    {"S": strategy},
            "success":     {"BOOL": success},
            "message":     {"S": message},
            "request_id":  {"S": self.request_id},
            "ttl":         {"N": str(ttl)},
        }

        try:
            self.dynamo.put_item(TableName=self.table_name, Item=item)
            logger.info(
                "Audit record written: secret=%s success=%s", secret_arn, success
            )
        except Exception as exc:
            # Audit failure must not abort the Lambda invocation
            logger.error("Failed to write audit record: %s", exc)
