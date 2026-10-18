"""The hourly model: an hour is named by its start, duplicates count once, and conflicting,
non-numeric or out-of-range hours are invalid with their reason. A later build replaces only
the station and day whose file changed."""

import gzip
import hashlib
import shutil
from datetime import UTC, date, datetime

import duckdb
import pytest
from test_registry import PROJECT, build

from airquality import contracts, openaq
from airquality.ingest import Event, ingest
from airquality.storage import DirectoryStorage, SqlitePointer

STATION, DAYS = "3019", [date(2025, 1, d) for d in (1, 2, 3)]
STREAM = "openaq/1300119/pm25"


def lines(day: date) -> list[str]:
    content = (openaq.FIXTURES / openaq.key(STATION, day)).read_bytes()
    return gzip.decompress(content).decode("utf-8").splitlines()


def packed(rows: list[str]) -> bytes:
    return gzip.compress(("\n".join(rows) + "\n").encode("utf-8"))


def pm25(day: date, stamp: str) -> str:
    """The real PM2.5 line of a day whose time is `stamp`, like 01:00."""
    return next(line for line in lines(day) if '"pm25"' in line and f"T{stamp}:00+01:00" in line)


def deliver(storage, pointer, day: date, content: bytes, sequencer: str) -> None:
    key = f"landing/openaq/{openaq.key(STATION, day)}"
    storage.write(key, content)
    event = Event(key, hashlib.md5(content).hexdigest(), sequencer)
    assert ingest(event, storage, pointer).status == "validated"


@pytest.fixture
def project(tmp_path):
    ignore = shutil.ignore_patterns("target", "logs")
    return shutil.copytree(PROJECT, tmp_path / "dbt_project", ignore=ignore)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQUALITY_STORE", str(tmp_path / "store"))
    (tmp_path / "store").mkdir()
    return DirectoryStorage(tmp_path / "store"), SqlitePointer(
        tmp_path / "store" / "pointer.sqlite"
    )


def hours(database) -> dict[datetime, tuple]:
    """Each hour of the PM2.5 stream: value, valid, reason, rows found, version (first 8)."""
    con = duckdb.connect(str(database))  # as dbt opened it, and still holds it
    found = con.execute(
        "SELECT hour_start AT TIME ZONE 'UTC', value, is_valid, invalid_reason, rows_found, "
        "left(version, 8) FROM hourly WHERE datastream_key = ? ORDER BY 1",
        [STREAM],
    ).fetchall()
    return {row[0].replace(tzinfo=UTC): row[1:] for row in found}


def built(project, tmp_path, monkeypatch) -> dict[datetime, tuple]:
    database = tmp_path / "candidate.duckdb"
    ended = build(project, database, monkeypatch)
    assert ended["hourly"] == "success"
    assert "fail" not in ended.values() and "error" not in ended.values()
    return hours(database)


def utc(day: int, hour: int) -> datetime:
    return datetime(
        2024 if day == 0 else 2025, 12 if day == 0 else 1, 31 if day == 0 else day, hour, tzinfo=UTC
    )


def test_an_hour_is_named_by_its_start_and_only_the_pinned_sensor_is_read(
    project, store, tmp_path, monkeypatch
):
    deliver(*store, DAYS[0], packed(lines(DAYS[0])), "0A")
    found = built(project, tmp_path, monkeypatch)
    # OpenAQ stamps 01:00 Berlin (00:00 UTC) for the hour from midnight; its start is 23:00 UTC.
    assert pm25(DAYS[0], "01:00").endswith('"pm25","µg/m³","26.81"')
    assert found[utc(0, 23)][:2] == (26.81, True)
    # The day's last stamp, 00:00 on 2 January in Berlin, is the hour from 23:00 on 1 January.
    assert max(found) == utc(1, 22)
    assert len(found) == 24  # the file's 72 rows are 24 hours of PM2.5, PM10 and NO2
    con = duckdb.connect(str(tmp_path / "candidate.duckdb"))
    assert con.execute("SELECT DISTINCT parameter FROM hourly").fetchall() == [("pm25",)]


