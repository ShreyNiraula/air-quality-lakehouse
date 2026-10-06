setup:  ## install the pinned tools and turn on the git hooks
	uv sync --locked
	git config core.hooksPath .githooks

lint:  ## what the pre-commit hook runs
	.githooks/pre-commit

test:  ## what the pre-push hook runs
	.githooks/pre-push

check: lint test

lakehouse:  ## start the object store and the Iceberg catalog, then run the lakehouse check
	docker compose up -d --wait
	uv run python -m airquality.checks.lakehouse

.PHONY: setup lint test check lakehouse
