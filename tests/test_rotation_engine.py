"""
tests/test_rotation_engine.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.rotator.rotation_engine import RotationEngine, RotationResult


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:vaultkey-test")
    monkeypatch.setenv("AUDIT_TABLE", "vaultkey-audit-test")
    monkeypatch.setenv("ROTATION_WINDOW_HOURS", "24")


@pytest.fixture
def mock_aws(mock_env):
    with patch("src.rotator.rotation_engine.get_client") as mock_get_client, \
         patch("src.rotator.notifier.get_client") as mock_notifier_client:
        sm = MagicMock()
        sns = MagicMock()
        mock_get_client.side_effect = lambda svc: sm if svc == "secretsmanager" else sns
        mock_notifier_client.return_value = sns
        yield sm, sns


class TestRotationEngine:

    def test_invalid_strategy_raises(self, mock_env):
        with pytest.raises(ValueError, match="Unknown strategy"):
            RotationEngine(strategy="invalid_strategy")

    def test_successful_api_key_rotation(self, mock_aws):
        sm, sns = mock_aws
        secret_arn = "arn:aws:secretsmanager:us-east-1:123:secret:my-key"
        current_secret = {"api_key": "old-key", "service": "test-service"}

        # Describe: no recent rotation
        sm.describe_secret.return_value = {
            "LastChangedDate": datetime.now(tz=timezone.utc) - timedelta(days=60)
        }
        sm.get_secret_value.return_value = {
            "SecretString": json.dumps(current_secret)
        }

        engine = RotationEngine(strategy="api_key")
        result = engine.rotate(secret_arn)

        assert result.success is True
        assert result.skipped is False
        sm.put_secret_value.assert_called_once()
        call_args = sm.put_secret_value.call_args[1]
        new_secret = json.loads(call_args["SecretString"])
        assert new_secret["api_key"] != "old-key"
        assert new_secret["service"] == "test-service"

    def test_skips_rotation_within_window(self, mock_aws):
        sm, _ = mock_aws
        sm.describe_secret.return_value = {
            "LastChangedDate": datetime.now(tz=timezone.utc) - timedelta(hours=1)
        }

        engine = RotationEngine(strategy="api_key")
        result = engine.rotate("arn:aws:secretsmanager:us-east-1:123:secret:recent")

        assert result.success is True
        assert result.skipped is True
        sm.put_secret_value.assert_not_called()

    def test_failure_on_describe_error(self, mock_aws):
        sm, sns = mock_aws
        from botocore.exceptions import ClientError
        sm.describe_secret.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
            "DescribeSecret",
        )

        engine = RotationEngine(strategy="api_key")
        result = engine.rotate("arn:aws:secretsmanager:us-east-1:123:secret:missing")

        assert result.success is False
        assert "Failed to describe secret" in result.message

    def test_failure_does_not_persist_secret(self, mock_aws):
        sm, _ = mock_aws
        sm.describe_secret.return_value = {
            "LastChangedDate": datetime.now(tz=timezone.utc) - timedelta(days=60)
        }
        sm.get_secret_value.return_value = {
            "SecretString": json.dumps({"api_key": "old-key"})
        }
        sm.put_secret_value.side_effect = Exception("DenyPolicy")

        engine = RotationEngine(strategy="api_key")
        result = engine.rotate("arn:aws:secretsmanager:us-east-1:123:secret:test")

        assert result.success is False
        assert "DenyPolicy" in result.message


class TestLambdaHandler:

    def test_handler_missing_secret_arn(self):
        from src.rotator.handler import lambda_handler
        ctx = MagicMock()
        ctx.aws_request_id = "test-request-id"

        with patch("src.rotator.handler.RotationEngine"), \
             patch("src.rotator.handler.AuditLogger"):
            resp = lambda_handler({}, ctx)

        assert resp["statusCode"] == 400

    def test_handler_resolves_eventbridge_envelope(self):
        from src.rotator.handler import _resolve_secret_arn
        event = {"detail": {"secret_arn": "arn:aws:secretsmanager:us-east-1:123:secret:x"}}
        assert _resolve_secret_arn(event) == "arn:aws:secretsmanager:us-east-1:123:secret:x"
