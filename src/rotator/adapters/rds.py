"""
vaultkey.adapters.rds
---------------------
Adapters for rotating RDS credentials.

RDSMasterAdapter  -- rotates the master (admin) password via the RDS API.
RDSUserAdapter    -- rotates an application user password via psycopg2/pymysql.

Expected secret shape:
    {
        "engine":   "postgres" | "mysql",
        "host":     "mydb.cluster-xxx.us-east-1.rds.amazonaws.com",
        "port":     5432,
        "username": "app_user",
        "password": "current-password",
        "dbname":   "myapp"
    }
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from typing import Any

import boto3

from .base import TargetAdapter
from ...utils.aws_clients import get_client

logger = logging.getLogger(__name__)

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!#$%^&*()-_=+"
PASSWORD_LENGTH = 32


def _generate_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))


class RDSMasterAdapter(TargetAdapter):
    """
    Rotates the RDS cluster/instance master password via the AWS API.
    No direct database connection required -- AWS handles the credential
    propagation to the RDS control plane.
    """

    def __init__(self) -> None:
        self.rds = get_client("rds")
        self.db_instance_id = os.environ.get("RDS_INSTANCE_ID", "")

    def generate_secret(self, current: dict[str, Any]) -> dict[str, Any]:
        new_password = _generate_password()
        return {**current, "password": new_password}

    def update_target(self, new_secret: dict[str, Any]) -> None:
        instance_id = self.db_instance_id or new_secret.get("dbInstanceIdentifier", "")
        if not instance_id:
            raise ValueError(
                "RDS instance identifier not found. Set RDS_INSTANCE_ID env var "
                "or include 'dbInstanceIdentifier' in the secret."
            )
        logger.info("Updating master password for RDS instance %s", instance_id)
        self.rds.modify_db_instance(
            DBInstanceIdentifier=instance_id,
            MasterUserPassword=new_secret["password"],
            ApplyImmediately=True,
        )
        logger.info("Master password updated successfully for %s", instance_id)


class RDSUserAdapter(TargetAdapter):
    """
    Rotates an application-level database user password by connecting
    directly to the database and executing ALTER USER / SET PASSWORD.

    Requires psycopg2-binary (Postgres) or pymysql (MySQL) in the Lambda layer.
    """

    def generate_secret(self, current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "password": _generate_password()}

    def update_target(self, new_secret: dict[str, Any]) -> None:
        engine = new_secret.get("engine", "postgres").lower()
        if engine == "postgres":
            self._rotate_postgres(new_secret)
        elif engine == "mysql":
            self._rotate_mysql(new_secret)
        else:
            raise ValueError(f"Unsupported engine: {engine}")

    def _rotate_postgres(self, secret: dict[str, Any]) -> None:
        try:
            import psycopg2
        except ImportError:
            raise RuntimeError(
                "psycopg2-binary is required for Postgres rotation. "
                "Add it to the Lambda layer."
            )
        conn = psycopg2.connect(
            host=secret["host"],
            port=secret.get("port", 5432),
            dbname=secret["dbname"],
            user=secret["username"],
            password=secret["password"],
            connect_timeout=5,
            sslmode="require",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER USER %s WITH PASSWORD %s",
                    (secret["username"], secret["password"]),
                )
            conn.commit()
            logger.info("Postgres user password updated for %s", secret["username"])
        finally:
            conn.close()

    def _rotate_mysql(self, secret: dict[str, Any]) -> None:
        try:
            import pymysql
        except ImportError:
            raise RuntimeError(
                "pymysql is required for MySQL rotation. "
                "Add it to the Lambda layer."
            )
        conn = pymysql.connect(
            host=secret["host"],
            port=secret.get("port", 3306),
            db=secret["dbname"],
            user=secret["username"],
            password=secret["password"],
            connect_timeout=5,
            ssl={"ssl": True},
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER USER %s@'%%' IDENTIFIED BY %s",
                    (secret["username"], secret["password"]),
                )
            conn.commit()
            logger.info("MySQL user password updated for %s", secret["username"])
        finally:
            conn.close()
