"""The raw model: dbt reads the file versions the pointer names, and a later build replaces only
the station and day whose version changed."""

import gzip
import hashlib
import shutil
from datetime import date

import duckdb
import pytest
from test_registry import PROJECT, build

from airquality import openaq
from airquality.ingest import Event, ingest
from airquality.storage import DirectoryStorage, SqlitePointer

STATION, DAYS = "3019", [date(2025, 1, d) for d in (1, 2, 3)]


def real(day: date) -> bytes:
    return (openaq.FIXTURES / openaq.key(STATION, day)).read_bytes()


def file(day: date) -> str:
    return f"openaq/{openaq.key(STATION, day)}"


def deliver(storage, pointer, day: date, content: bytes, sequencer: str) -> str:
    """Land a file and ingest it, as a delivery does. Returns its version."""
    storage.write(f"landing/{file(day)}", content)
    event = Event(f"landing/{file(day)}", hashlib.md5(content).hexdigest(), sequencer)
    assert ingest(event, storage, pointer).status == "validated"
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def project(tmp_path):
    ignore = shutil.ignore_patterns("target", "logs")
    return shutil.copytree(PROJECT, tmp_path / "dbt_project", ignore=ignore)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQUALITY_STORE", str(tmp_path / "store"))
    storage = DirectoryStorage(tmp_path / "store")
    (tmp_path / "store").mkdir()
    return storage, SqlitePointer(tmp_path / "store" / "pointer.sqlite")


def rows(database) -> dict[str, tuple[int, str]]:
    """For each file in the raw table: its number of rows, and its version."""
    con = duckdb.connect(str(database))  # as dbt opened it, and still holds it
    found = con.execute("SELECT file, count(*), any_value(version) FROM raw GROUP BY file")
    return {name: (count, version) for name, count, version in found.fetchall()}


def test_dbt_reads_every_row_of_the_versions_the_pointer_names(
    project, store, tmp_path, monkeypatch
):
    versions = {day: deliver(*store, day, real(day), "0A") for day in DAYS}
    database = tmp_path / "candidate.duckdb"
    ended = build(project, database, monkeypatch)
    assert {ended[name] for name in ("current_file", "raw")} == {"success"}
    assert "fail" not in ended.values() and "error" not in ended.values()
    lines = {day: len(gzip.decompress(real(day)).decode().splitlines()) - 1 for day in DAYS}
    assert rows(database) == {file(day): (lines[day], versions[day]) for day in DAYS}

    con = duckdb.connect(str(database))  # as dbt opened it, and still holds it
    first = "SELECT station_id, day, sensor_id, parameter, value FROM raw ORDER BY stamped_at, 3"
    assert con.execute(first).fetchone() == ("3019", DAYS[0], "1300119", "pm25", "26.81")


def test_a_second_build_replaces_only_the_station_and_day_whose_version_changed(
    project, store, tmp_path, monkeypatch
):
    storage, pointer = store
    versions = {day: deliver(storage, pointer, day, real(day), "0A") for day in DAYS}
    database = tmp_path / "candidate.duckdb"
    build(project, database, monkeypatch)
    before = rows(database)

    lines = gzip.decompress(real(DAYS[1])).decode().splitlines()
    shorter = gzip.compress(("\n".join(lines[:7]) + "\n").encode())  # six rows
    reissued = deliver(storage, pointer, DAYS[1], shorter, "0B")
    # The other days' copies are taken away: a build that read them again would fail.
    for day in (DAYS[0], DAYS[2]):
        (storage.root / "validated" / file(day) / versions[day]).unlink()

    ended = build(project, database, monkeypatch)
    assert "fail" not in ended.values() and "error" not in ended.values()
    after = rows(database)
    assert after[file(DAYS[1])] == (6, reissued)
    assert {name: after[name] for name in (file(DAYS[0]), file(DAYS[2]))} == {
        name: before[name] for name in (file(DAYS[0]), file(DAYS[2]))
    }


def test_an_empty_store_gives_an_empty_raw_table(project, store, tmp_path, monkeypatch):
    database = tmp_path / "candidate.duckdb"
    ended = build(project, database, monkeypatch)
    assert {ended[name] for name in ("current_file", "raw")} == {"success"}
    assert "fail" not in ended.values() and rows(database) == {}


def test_a_raw_row_of_a_version_no_longer_current_fails_the_test_that_guards_it(
    project, store, tmp_path, monkeypatch
):
    storage, pointer = store
    deliver(storage, pointer, DAYS[0], real(DAYS[0]), "0A")
    database = tmp_path / "candidate.duckdb"
    build(project, database, monkeypatch)
    con = duckdb.connect(str(database))
    first = "(SELECT min(stamped_at) FROM raw)"
    con.execute(f"UPDATE raw SET version = 'an older version' WHERE stamped_at = {first}")
    con.close()
    ended = build(project, database, monkeypatch)
    assert ended["raw_holds_the_current_versions"] == "fail"
