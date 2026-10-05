"""Task 0.5: read real Sensor.Community files and its licence links, and print what is found.

    uv run python -m airquality.checks.sensor_community [--date 2026-10-03]

Every finding is printed with the address it was read from. Where `plan.md` states an expectation
the finding is marked as matching it or not, and the exit code is 1 if one does not.
"""

import argparse
import csv
import gzip
import io
import json
import re
import statistics
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import sleep
from typing import NamedTuple

ARCHIVE = "https://archive.sensor.community"
SITE = "https://sensor.community/en/"
LIVE = "https://data.sensor.community/airrohr/v1/sensor/{}/"
DUST, CLIMATE = "sds011_sensor_151", "dht22_sensor_152"  # the two sensors of one box in Stuttgart
RANGES = {"temperature": (-60, 60), "humidity": (0, 100)}  # proposed in plan.md
SAMPLE = 20  # climate files read for the value ranges


class Fetched(NamedTuple):
    url: str
    body: bytes
    modified: str  # the Last-Modified header, which is always in GMT


@dataclass
class Finding:
    name: str
    found: str
    source: str
    expected: str | None = None  # None: plan.md states no expectation
    matches: bool | None = None


def folders(listing: str) -> tuple[list[str], dict[date, datetime]]:
    """Year folders, and each day folder with the time the listing says it was last modified."""
    days = re.findall(r'href="(\d{4}-\d\d-\d\d)/".*?(\d{4}-\d\d-\d\d \d\d:\d\d)', listing)
    modified = {date.fromisoformat(day): datetime.fromisoformat(when) for day, when in days}
    return re.findall(r'href="(\d{4})/"', listing), modified


def climate_files(listing: str) -> list[str]:
    return re.findall(r'href="([\d-]+_(?:dht22|bme280)_sensor_\d+\.csv)"', listing)


def rows(body: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(body.decode("utf-8")), delimiter=";"))


def numbers(table: list[dict[str, str]], column: str) -> list[float]:
    return [
        float(row[column]) for row in table if re.fullmatch(r"-?\d+(\.\d+)?", row[column] or "")
    ]


def spread(values: list[float], unit: str) -> str:
    middle = statistics.median(values)
    return f"median {middle:.1f}, least {min(values):.1f}, most {max(values):.1f} {unit}".strip()


def spacing(table: list[dict[str, str]]) -> str:
    stamps = sorted(datetime.fromisoformat(row["timestamp"]) for row in table)
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
    return spread(gaps, "seconds")


def licence_links(page: str) -> list[str]:
    """Links on the page whose label says licence, as 'label -> address'."""
    links = re.findall(r"<a href=[\"']?([^\"'\s>]+)[^>]*>([^<]*)</a>", page)
    return [f"{label.strip()} -> {url}" for url, label in links if "licen" in label.lower()]


