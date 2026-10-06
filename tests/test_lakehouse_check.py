"""The lakehouse check, run against the real store and catalog of `compose.yaml`.

It is skipped when they are not running, so the tests still pass on a machine without Docker.
CI starts them and sets LAKEHOUSE_REQUIRED, which turns a skip into a failure.
"""

import os
import time
import urllib.request

import pytest

from airquality.checks.lakehouse import CATALOG, SCHEMA, Finding, check, connect


@pytest.fixture
def lake():
    try:
        urllib.request.urlopen(f"{CATALOG}/v1/config", timeout=3)
    except OSError:
        if os.environ.get("LAKEHOUSE_REQUIRED"):
            raise
        pytest.skip("the lakehouse is not running: start it with `docker compose up -d --wait`")
    # A new name each time: dropping a table leaves its files in the store, and a table created
    # again under the same name would count them.
    con, table = connect(), f"test_{time.time_ns()}"
    yield con, table
    con.execute(f"DROP TABLE IF EXISTS lake.{SCHEMA}.{table}")


def test_duckdb_writes_an_iceberg_table_and_reads_an_earlier_snapshot(lake):
    findings = check(*lake)
    assert [finding.name for finding in findings if not finding.matches] == []
    assert len(findings) == 5


def test_a_finding_matches_only_when_found_equals_expected():
    assert Finding("Rows read now", "3", "3").matches
    assert not Finding("Rows read now", "3", "2").matches
