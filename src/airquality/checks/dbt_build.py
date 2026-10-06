"""Task 0.3: dbt builds a model into the Iceberg catalog, and what the catalog refuses is recorded.

    make dbt-check                                  starts the store and the catalog, then runs this
    uv run python -m airquality.checks.dbt_build    runs this against a stack that is already up

The dbt project is `dbt_check/`. Each step is printed next to what was expected with the pinned
versions. The last line is PASS or FAIL, and the exit code is 1 on FAIL.
"""

import contextlib
import io
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from dbt.adapters.duckdb.__version__ import version as adapter_version
from dbt.cli.main import dbtRunner
from dbt.version import __version__ as dbt_version

from airquality.checks.lakehouse import CATALOG, Finding, connect

PROJECT = Path(__file__).parents[3] / "dbt_check"
# What the Iceberg catalog answers, through DuckDB, to the three things it refuses.
NO_TABLE = "Catalog Error: This table ({}__dbt_tmp) was modified already, can't be renamed!"
NO_VIEW = "Not implemented Error: Create View"
NO_REFRESH = (
    "TransactionContext Error: Failed to commit: Failed to commit Iceberg transaction: "
    "Table {}__dbt_tmp does not exist"
)


def build(schema: str, *args: str) -> str:
    """Run `dbt build` on the check project in `schema`: "ok", or the last line of its error."""
    os.environ["DBT_CHECK_SCHEMA"] = schema  # profiles.yml reads it
    paths = ["--project-dir", str(PROJECT), "--profiles-dir", str(PROJECT)]
    # Run from a folder that is thrown away: dbt writes its working files there, and DuckDB leaves
    # an empty `data` folder wherever it creates an Iceberg table from a query.
    with tempfile.TemporaryDirectory() as scratch, contextlib.chdir(scratch):
        paths += ["--target-path", scratch, "--log-path", scratch]
        with contextlib.redirect_stdout(io.StringIO()):
            result = dbtRunner().invoke(["build", *paths, *args])
    if result.success:
        return "ok"
    failed = [node.message for node in result.result or [] if node.status in ("error", "fail")]
    return (failed[0] if failed else str(result.exception)).strip().splitlines()[-1].strip()


def check(con: duckdb.DuckDBPyConnection, schema: str) -> list[Finding]:
    """Build the project twice, then try what the catalog refuses. `con` reads the results."""

    def one(sql: str) -> str:
        return str(con.execute(sql.format(f"lake.{schema}")).fetchone()[0])

    def model_as(kind: str) -> str:
        chosen = f'{{"as": "{kind}", "named": "as_{kind}"}}'
        return build(schema, "--select", "readings", "--vars", chosen)

    snapshots = "SELECT count(*) FROM iceberg_snapshots({}.readings)"
    kept = "SELECT count(*) FROM iceberg_snapshots({}.readings__dbt_backup)"
    tables = (
        "SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM information_schema.tables "
        f"WHERE table_catalog = 'lake' AND table_schema = '{schema}'"
    )
    first, again = build(schema), build(schema)
    rows, seeded = one("SELECT count(*) FROM {}.readings"), one("SELECT count(*) FROM {}.units")
    findings = [
        Finding("dbt build: a seed, an incremental model and its two tests", "ok", first),
        Finding("dbt build a second time", "ok", again),
        Finding("Rows in the model's table after two builds, which replace rows by id", "2", rows),
        Finding("Rows in the seed's table after two builds", "2", seeded),
        Finding("Snapshots of the model's table after two builds", "3", one(snapshots)),
        Finding("The model as a plain table", NO_TABLE.format("as_table"), model_as("table")),
        Finding("The model as a view", NO_VIEW, model_as("view")),
        Finding(
            "The model with --full-refresh",
            NO_REFRESH.format("readings"),
            build(schema, "--select", "readings", "--full-refresh"),
        ),
    ]
    # The refused full refresh is not undone: the old table is renamed and a new one takes its name.
    return findings + [
        Finding("Tables after it", "readings, readings__dbt_backup, units", one(tables)),
        Finding("Snapshots of the model's table after it", "1", one(snapshots)),
        Finding("Snapshots of the table it left behind, readings__dbt_backup", "3", one(kept)),
    ]


def clean(con: duckdb.DuckDBPyConnection, schema: str) -> None:
    """Drop every table of `schema`, and the schema."""
    listed = con.execute(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_catalog = 'lake' AND table_schema = '{schema}'"
    ).fetchall()
    for (table,) in listed:
        con.execute(f'DROP TABLE lake.{schema}."{table}"')
    con.execute(f"DROP SCHEMA IF EXISTS lake.{schema}")


def main() -> int:
    try:
        con = connect()
    except duckdb.Error as error:
        print(f"Could not attach the catalog at {CATALOG}: {error}")
        print("Is the stack up? `make dbt-check` starts it and runs this check.\nFAIL")
        return 1
    schema = f"dbt_check_{time.time_ns()}"  # never used before, so runs cannot disturb each other
    try:
        findings = check(con, schema)
    finally:  # leave the catalog as it was, so the check can run any number of times
        clean(con, schema)
    versions = f"dbt-core {dbt_version}, dbt-duckdb {adapter_version}, DuckDB {duckdb.__version__}"
    print(f"dbt check (task 0.3), {versions}")
    print(
        f"Run at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC with: python -m airquality.checks.dbt_build"
    )
    for finding in findings:
        status = "match  " if finding.matches else "DIFFERS"
        print(f"\n[{status}] {finding.name}")
        print(f"    expected: {finding.expected}\n    found:    {finding.found}")
    passed = all(finding.matches for finding in findings)
    print("\nPASS" if passed else "\nFAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
