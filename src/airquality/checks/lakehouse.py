"""Task 0.2: DuckDB writes an Iceberg table through the REST catalog and reads an earlier snapshot.

    make lakehouse                                  starts the store and the catalog, then runs this
    uv run python -m airquality.checks.lakehouse    runs this against a stack that is already up

Each step is printed next to what was expected. The last line is PASS or FAIL, and the exit code
is 1 on FAIL. The store and the catalog are the two services in `compose.yaml`.
"""

import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

CATALOG = "http://localhost:8181"
STORE = "localhost:9000"
KEY, SECRET = "lakeadmin", "lakepassword"  # the local store's own, set in compose.yaml
SCHEMA = "lakehouse_check"


@dataclass
class Finding:
    name: str
    expected: str
    found: str

    @property
    def matches(self) -> bool:
        return self.expected == self.found


def connect() -> duckdb.DuckDBPyConnection:
    """A DuckDB session with the catalog attached as `lake` and the store's key loaded."""
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL iceberg; LOAD iceberg")
    con.execute(
        f"CREATE SECRET (TYPE s3, KEY_ID '{KEY}', SECRET '{SECRET}', ENDPOINT '{STORE}', "
        "URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')"
    )
    # The catalog has no login, and it hands out no keys: DuckDB uses the secret above.
    con.execute(
        f"ATTACH 'warehouse' AS lake (TYPE iceberg, ENDPOINT '{CATALOG}', "
        "AUTHORIZATION_TYPE 'none', ACCESS_DELEGATION_MODE 'none')"
    )
    return con


def check(con: duckdb.DuckDBPyConnection, table: str) -> list[Finding]:
    """Create `table`, insert twice, and read it as it is now and as it was after one insert."""
    name = f"lake.{SCHEMA}.{table}"

    def one(sql: str) -> str:
        return str(con.execute(sql).fetchone()[0])

    con.execute(f"CREATE SCHEMA IF NOT EXISTS lake.{SCHEMA}")
    con.execute(f"CREATE TABLE {name} (id INTEGER, reading VARCHAR)")
    listed = one(
        "SELECT count(*) FROM information_schema.tables "
        f"WHERE table_catalog = 'lake' AND table_schema = '{SCHEMA}' AND table_name = '{table}'"
    )
    con.execute(f"INSERT INTO {name} VALUES (1, 'first'), (2, 'first')")
    con.execute(f"INSERT INTO {name} VALUES (3, 'second')")
    snapshots = con.execute(
        f"SELECT snapshot_id FROM iceberg_snapshots({name}) ORDER BY sequence_number"
    ).fetchall()
    earlier = f"SELECT count(*) FROM {name} AT (VERSION => {snapshots[0][0]})" if snapshots else ""
    files = one(f"SELECT count(*) FROM glob('s3://warehouse/{SCHEMA}/{table}/data/*.parquet')")
    return [
        Finding("Tables of that name in the catalog after CREATE TABLE", "1", listed),
        Finding("Snapshots after two inserts", "2", str(len(snapshots))),
        Finding("Rows read now", "3", one(f"SELECT count(*) FROM {name}")),
        Finding("Rows read at the first snapshot", "2", one(earlier) if earlier else "no snapshot"),
        Finding("Parquet data files of the table in the store", "2", files),
    ]


def main() -> int:
    try:
        con = connect()
    except duckdb.Error as error:
        print(f"Could not attach the catalog at {CATALOG}: {error}")
        print("Is the stack up? `make lakehouse` starts it and runs this check.\nFAIL")
        return 1
    table = f"run_{time.time_ns()}"  # never used before: a dropped table leaves its files behind
    try:
        findings = check(con, table)
    finally:  # leave the catalog as it was, so the check can run any number of times
        con.execute(f"DROP TABLE IF EXISTS lake.{SCHEMA}.{table}")
    print(f"Lakehouse check (task 0.2), DuckDB {duckdb.__version__}")
    print(
        f"Run at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC with: python -m airquality.checks.lakehouse"
    )
    print(f"Catalog: {CATALOG}   Store: http://{STORE}")
    for finding in findings:
        status = "match  " if finding.matches else "DIFFERS"
        print(f"\n[{status}] {finding.name}")
        print(f"    expected: {finding.expected}\n    found:    {finding.found}")
    passed = all(finding.matches for finding in findings)
    print("\nPASS" if passed else "\nFAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