def check(
    day: date,
    now: datetime,
    listing: str,
    dust: Fetched,
    climate: Fetched,
    sample: list[bytes],
    page: str,
    live_stamp: str,
) -> list[Finding]:
    """Every finding. `now` is in UTC, and `live_stamp` is the live API's newest reading time."""
    years, modified = folders(listing)
    dust_rows, climate_rows = rows(dust.body), rows(climate.body)
    stamps = [row["timestamp"] for row in dust_rows]
    places = [dust_rows[0]["location"], climate_rows[0]["location"]]
    swapped = sum(1 for row in dust_rows if float(row["P2"] or 0) > float(row["P1"] or 0))
    behind = (now.replace(tzinfo=None) - datetime.fromisoformat(live_stamp)).total_seconds() / 60
    day_end = {d: datetime(d.year, d.month, d.day) + timedelta(days=1) for d in modified}
    lags = [(modified[d] - day_end[d]).total_seconds() / 3600 for d in modified]
    licences = licence_links(page)
    findings = [
        Finding(
            "Year folders, and day folders at the top level",
            f"years {years[0]} to {years[-1]}; days {min(modified)} to {max(modified)}",
            ARCHIVE,
            "years to 2025; 2026 days at the top level",
            years[-1] == "2025" and {d.year for d in modified} == {2026},
        ),
        Finding("Dust file columns", ";".join(dust_rows[0]), dust.url),
        Finding("Climate file columns", ";".join(climate_rows[0]), climate.url),
        Finding(
            "Location id in the dust file and in the climate file",
            f"{places[0]} and {places[1]}",
            f"{dust.url} and {climate.url}",
            "the same: the location id joins the two sensors of a box",
            places[0] == places[1],
        ),
        Finding(
            "Dust rows where P2 is above P1",
            f"{swapped} of {len(dust_rows)}",
            dust.url,
            "none, if P2 is the finer fraction",
            swapped == 0,
        ),
        Finding(
            "Timestamps in the dust file",
            f"first {min(stamps)}, last {max(stamps)}, written without a UTC offset",
            dust.url,
            f"all on {day}",
            {stamp[:10] for stamp in stamps} == {str(day)},
        ),
        Finding(
            "Newest live reading of the dust sensor, minutes before now in UTC",
            f"{behind:.1f} (its timestamp is {live_stamp})",
            LIVE.format(DUST.rsplit("_", 1)[1]),
            "0 to 15, which holds only if the timestamps are UTC",
            0 <= behind <= 15,
        ),
        Finding("Time between readings, dust file", spacing(dust_rows), dust.url),
        Finding("Time between readings, climate file", spacing(climate_rows), climate.url),
        Finding(
            "Hours from the end of a UTC day until its folder was last modified, by the listing",
            f"{spread(lags, 'hours')}, over {len(lags)} days",
            ARCHIVE,
        ),
        Finding(
            f"Last-Modified of the two files of {day}, and its folder in the listing",
            f"{dust.modified}; {climate.modified}; folder {modified[day]}",
            f"{dust.url} and {climate.url}",
        ),
        Finding(
            "Licence links on the Sensor.Community site",
            "; ".join(licences) or "none",
            SITE,
            "a licence for the data is named",
            any("opendatacommons.org" in link for link in licences),
        ),
    ]
    source = f"{len(sample)} dht22 and bme280 files of {day}, spread over the folder"
    headers = sorted({body.split(b"\n")[0].decode().strip() for body in sample})
    findings.append(
        Finding("Column sets among the sampled climate files", " | ".join(headers), source)
    )
    for column, (low, high) in RANGES.items():
        values = [value for body in sample for value in numbers(rows(body), column)]
        out = sum(1 for value in values if not low <= value <= high)
        found = f"{out} of {len(values)} readings outside; {spread(values, '')}"
        name = f"{column} against the proposed {low} to {high}"
        findings.append(Finding(name, found, source, "no reading outside", out == 0))
    return findings


def fetch(url: str) -> Fetched:
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return Fetched(url, body, response.headers.get("Last-Modified", "not given"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat, help="default: the newest day folder")
    args = parser.parse_args()
    listing = fetch(ARCHIVE + "/").body.decode()
    years, modified = folders(listing)
    day = args.date or max(modified)
    # Days of the years that have a folder sit inside it; later days sit at the top level.
    folder = f"{ARCHIVE}/{day.year}/{day}/" if str(day.year) in years else f"{ARCHIVE}/{day}/"
    names = climate_files(fetch(folder).body.decode())
    sample = []
    for name in names[:: max(1, len(names) // SAMPLE)][:SAMPLE]:
        sample.append(fetch(folder + name).body)
        sleep(0.2)  # be polite to a volunteer-run server
    live = json.loads(fetch(LIVE.format(DUST.rsplit("_", 1)[1])).body)
    findings = check(
        day,
        datetime.now(UTC),
        listing,
        fetch(f"{folder}{day}_{DUST}.csv"),
        fetch(f"{folder}{day}_{CLIMATE}.csv"),
        sample,
        fetch(SITE).body.decode(),
        max(reading["timestamp"] for reading in live).replace(" ", "T"),
    )
    command = " ".join(["python -m airquality.checks.sensor_community", *sys.argv[1:]])
    print("Sensor.Community check (task 0.5)")
    print(f"Run at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC with: {command}")
    for finding in findings:
        status = {None: "note   ", True: "match  ", False: "DIFFERS"}[finding.matches]
        print(f"\n[{status}] {finding.name}")
        if finding.expected is not None:
            print(f"    expected: {finding.expected}")
        print(f"    found:    {finding.found}\n    source:   {finding.source}")
    differing = sum(1 for finding in findings if finding.matches is False)
    print(f"\n{differing} findings differ from plan.md.")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
