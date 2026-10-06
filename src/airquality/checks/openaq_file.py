"""Task 0.4: compare a real OpenAQ archive day file with what `plan.md` expects.

    uv run python -m airquality.checks.openaq_file [--date 2026-09-18]
    uv run python -m airquality.checks.openaq_file --location <id> --timezone <IANA name>

The archive is read over HTTPS without credentials. Each finding is printed next to the expected
value. The exit code is 1 if a finding differs from its expectation. The station's timezone is
given, not looked up: the OpenAQ API that holds it needs a key.
"""

import argparse
import csv
import gzip
import io
import statistics
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ARCHIVE = "https://openaq-data-archive.s3.amazonaws.com"
S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
EXPECTED_FIELDS = "location_id,sensors_id,location,datetime,lat,lon,parameter,units,value"
EXPECTED_PM25_UNIT = "µg/m³"  # micro sign and superscript three, as OpenAQ documents it
NORMALIZED_PM25_UNIT = "μg/m3"  # Greek mu and a plain 3: what the unit rule compares
DEFAULT_LOCATION, DEFAULT_TIMEZONE = 2178, "America/Denver"  # Del Norte, Albuquerque
EXPECTED_LAG_HOURS = (72, 96)  # documented: 72 h after the day ends; seen: four days after the day


@dataclass
class Finding:
    name: str
    expected: str | None  # None: plan.md states no expectation, the finding is for the record
    found: str
    matches: bool | None = None


def month_prefix(location: int, month: date) -> str:
    return f"records/csv.gz/locationid={location}/year={month.year}/month={month.month:02d}/"


def parse_listing(xml_text: str) -> dict[date, datetime]:
    """The day each listed file is for, and when the archive last wrote it, patches included."""
    files = {}
    for item in ET.fromstring(xml_text).iter(f"{S3}Contents"):
        stamp = item.findtext(f"{S3}Key").rsplit("-", 1)[1].removesuffix(".csv.gz")
        written = datetime.fromisoformat(item.findtext(f"{S3}LastModified"))
        files[datetime.strptime(stamp, "%Y%m%d").date()] = written
    return files


def parse_day_file(raw: bytes) -> tuple[str, list[dict[str, str]]]:
    """The header line as written, and the rows."""
    text = gzip.decompress(raw).decode("utf-8")
    return text.splitlines()[0], list(csv.DictReader(io.StringIO(text)))


def hour_labels(day: date, stamps: list[datetime]) -> str:
    """Whether a day file's timestamps name each hour by its end or by its start."""
    local = [stamp.replace(tzinfo=None) for stamp in stamps]
    start = datetime.combine(day, time())
    end = start + timedelta(days=1)
    if all(start < stamp <= end for stamp in local) and end in local:
        return "end"
    if all(start <= stamp < end for stamp in local) and start in local:
        return "start"
    return "unclear"


def lag_hours(files: dict[date, datetime], zone: ZoneInfo) -> list[float]:
    """Hours from the end of each file's local day to when the archive wrote it."""
    day_ends = {day: datetime.combine(day + timedelta(days=1), time(), zone) for day in files}
    return [(files[day] - day_ends[day]).total_seconds() / 3600 for day in files]


def in_station_time(stamps: list[datetime], zone: ZoneInfo) -> bool:
    """Whether each timestamp carries the offset the station's timezone has at that instant."""
    return all(stamp.utcoffset() == stamp.astimezone(zone).utcoffset() for stamp in stamps)


def offsets(stamps: list[datetime]) -> str:
    return ", ".join(sorted({stamp.isoformat()[-6:] for stamp in stamps}))


def code_points(text: str) -> str:
    return f"{text} ({' '.join(f'U+{ord(char):04X}' for char in text)})"


