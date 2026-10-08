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

dbt-check:  ## start the object store and the Iceberg catalog, then run the dbt check
	docker compose up -d --wait
	uv run python -m airquality.checks.dbt_build

seeds:  ## load the vocabulary and the registry into the candidate database, and test them
	uv run dbt build --project-dir dbt_project --profiles-dir dbt_project

.PHONY: setup lint test check lakehouse dbt-check seeds
