"""Task 0.4: compare a real OpenAQ archive day file with what `plan.md` expects.

    uv run python -m airquality.checks.openaq_file [--location 2178] [--date 2026-09-18]

The archive is read over HTTPS without credentials. Each finding is printed next to the expected
value. The exit code is 1 if a finding differs from its expectation.
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

ARCHIVE = "https://openaq-data-archive.s3.amazonaws.com"
S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
EXPECTED_FIELDS = "location_id,sensors_id,location,datetime,lat,lon,parameter,units,value"
EXPECTED_PM25_UNIT = "µg/m³"  # micro sign and superscript three, as OpenAQ documents it
NORMALIZED_PM25_UNIT = "μg/m3"  # Greek mu and a plain 3: what the unit rule compares
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
    """The day each listed file is for, and when the archive last wrote it."""
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


def lag_hours(files: dict[date, datetime], offset: timedelta) -> list[float]:
    """Hours from the end of each file's local day to when the archive wrote it."""
    day_ends = {
        day: datetime.combine(day, time(), UTC) + timedelta(days=1) - offset for day in files
    }
    return [(files[day] - day_ends[day]).total_seconds() / 3600 for day in files]


def code_points(text: str) -> str:
    return f"{text} ({' '.join(f'U+{ord(char):04X}' for char in text)})"


def check(day: date, raw: bytes, files: dict[date, datetime], now: datetime) -> list[Finding]:
    """Every finding for one day file and the listing it came from."""
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
    gap = gaps.most_common(1)[0][0] if gaps else None
    offset = stamps[0].utcoffset()
    labels = hour_labels(day, stamps)
    lags = lag_hours(files, offset)
    lag = statistics.median(lags)
    newest = max(files)
    # A day is due once the usual lag has passed since its local end.
    last_due = (now.astimezone(UTC) - timedelta(hours=lag) + offset).date() - timedelta(days=1)
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
            "PM2.5 unit after NFKC, as the unit rule compares it",
            code_points(NORMALIZED_PM25_UNIT),
            code_points(unicodedata.normalize("NFKC", unit)),
            unicodedata.normalize("NFKC", unit) == NORMALIZED_PM25_UNIT,
        ),
        Finding(
            "Sensors in the file: parameter, unit, sensor id, rows",
            None,
            "; ".join(f"{p} {u} {s} {n}" for (p, u, s), n in sorted(sensors.items())),
        ),
        Finding(
            "Timestamps name each hour by its",
            "end",
            f"{labels} (first {min(stamps).isoformat()}, last {max(stamps).isoformat()})",
            labels == "end",
        ),
        Finding(
            "Usual time between rows of one sensor", "1:00:00", str(gap), gap == timedelta(hours=1)
        ),
        Finding(
            "Hours from the end of the local day until the file is written",
            f"{low} to {high}",
            f"{spread}, over {len(files)} files",
            low <= lag <= high,
        ),
        Finding(
            "Newest day with a file",
            None,
            f"{newest}, written {files[newest].isoformat()}; "
            f"{overdue} later days are due by that lag and have no file",
        ),
    ]


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{ARCHIVE}/{path}", timeout=60) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--location", type=int, default=2178)
    parser.add_argument(
        "--date", type=date.fromisoformat, help="default: the newest day with a file"
    )
    args = parser.parse_args()
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
    downloaded = Finding("Download without credentials", "works", f"works, {len(raw)} bytes", True)
    findings = [downloaded, *check(day, raw, files, now)]
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
