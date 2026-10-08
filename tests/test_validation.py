"""File validation: real files and a short day pass, and each kind of broken file is refused."""

import gzip
from datetime import date

import pytest

from airquality import openaq
from airquality.contracts import load
from airquality.validation import validate

OPENAQ = load("openaq")
STATION, DAY = "3019", date(2025, 1, 1)
REAL = (openaq.FIXTURES / openaq.key(STATION, DAY)).read_bytes()
LINES = gzip.decompress(REAL).decode("utf-8").splitlines()  # the header, then 72 rows
PM25 = [line for line in LINES if '"pm25"' in line]


def packed(lines: list[str]) -> bytes:
    return gzip.compress("\n".join(lines).encode("utf-8") + b"\n")


def check(content: bytes) -> list[str]:
    return validate(content, STATION, DAY, OPENAQ)


def test_every_real_file_of_the_test_data_is_valid():
    for station, day in openaq.fixture_days():
        content = (openaq.FIXTURES / openaq.key(station, day)).read_bytes()
        assert validate(content, station, day, OPENAQ) == [], (station, day)


def test_a_short_day_is_valid():
    assert len(PM25) == 24
    assert check(packed([LINES[0], *PM25[:6]])) == []
    assert check(packed([LINES[0], LINES[1]])) == []


def test_a_reading_out_of_range_is_valid_because_values_are_not_judged():
    assert '"26.81"' in PM25[0]
    for value in ("99999", "-5", "not a number", ""):
        assert check(packed([LINES[0], PM25[0].replace('"26.81"', f'"{value}"')])) == []


def test_the_unit_of_a_parameter_the_contract_does_not_read_is_not_checked():
    other = next(line for line in LINES if '"no2"' in line)
    assert check(packed([LINES[0], other.replace("µg/m³", "ppm")])) == []


def changed(old: str, new: str, rows: list[str] = LINES[1:]) -> bytes:
    """The real header, and `rows` with one text put in place of another."""
    assert any(old in row for row in rows)
    return packed([LINES[0], *(row.replace(old, new) for row in rows)])


@pytest.mark.parametrize(
    ("content", "reasons"),
    [
        (b"not a gzip file", ["the file does not open: Not a gzipped file (b'no')"]),
        (REAL[:200], ["the file does not open: Compressed file ended before"]),
        (gzip.compress(b"\xff\xfe\x00"), ["the file does not open: 'utf-8' codec can't decode"]),
        (gzip.compress(b""), ["the file is empty"]),
        (packed(LINES[:1]), ["the file has a header and no rows"]),
        (packed(LINES[1:]), ["the header is 3019,6422,Berlin Mitte-3019,"]),
        (packed([LINES[0].replace("units", "unit"), *LINES[1:]]), ["the header is location_id,"]),
        (packed([",".join(reversed(LINES[0].split(","))), *LINES[1:]]), ["the header is value,"]),
        (
            packed([*LINES[:3], LINES[3].rsplit(",", 2)[0], *LINES[4:]]),
            ["the wrong number of fields in 1 of 72 rows: row 3 has 7 fields"],
        ),
        (
            changed("3019,", "4762,"),
            ["another station in 72 of 72 rows: row 1 is of 4762, not 3019"],
        ),
        (
            changed("2025-01-01T", "2025-01-02T", PM25[:3]),
            ["another day in 3 of 3 rows: row 1 is of 2025-01-02, not 2025-01-01"],
        ),
        (
            changed("2025-01-01T01:00:00+01:00", "1 January, one o'clock"),
            ['a time that cannot be read in 3 of 72 rows: row 1 has "1 January, one o\'clock"'],
        ),
        (
            changed("+01:00", "", PM25[:2]),
            ["a time with no UTC offset in 2 of 2 rows: row 1 has 2025-01-01T01:00:00"],
        ),
        (
            changed("µg/m³", "mg/m³", PM25),
            ["a unit that does not pass in 24 of 24 rows: row 1 has pm25 in 'mg/m³'"],
        ),
        (
            changed("3019,", "4762,", [PM25[0].replace("µg/m³", "ppm"), PM25[1]]),
            [
                "another station in 2 of 2 rows: row 1 is of 4762, not 3019",
                "a unit that does not pass in 1 of 2 rows: row 1 has pm25 in 'ppm'",
            ],
        ),
    ],
    ids=[
        "not gzip",
        "cut short",
        "not text",
        "empty",
        "no rows",
        "no header",
        "a field renamed",
        "fields in another order",
        "a row with fields missing",
        "another station",
        "another day",
        "a time that is not one",
        "a time with no offset",
        "another unit",
        "two faults at once",
    ],
)
def test_each_kind_of_broken_file_is_refused_with_its_reason(content, reasons):
    found = check(content)
    assert len(found) == len(reasons)
    for said, expected in zip(found, reasons, strict=True):
        assert said.startswith(expected), found


def test_a_real_file_under_another_name_is_refused():
    assert validate(REAL, STATION, date(2025, 1, 2), OPENAQ) == [
        "another day in 72 of 72 rows: row 1 is of 2025-01-01, not 2025-01-02"
    ]
    assert validate(REAL, "4762", DAY, OPENAQ)[0].startswith("another station in 72 of 72 rows")


def test_a_day_ends_with_the_hour_that_is_stamped_midnight():
    assert LINES[24].count("2025-01-02T00:00:00+01:00") == 1  # the hour from 23:00 to midnight
    assert check(packed([LINES[0], LINES[24]])) == []
    late = LINES[24].replace("2025-01-02T00:00:00", "2025-01-02T01:00:00")
    assert check(packed([LINES[0], late]))[0].startswith("another day in 1 of 1 rows")