def test_duplicates_conflicts_and_values_out_of_range(project, store, tmp_path, monkeypatch):
    rows = lines(DAYS[0])
    one, two, three, four = (pm25(DAYS[0], f"0{h}:00") for h in (1, 2, 3, 4))
    five = pm25(DAYS[0], "05:00")
    broken = [line for line in rows if line not in (three, four, five)] + [
        one,  # an identical duplicate of 01:00
        two.replace('"161.66"', '"170.00"'),  # a second, different value for 02:00
        three.replace('"93.92"', '"1500"'),  # above the valid range of 0 to 1000
        four.replace('"31.35"', '"-1"'),  # below it
        five.replace('"25.57"', '"n/a"'),  # not a number
    ]
    deliver(*store, DAYS[0], packed(broken), "0A")
    found = built(project, tmp_path, monkeypatch)
    assert found[utc(0, 23)][:4] == (26.81, True, None, 2)  # duplicate kept once
    assert found[utc(1, 0)][:4] == (None, False, "conflicting values", 2)
    assert found[utc(1, 1)][:4] == (1500.0, False, "out of range", 1)
    assert found[utc(1, 2)][:4] == (-1.0, False, "out of range", 1)
    assert found[utc(1, 3)][:4] == (None, False, "not a number", 1)
    assert found[utc(1, 4)][:3] == (20.49, True, None)


def test_a_later_build_replaces_only_the_day_whose_file_changed(
    project, store, tmp_path, monkeypatch
):
    storage, pointer = store
    for day in DAYS:
        deliver(storage, pointer, day, packed(lines(day)), "0A")
    before = built(project, tmp_path, monkeypatch)
    assert len(before) == 72
    old = before[utc(2, 11)][4]  # the version of 2 January's file
    day_two = {hour for hour, row in before.items() if row[4] == old}
    assert len(day_two) == 24

    corrected = lines(DAYS[1])
    one_pm = pm25(DAYS[1], "13:00")  # stamped 13:00 in Berlin: the hour from 11:00 UTC
    corrected[corrected.index(one_pm)] = one_pm.rsplit(",", 1)[0] + ',"999.5"'
    deliver(storage, pointer, DAYS[1], packed(corrected), "0B")
    after = built(project, tmp_path, monkeypatch)

    assert after[utc(2, 11)][:2] == (999.5, True)
    assert {hour for hour, row in after.items() if row[4] != old and hour in day_two} == day_two
    assert all(after[hour] == row for hour, row in before.items() if hour not in day_two)


def test_a_correction_that_drops_the_pinned_sensor_removes_its_hours(
    project, store, tmp_path, monkeypatch
):
    storage, pointer = store
    for day in DAYS:
        deliver(storage, pointer, day, packed(lines(day)), "0A")
    before = built(project, tmp_path, monkeypatch)
    rows = lines(DAYS[1])
    deliver(
        storage, pointer, DAYS[1], packed([line for line in rows if '"pm25"' not in line]), "0B"
    )
    after = built(project, tmp_path, monkeypatch)
    assert len(after) == 48
    assert all(after[h] == before[h] for h in after)


def test_a_line_of_the_pinned_sensor_under_another_parameter_is_left_out(
    project, store, tmp_path, monkeypatch
):
    rows = lines(DAYS[0])
    one = pm25(DAYS[0], "01:00")
    rows[rows.index(one)] = one.replace('"pm25"', '"pm10"')  # the PM2.5 sensor, labelled PM10
    deliver(*store, DAYS[0], packed(rows), "0A")
    found = built(project, tmp_path, monkeypatch)
    assert utc(0, 23) not in found and len(found) == 23


def test_openaq_calls_each_parameter_as_the_vocabulary_does():
    # hourly.sql matches a line's parameter to the registry's directly, which holds only while
    # the contract maps each vocabulary parameter to a source name equal to it.
    openaq_contract = contracts.load("openaq")
    assert {name: entry.name for name, entry in openaq_contract.parameters.items()} == {
        "pm25": "pm25"
    }
