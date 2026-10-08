"""Task 1.7: the OpenAQ adapter. It finds and downloads the archive's day files of a station.

    uv run python -m airquality.openaq --station 3019 --date 2025-01-01    downloads one day
    uv run python -m airquality.openaq --fixtures                          rewrites the test data

The archive holds one file per station and local day, and is read without credentials. A day
is written under `--to`, by default the current folder, at the key it has in the archive. The
test data is January 2025 and January 2026 of the three Berlin monitors, in `tests/fixtures/`.
"""

import argparse
import calendar
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from airquality import manifests
from airquality.checks.city_candidates import fetch  # waits between requests; nothing for a 404
from airquality.checks.openaq_file import ARCHIVE, S3

FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures" / "openaq"
NAME = re.compile(r"location-(?P<station>\d+)-(?P<day>\d{8})\.csv\.gz")
WINDOW = (date(2025, 1, 1), date(2026, 1, 1))  # the months of the test data, by their first day


@dataclass(frozen=True)
class Listed:
    """One file as the archive lists it."""

    key: str
    md5: str  # S3's ETag, which for these files is the MD5 of the content
    size: int
    written: datetime  # when the archive last wrote it; a file can be patched later


def key(station: str, day: date) -> str:
    """Where the archive keeps the file of a station and day."""
    folder = f"records/csv.gz/locationid={station}/year={day.year}/month={day.month:02d}"
    return f"{folder}/location-{station}-{day:%Y%m%d}.csv.gz"


def named(key: str) -> tuple[str, date]:
    """The station and the day that a file's key names. Raises ValueError for any other key."""
    name = NAME.fullmatch(key.rsplit("/", 1)[-1])
    if not name:
        raise ValueError(f"not the key of an OpenAQ day file: {key!r}")
    return name["station"], datetime.strptime(name["day"], "%Y%m%d").date()


def days(month: date) -> list[date]:
    """Every day of the month that `month` lies in."""
    return [
        month.replace(day=n) for n in range(1, calendar.monthrange(month.year, month.month)[1] + 1)
    ]


def find(station: str, month: date) -> dict[date, Listed]:
    """The days of a month for which the archive holds a file of the station."""
    prefix = key(station, month).rsplit("/", 1)[0] + "/"
    listing = ET.fromstring(fetch(f"{ARCHIVE}/?list-type=2&prefix={prefix}"))
    if listing.findtext(f"{S3}IsTruncated") != "false":
        raise ValueError(f"the archive's list of {prefix} is cut short: it has more than one page")
    listed = {
        item.findtext(f"{S3}Key"): Listed(
            key=item.findtext(f"{S3}Key"),
            md5=item.findtext(f"{S3}ETag").strip('"'),
            size=int(item.findtext(f"{S3}Size")),
            written=datetime.fromisoformat(item.findtext(f"{S3}LastModified")),
        )
        for item in listing.iter(f"{S3}Contents")
    }
    return {day: listed[key(station, day)] for day in days(month) if key(station, day) in listed}


def download(station: str, day: date) -> bytes | None:
    """The file of a station and day as the archive has it, or nothing if it has none."""
    return fetch(f"{ARCHIVE}/{key(station, day)}") or None


def save(station: str, day: date, folder: Path) -> Path | None:
    """Download one day into `folder`, at its key. Returns where it is, or nothing if no file."""
    content = download(station, day)
    if content is None:
        return None
    path = folder / key(station, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def fixture_days() -> list[tuple[str, date]]:
    """The test data: each Berlin monitor of the manifest, on each day of the window."""
    manifest, _ = manifests.read("openaq")
    berlin = sorted(
        station["id"] for station in manifest["stations"] if station["city"] == "Berlin"
    )
    return [(station, day) for station in berlin for month in WINDOW for day in days(month)]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", help="the OpenAQ location id, like 3019")
    parser.add_argument("--date", type=date.fromisoformat, help="the station's local day")
    parser.add_argument("--to", type=Path, default=Path("."), help="the folder to write into")
    parser.add_argument("--fixtures", action="store_true", help="rewrite the test data")
    args = parser.parse_args(arguments)
    if args.fixtures == bool(args.station or args.date) or bool(args.station) != bool(args.date):
        parser.error("give --station and --date, or --fixtures alone")
    wanted = fixture_days() if args.fixtures else [(args.station, args.date)]
    missing = 0
    for station, day in wanted:
        path = save(station, day, FIXTURES if args.fixtures else args.to)
        if path is None:
            missing += 1
            print(f"{station} {day}: the archive has no file")
        else:
            content = path.read_bytes()
            print(f"{station} {day}: {len(content)} bytes, MD5 {hashlib.md5(content).hexdigest()}")
            print(f"  {path}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
