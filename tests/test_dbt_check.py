"""The dbt check, run against the real store and catalog of `compose.yaml`.

Like the lakehouse test, it is skipped when they are not running, and CI requires it.
"""

import os
import time
import urllib.request

import pytest

from airquality.checks.dbt_build import check, clean
from airquality.checks.lakehouse import CATALOG, connect


@pytest.fixture
def lake():
    try:
        urllib.request.urlopen(f"{CATALOG}/v1/config", timeout=3)
    except OSError:
        if os.environ.get("LAKEHOUSE_REQUIRED"):
            raise
        pytest.skip("the lakehouse is not running: start it with `docker compose up -d --wait`")
    con, schema = connect(), f"dbt_test_{time.time_ns()}"
    yield con, schema
    clean(con, schema)


def test_dbt_builds_an_incremental_model_and_the_catalog_refuses_the_rest(lake):
    con, schema = lake
    findings = check(con, schema)
    assert [finding.name for finding in findings if not finding.matches] == []
    assert len(findings) == 11
    clean(con, schema)
    left = con.execute(
        f"SELECT count(*) FROM information_schema.schemata WHERE schema_name = '{schema}'"
    ).fetchone()
    assert left == (0,)
