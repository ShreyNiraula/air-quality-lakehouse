"""The station, sensor and datastream tables: dbt builds them from the registry, and their tests
catch a registry that would make them wrong."""

import shutil

import duckdb
import pytest
from test_registry import PROJECT, build, in_seed

KEYS = ["openaq/3019", "openaq/4762", "openaq/4767"]


@pytest.fixture
def project(tmp_path):
    """A copy of the dbt project that a test may change, without dbt's own working files."""
    ignore = shutil.ignore_patterns("target", "logs")
    return shutil.copytree(PROJECT, tmp_path / "dbt_project", ignore=ignore)


def test_dbt_builds_the_three_tables_from_the_registry(project, tmp_path, monkeypatch):
    ended = build(project, tmp_path / "candidate.duckdb", monkeypatch)
    assert [ended[name] for name in ("station", "sensor", "datastream")] == ["success"] * 3
    con = duckdb.connect(str(tmp_path / "candidate.duckdb"))
    stations = "SELECT station_key, station_name, city, timezone FROM station ORDER BY 1"
    assert con.execute(stations).fetchall() == [
        ("openaq/3019", "Berlin Mitte", "Berlin", "Europe/Berlin"),
        ("openaq/4762", "Berlin Schildhornstraße", "Berlin", "Europe/Berlin"),
        ("openaq/4767", "Berlin Frankfurter Allee", "Berlin", "Europe/Berlin"),
    ]
    sensors = "SELECT sensor_key, station_key, sensor_type FROM sensor ORDER BY 2"
    assert con.execute(sensors).fetchall() == [
        ("openaq/1300119", "openaq/3019", "reference monitor"),
        ("openaq/1300114", "openaq/4762", "reference monitor"),
        ("openaq/1300111", "openaq/4767", "reference monitor"),
    ]
    streams = "SELECT datastream_key, station_key, parameter, unit, start_date FROM datastream"
    rows = sorted(con.execute(streams).fetchall(), key=lambda row: row[1])
    assert [row[1] for row in rows] == KEYS
    assert rows[0][0] == "openaq/1300119/pm25"
    assert {row[2:4] for row in rows} == {("pm25", "ug/m3")}
    assert {str(row[4]) for row in rows} == {"2025-01-01"}


def second_parameter(project, change: tuple[str, str] = ("", "")):
    """Add PM10 to the vocabulary, and give Berlin Mitte a PM10 sensor, changing one text in it."""
    with open(project / "seeds" / "parameter.csv", "a", encoding="utf-8") as seed:
        seed.write("pm10,mass_concentration_of_pm10_ambient_aerosol_particles_in_air,")
        seed.write("ug/m3,0,1000,mean,,\n")
    row = (project / "seeds" / "registry.csv").read_text(encoding="utf-8").splitlines()[1]
    row = row.replace(",1300119,pm25,", ",6417,pm10,").replace(*change)
    with open(project / "seeds" / "registry.csv", "a", encoding="utf-8") as seed:
        seed.write(row + "\n")


@pytest.mark.parametrize(
    ("change", "failing"),
    [
        (second_parameter, []),
        (
            lambda p: second_parameter(p, ("Berlin Mitte", "Berlin-Mitte")),
            ["unique_station_station_key"],
        ),
        (
            lambda p: second_parameter(p, ("13.41883300000022", "13.42")),
            ["unique_station_station_key"],
        ),
    ],
    ids=[
        "a station with two parameters",
        "a station named two ways",
        "a station in two places",
    ],
)
def test_a_station_is_one_row_however_many_parameters_it_has(
    change,
    failing,
    project,
    tmp_path,
    monkeypatch,
):
    change(project)
    ended = build(project, tmp_path / "candidate.duckdb", monkeypatch)
    assert sorted(name for name, status in ended.items() if status == "fail") == failing
    assert "error" not in ended.values()
    if not failing:
        con = duckdb.connect(str(tmp_path / "candidate.duckdb"))
        assert con.execute("SELECT count(*) FROM station").fetchone() == (3,)
        assert con.execute("SELECT count(*) FROM sensor").fetchone() == (4,)
        assert con.execute("SELECT count(*) FROM datastream").fetchone() == (4,)


def test_a_sensor_of_a_source_with_no_type_fails_its_test(project, tmp_path, monkeypatch):
    # The registry's own test refuses the source too, so the tables are not built.
    in_seed(project, "registry.csv", "openaq,3019", "elsewhere,3019")
    ended = build(project, tmp_path / "candidate.duckdb", monkeypatch)
    assert ended["accepted_values_registry_source__openaq"] == "fail"
    assert {ended[name] for name in ("station", "sensor", "datastream")} == {"skipped"}
