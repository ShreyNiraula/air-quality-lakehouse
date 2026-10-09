"""The vocabulary and the registry: dbt loads both seeds, and its tests catch a broken one."""

import contextlib
import io
import shutil

import duckdb
import pytest
from dbt.cli.main import dbtRunner

from airquality import manifests, registry

PROJECT = registry.SEEDS.parent


def build(project, database, monkeypatch) -> dict[str, str]:
    """Run `dbt build` on a copy of the project: each seed and test, and how it ended."""
    monkeypatch.setenv("AIRQUALITY_CANDIDATE", str(database))  # profiles.yml reads it
    paths = ["--project-dir", str(project), "--profiles-dir", str(project)]
    paths += ["--target-path", str(database.parent / "target")]
    paths += ["--log-path", str(database.parent / "logs")]
    with contextlib.redirect_stdout(io.StringIO()):
        result = dbtRunner().invoke(["build", *paths])
    assert result.exception is None, result.exception
    return {node.node.name: str(node.status) for node in result.result}


@pytest.fixture
def project(tmp_path):
    """A copy of the dbt project that a test may break, without dbt's own working files."""
    ignore = shutil.ignore_patterns("target", "logs")
    return shutil.copytree(PROJECT, tmp_path / "dbt_project", ignore=ignore)


def test_dbt_loads_both_seeds_and_their_tests_pass(project, tmp_path, monkeypatch):
    ended = build(project, tmp_path / "candidate.duckdb", monkeypatch)
    assert {ended.pop("parameter"), ended.pop("registry")} == {"success"}
    # The seeds' 27 tests, then task 1.15a's three tables and their 30 tests.
    assert {ended.pop(name) for name in ("station", "sensor", "datastream")} == {"success"}
    assert len(ended) == 57 and set(ended.values()) == {"pass"}
    con = duckdb.connect(str(tmp_path / "candidate.duckdb"))  # as dbt opened it, and still holds it
    pm25 = "SELECT * EXCLUDE (cf_standard_name, guideline_name) FROM parameter"
    assert con.execute(pm25).fetchall() == [("pm25", "ug/m3", 0.0, 1000.0, "mean", 15.0)]
    kinds = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE registry)").fetchall())
    assert [kinds[name] for name in ("station_id", "sensor_id", "start_date")] == [
        *("VARCHAR", "VARCHAR"),
        "DATE",
    ]
    stations = "SELECT count(*), count(DISTINCT station_id), min(station_id) FROM registry"
    assert con.execute(stations).fetchone() == (3, 3, "3019")


def in_seed(project, name, old, new):
    seed = project / "seeds" / name
    text = seed.read_text(encoding="utf-8")
    assert old in text
    seed.write_text(text.replace(old, new), encoding="utf-8")


def second_sensor(project):
    """Give Berlin Mitte a second PM2.5 sensor."""
    row = (project / "seeds" / "registry.csv").read_text(encoding="utf-8").splitlines()[1]
    with open(project / "seeds" / "registry.csv", "a", encoding="utf-8") as seed:
        seed.write(row.replace(",1300119,", ",999,") + "\n")


@pytest.mark.parametrize(
    ("change", "failing"),
    [
        (second_sensor, ["registry_one_sensor_per_station_and_parameter"]),
        (
            lambda p: in_seed(p, "registry.csv", ",1300114,", ",1300119,"),
            ["registry_one_row_per_sensor"],
        ),
        (
            lambda p: in_seed(p, "registry.csv", ",pm25,", ",pm10,"),
            ["relationships_registry_parameter__parameter__ref_parameter_"],
        ),
        (
            lambda p: in_seed(p, "registry.csv", "openaq,3019", "elsewhere,3019"),
            ["accepted_values_registry_source__openaq"],
        ),
        (
            lambda p: in_seed(p, "parameter.csv", ",mean,", ",sum,"),
            ["accepted_values_parameter_aggregation__mean"],
        ),
        (
            lambda p: in_seed(p, "parameter.csv", ",0,1000,", ",1000,0,"),
            ["parameter_range_and_guideline"],
        ),
        (
            lambda p: in_seed(p, "parameter.csv", ",15,WHO", ",1500,WHO"),
            ["parameter_range_and_guideline"],
        ),
        (
            lambda p: in_seed(p, "parameter.csv", ",15,WHO 2021 24-hour guideline value", ",15,"),
            ["parameter_range_and_guideline"],
        ),
    ],
    ids=[
        "two sensors for one parameter",
        "one sensor at two stations",
        "a parameter not in the vocabulary",
        "an unknown source",
        "an aggregation that is not built",
        "an empty valid range",
        "a guideline outside the valid range",
        "a guideline with no name",
    ],
)
def test_a_broken_seed_fails_the_test_that_guards_it(
    change, failing, project, tmp_path, monkeypatch
):
    change(project)
    ended = build(project, tmp_path / "candidate.duckdb", monkeypatch)
    assert sorted(name for name, status in ended.items() if status == "fail") == failing
    assert "error" not in ended.values()


def test_the_committed_registry_is_what_the_manifests_give():
    committed = (registry.SEEDS / "registry.csv").read_text(encoding="utf-8")
    assert committed == registry.build()
    assert committed.count("\n") == 4  # the header, and Berlin's three monitors


def test_the_registry_keeps_the_chosen_cities_and_the_vocabulary_s_parameters():
    manifest, _ = manifests.read("openaq")
    rows = registry.rows(manifest, ("Berlin", "Wien"), ["pm25", "no2"])
    assert len(rows) == 6 and {row["parameter"] for row in rows} == {"pm25"}
    assert [row["city"] for row in rows] == ["Berlin"] * 3 + ["Wien"] * 3
    assert registry.rows(manifest, ("Berlin",), ["temperature"]) == []


def test_a_station_that_began_late_starts_on_its_first_local_day():
    station = {
        **dict.fromkeys(("id", "name", "provider", "latitude", "longitude"), "x"),
        "city": "Berlin",
        "timezone": "Europe/Berlin",
        "first_reading": "2025-03-31T22:30:00Z",  # half past midnight on 1 April in Berlin
        "sensors": [{"id": "7", "parameter": "pm25"}],
    }
    manifest = {
        "source": "openaq",
        "files": {"from": "2025-01-01"},
        "licence": {"name": "A licence", "credit": "A source"},
        "stations": [station, station | {"id": "y", "first_reading": "2016-11-21T11:00:00Z"}],
    }
    starts = [row["start_date"] for row in registry.rows(manifest, ("Berlin",), ["pm25"])]
    assert starts == ["2025-04-01", "2025-01-01"]
