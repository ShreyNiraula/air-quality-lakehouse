"""The OpenAQ adapter, without the network, and the test data it downloaded."""

import csv
import gzip
import hashlib
import io
from datetime import UTC, date, datetime

import pytest

from airquality import manifests, openaq
from airquality.contracts import load

DAY = "records/csv.gz/locationid=3019/year=2025/month=01/location-3019-20250101.csv.gz"
ITEM = (
    "<Contents><Key>{key}</Key><LastModified>2025-01-04T23:00:40.000Z</LastModified>"
    '<ETag>"734fa8766d4c446a95ca874b4047042d"</ETag><Size>685</Size></Contents>'
)
LISTING = (
    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "<IsTruncated>{cut}</IsTruncated>{items}</ListBucketResult>"
)


@pytest.fixture
def archive(monkeypatch):
    """Stands in for the archive: the addresses asked for, and what each one returns."""
    asked, answers = [], {}

    def fetch(url):
        asked.append(url)
        return answers.get(url, b"")

    monkeypatch.setattr(openaq, "fetch", fetch)
    return asked, answers


def test_the_key_of_a_station_and_day():
    assert openaq.key("3019", date(2025, 1, 1)) == DAY
    assert openaq.key("4762", date(2026, 12, 9)).endswith("/month=12/location-4762-20261209.csv.gz")


def test_a_key_names_its_station_and_day():
    assert openaq.named(DAY) == ("3019", date(2025, 1, 1))
    assert openaq.named("landing/openaq/location-4762-20261209.csv.gz") == (
        "4762",
        date(2026, 12, 9),
    )
    for other in ("location-3019-20250101.csv", "location-x-20250101.csv.gz", DAY + ".tmp", ""):
        with pytest.raises(ValueError, match="not the key of an OpenAQ day file"):
            openaq.named(other)
    with pytest.raises(ValueError):
        openaq.named("location-3019-20251345.csv.gz")


def test_find_lists_the_days_of_the_month_that_have_a_file(archive):
    asked, answers = archive
    other = DAY.replace("20250101", "20250103")
    items = ITEM.format(key=DAY) + ITEM.format(key=other) + ITEM.format(key=DAY + ".tmp")
    month = f"{openaq.ARCHIVE}/?list-type=2&prefix={DAY.rsplit('/', 1)[0]}/"
    answers[month] = LISTING.format(cut="false", items=items).encode()
    found = openaq.find("3019", date(2025, 1, 15))
    assert asked == [month] and sorted(found) == [date(2025, 1, 1), date(2025, 1, 3)]
    assert found[date(2025, 1, 1)] == openaq.Listed(
        DAY, "734fa8766d4c446a95ca874b4047042d", 685, datetime(2025, 1, 4, 23, 0, 40, tzinfo=UTC)
    )
    answers[month] = LISTING.format(cut="true", items=items).encode()
    with pytest.raises(ValueError, match="cut short"):
        openaq.find("3019", date(2025, 1, 15))


def test_one_command_downloads_a_day_to_its_key(archive, tmp_path, capsys):
    asked, answers = archive
    answers[f"{openaq.ARCHIVE}/{DAY}"] = b"a day file"
    assert openaq.main(["--station", "3019", "--date", "2025-01-01", "--to", str(tmp_path)]) == 0
    assert (tmp_path / DAY).read_bytes() == b"a day file"
    assert f"10 bytes, MD5 {hashlib.md5(b'a day file').hexdigest()}" in capsys.readouterr().out


def test_a_day_with_no_file_is_said_and_nothing_is_written(archive, tmp_path, capsys):
    assert openaq.download("3019", date(2025, 1, 2)) is None
    assert openaq.main(["--station", "3019", "--date", "2025-01-02", "--to", str(tmp_path)]) == 1
    assert "3019 2025-01-02: the archive has no file" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "arguments", [[], ["--station", "3019"], ["--fixtures", "--date", "2025-01-01"]]
)
def test_the_command_needs_a_station_and_a_day_or_the_test_data_alone(arguments, archive):
    with pytest.raises(SystemExit):
        openaq.main(arguments)
    assert archive[0] == []


def test_the_test_data_is_two_januaries_of_berlin_s_three_monitors():
    wanted = openaq.fixture_days()
    assert len(wanted) == 186 and {station for station, _ in wanted} == {"3019", "4762", "4767"}
    assert {day.strftime("%Y-%m") for _, day in wanted} == {"2025-01", "2026-01"}
    files = [path for path in openaq.FIXTURES.rglob("*.gz") if path.is_file()]
    committed = {str(path.relative_to(openaq.FIXTURES)) for path in files}
    assert committed == {openaq.key(station, day) for station, day in wanted}


def test_the_test_data_is_the_archive_s_files_unchanged():
    _, rows = manifests.read("openaq")
    listed = {(row["station"], row["date"]): (row["md5"], int(row["bytes"])) for row in rows}
    for station, day in openaq.fixture_days():
        content = (openaq.FIXTURES / openaq.key(station, day)).read_bytes()
        assert (hashlib.md5(content).hexdigest(), len(content)) == listed[station, str(day)]


def test_the_test_data_reads_as_the_contract_says():
    contract, (manifest, _) = load("openaq"), manifests.read("openaq")
    pm25 = {
        station["id"]: next(s["id"] for s in station["sensors"] if s["parameter"] == "pm25")
        for station in manifest["stations"]
    }
    role, hours = contract.roles, 0
    for station, day in openaq.fixture_days():
        text = gzip.decompress((openaq.FIXTURES / openaq.key(station, day)).read_bytes()).decode()
        table = csv.DictReader(io.StringIO(text))
        rows = [row for row in table if row[role["parameter"]] == contract.parameters["pm25"].name]
        assert tuple(table.fieldnames) == contract.fields
        assert {row[role["station"]] for row in rows} == {station}, (station, day)
        assert {row[role["sensor"]] for row in rows} == {pm25[station]}, (station, day)
        assert {row[role["unit"]] for row in rows} <= set(contract.parameters["pm25"].units)
        hours += len(rows)
    assert hours > 0.9 * 186 * 24


def test_the_licence_of_the_test_data_is_noted_and_allows_passing_it_on():
    manifest, _ = manifests.read("openaq")
    note = (openaq.FIXTURES / "README.md").read_text(encoding="utf-8")
    assert manifest["licence"]["permissions"]["redistribution"] is True
    assert manifest["licence"]["name"] in note and manifest["licence"]["credit"] in note
