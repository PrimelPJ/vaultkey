"""
vaultkey.utils.aws_clients
--------------------------
Lazy, cached Boto3 client factory.

Using module-level singletons keeps clients alive across Lambda
warm invocations, avoiding repeated TLS handshakes and auth refreshes.
"""

from __future__ import annotations

import os
import boto3
from botocore.config import Config

_CLIENTS: dict[str, object] = {}

_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)


def get_client(service: str) -> object:
    """
    Return a cached Boto3 client for the given service name.
    Thread-safe for Lambda's single-threaded execution model.
    """
    if service not in _CLIENTS:
        _CLIENTS[service] = boto3.client(service, config=_RETRY_CONFIG)
    return _CLIENTS[service]