def check(
    day: date, raw: bytes, files: dict[date, datetime], now: datetime, zone: ZoneInfo
) -> list[Finding]:
    """Every finding for one day file and the listing it came from, for a station in `zone`."""
    header, rows = parse_day_file(raw)
    fields = ",".join(next(csv.reader([header])))
    start = [
        Finding("Field names", EXPECTED_FIELDS, fields, fields == EXPECTED_FIELDS),
        Finding("Header line as written", None, header),
        Finding("Rows in the file", "at least 1", str(len(rows)), len(rows) > 0),
    ]
    if fields != EXPECTED_FIELDS or not rows:
        return start  # everything below reads rows by these field names
    pm25 = [row for row in rows if row["parameter"] == "pm25"]
    unit = ", ".join(sorted({row["units"] for row in pm25})) or "no pm25 rows"
    sensors = Counter((row["parameter"], row["units"], row["sensors_id"]) for row in rows)
    by_sensor: dict[str, list[datetime]] = {}
    for row in rows:
        by_sensor.setdefault(row["sensors_id"], []).append(datetime.fromisoformat(row["datetime"]))
    stamps = [stamp for series in by_sensor.values() for stamp in series]
    gaps = Counter(
        later - earlier
        for series in by_sensor.values()
        for earlier, later in zip(sorted(series), sorted(series)[1:], strict=False)
    )
    hour = timedelta(hours=1)
    hourly = min(gaps) == hour and not any(gap % hour for gap in gaps) if gaps else None
    spacing = ", ".join(f"{gap} x{n}" for gap, n in sorted(gaps.items())) or "one row per sensor"
    in_zone = [stamp.astimezone(zone) for stamp in stamps]
    labels = hour_labels(day, stamps)
    lags = lag_hours(files, zone)
    lag = statistics.median(lags)
    newest = max(files)
    # A day is due once the usual lag has passed since its local end.
    last_due = (now - timedelta(hours=lag)).astimezone(zone).date() - timedelta(days=1)
    overdue = max(0, (last_due - newest).days)
    spread = f"median {lag:.1f}, least {min(lags):.1f}, most {max(lags):.1f}"
    low, high = EXPECTED_LAG_HOURS
    return [
        *start,
        Finding(
            "PM2.5 unit text",
            code_points(EXPECTED_PM25_UNIT),
            code_points(unit),
            unit == EXPECTED_PM25_UNIT,
        ),
        Finding(
            "PM2.5 unit after strip and NFKC, as the unit rule compares it",
            code_points(NORMALIZED_PM25_UNIT),
            code_points(unicodedata.normalize("NFKC", unit.strip())),
            unicodedata.normalize("NFKC", unit.strip()) == NORMALIZED_PM25_UNIT,
        ),
        Finding(
            "Sensors in the file: parameter, unit, sensor id, rows",
            None,
            "; ".join(f"{p} {u} {s} {n}" for (p, u, s), n in sorted(sensors.items())),
        ),
        Finding(
            f"UTC offset of the timestamps, against {zone.key} at those times",
            offsets(in_zone),
            offsets(stamps),
            in_station_time(stamps, zone),
        ),
        Finding(
            "Timestamps name each hour by its",
            "end",
            f"{labels} (first {min(stamps).isoformat()}, last {max(stamps).isoformat()})",
            labels == "end",
        ),
        Finding("Times between rows of one sensor", "whole hours from 1:00:00", spacing, hourly),
        Finding(
            "Hours from the end of the local day until the file was last written",
            f"{low} to {high}",
            f"{spread}, over {len(files)} files",
            low <= lag <= high,
        ),
        Finding(
            "Newest day with a file",
            None,
            f"{newest}, last written {files[newest].isoformat()}; "
            f"{overdue} later days are due by that lag and have no file",
        ),
    ]


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{ARCHIVE}/{path}", timeout=60) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--location", type=int, default=DEFAULT_LOCATION)
    parser.add_argument("--timezone", help="the station's IANA timezone")
    parser.add_argument(
        "--date", type=date.fromisoformat, help="default: the newest day with a file"
    )
    args = parser.parse_args()
    if args.timezone is None and args.location != DEFAULT_LOCATION:
        parser.error("--timezone is needed for a location other than the default")
    zone = ZoneInfo(args.timezone or DEFAULT_TIMEZONE)
    now = datetime.now(UTC)

    files: dict[date, datetime] = {}
    month = now.date().replace(day=1)
    for _ in range(3):  # this month and the two before it
        files |= parse_listing(
            fetch(f"?list-type=2&prefix={month_prefix(args.location, month)}").decode()
        )
        month = (month - timedelta(days=1)).replace(day=1)
    if not files:
        sys.exit(f"No files for location {args.location} in the last three months.")
    day = args.date or max(files)
    path = f"{month_prefix(args.location, day)}location-{args.location}-{day:%Y%m%d}.csv.gz"
    raw = fetch(path)

    print("OpenAQ archive day file check (task 0.4)")
    command = " ".join(["python -m airquality.checks.openaq_file", *sys.argv[1:]])
    print(f"Run at {now:%Y-%m-%d %H:%M} UTC with: {command}")
    print(f"File: {ARCHIVE}/{path}")
    print(f"Station timezone, as given: {zone.key}")
    downloaded = Finding("Download without credentials", "works", f"works, {len(raw)} bytes", True)
    findings = [downloaded, *check(day, raw, files, now, zone)]
    for finding in findings:
        status = {None: "note   ", True: "match  ", False: "DIFFERS"}[finding.matches]
        print(f"\n[{status}] {finding.name}")
        if finding.expected is not None:
            print(f"    expected: {finding.expected}")
        print(f"    found:    {finding.found}")
    differing = [finding for finding in findings if finding.matches is False]
    print(f"\n{len(differing)} findings differ from plan.md.")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
