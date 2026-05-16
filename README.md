# vaultkey

Automated secrets rotation engine built on AWS Lambda, Secrets Manager, and EventBridge. Rotates database credentials, API keys, and arbitrary secrets on a configurable schedule and notifies stakeholders via SNS. Designed as a drop-in compliance primitive for SOC 2 and ISO 27001 environments.

## Architecture

```
EventBridge (cron) ──► Lambda Rotator ──► Secrets Manager
                              │
                              ├──► RDS / target system (credential update)
                              │
                              └──► SNS Topic ──► Email / Slack / PagerDuty
```

- **EventBridge** triggers rotation on a cron schedule (default: every 30 days)
- **Lambda** pulls the current secret, generates a new credential, updates the target system, and writes the new value back to Secrets Manager
- **SNS** emits an event on every rotation (success or failure) for downstream alerting
- **DynamoDB** stores an audit log of every rotation attempt with outcome, timestamp, and rotated-by metadata

## Features

- Multi-strategy rotation: RDS master password, RDS user password, arbitrary API key
- Pluggable target adapters (implement `TargetAdapter` to add new secret types)
- Idempotent: re-running a rotation within the same window is a no-op
- Dead-letter queue on the Lambda for failed rotation events
- AWS SAM template for one-command deploy

## Project Structure

```
vaultkey/
├── src/
│   ├── rotator/
│   │   ├── handler.py          # Lambda entrypoint
│   │   ├── rotation_engine.py  # Core rotation logic
│   │   ├── adapters/
│   │   │   ├── base.py         # Abstract adapter interface
│   │   │   ├── rds.py          # RDS password adapter
│   │   │   └── api_key.py      # Generic API key adapter
│   │   └── notifier.py         # SNS notification wrapper
│   └── utils/
│       ├── aws_clients.py      # Boto3 client factory (lazy, cached)
│       └── audit.py            # DynamoDB audit logger
├── infra/
│   └── template.yaml           # AWS SAM template
├── tests/
│   ├── test_rotation_engine.py
│   ├── test_rds_adapter.py
│   └── conftest.py
├── requirements.txt
├── requirements-dev.txt
└── Makefile
```

## Quick Start

### Prerequisites

- AWS CLI configured (`aws configure`)
- AWS SAM CLI (`brew install aws-sam-cli`)
- Python 3.11+

### Deploy

```bash
# Install dependencies
make install

# Run tests
make test

# Build and deploy to AWS
make deploy STACK_NAME=vaultkey-prod REGION=us-east-1

# Schedule a secret for rotation
aws events put-rule \
  --name rotate-my-db-secret \
  --schedule-expression "rate(30 days)" \
  --state ENABLED

# Invoke manually
make invoke SECRET_ARN=arn:aws:secretsmanager:us-east-1:123456789012:secret:my-db-secret
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `ROTATION_STRATEGY` | `rds_master`, `rds_user`, `api_key` | `api_key` |
| `SNS_TOPIC_ARN` | ARN of the notification topic | required |
| `AUDIT_TABLE` | DynamoDB table name for audit log | `vaultkey-audit` |
| `ROTATION_WINDOW_HOURS` | Hours within which re-rotation is skipped | `24` |

## Adding a Custom Adapter

```python
from src.rotator.adapters.base import TargetAdapter

class MyServiceAdapter(TargetAdapter):
    def generate_secret(self, current: dict) -> dict:
        # Generate a new credential dict
        return {"api_key": secrets.token_urlsafe(32)}

    def update_target(self, new_secret: dict) -> None:
        # Push the new credential to your service
        my_service_client.rotate_key(new_secret["api_key"])
```

Register it in `rotation_engine.py` under `ADAPTER_REGISTRY`.

## IAM Permissions Required

The Lambda execution role needs:
- `secretsmanager:GetSecretValue`
- `secretsmanager:PutSecretValue`
- `secretsmanager:DescribeSecret`
- `sns:Publish`
- `dynamodb:PutItem`
- `rds-db:connect` (if using RDS adapter)

The SAM template provisions a least-privilege role automatically.

## Compliance Notes

Every rotation is recorded in DynamoDB with: secret ARN, strategy used, outcome, timestamp (ISO 8601 UTC), and AWS request ID. This log satisfies audit trail requirements for SOC 2 CC6.1 and ISO 27001 A.9.4.
