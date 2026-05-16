STACK_NAME  ?= vaultkey
REGION      ?= us-east-1
SECRET_ARN  ?=
STRATEGY    ?= api_key

.PHONY: install test lint build deploy invoke clean

install:
	pip install -r requirements.txt -r requirements-dev.txt

test:
	pytest tests/ -v --tb=short

lint:
	ruff check src/ tests/
	mypy src/

build:
	sam build --template infra/template.yaml

deploy: build
	sam deploy \
		--stack-name $(STACK_NAME) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM \
		--parameter-overrides RotationStrategy=$(STRATEGY) \
		--resolve-s3

invoke:
	@if [ -z "$(SECRET_ARN)" ]; then echo "Usage: make invoke SECRET_ARN=arn:..."; exit 1; fi
	aws lambda invoke \
		--function-name vaultkey-rotator \
		--payload '{"secret_arn":"$(SECRET_ARN)","strategy":"$(STRATEGY)"}' \
		--region $(REGION) \
		/dev/stdout

destroy:
	sam delete --stack-name $(STACK_NAME) --region $(REGION) --no-prompts

clean:
	rm -rf .aws-sam __pycache__ .pytest_cache .mypy_cache
