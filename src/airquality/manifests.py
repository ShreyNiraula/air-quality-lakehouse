"""Tasks 0.8a and 0.8b: write the source manifests of the chosen stations, and validate them.

    uv run python -m airquality.manifests    rewrites manifests/generated/ from the live sources

A manifest says, for one source, which stations are used, what each sensor measures and in which
unit text, under which licence, and which files exist: `<source>.json`, with one line per file
and its MD5 in `<source>-files.csv`. OpenAQ needs a key in OPENAQ_API_KEY; it is never printed.
"""

import csv
import json
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from airquality.checks import openaq_file
from airquality.checks.city_candidates import fetch  # waits between requests

OUT = Path(__file__).parents[2] / "manifests" / "generated"
START = date(2025, 1, 1)  # the first day plan.md loads
SETTLED = timedelta(days=7)  # the OpenAQ archive holds a day's file by then (check 0.4)
# The owner's choice of 6 October 2026: each openSenseMap box, its city, and the OpenAQ monitor
# within 1 km of it (check 0.7).
PAIRS = {
    "5c2bca0e2c80100019218e6b": ("Berlin", "3019"),
    "5d78d78f953683001a412c1d": ("Berlin", "4762"),
    "5cd9440aff898b001a3ba6c0": ("Berlin", "4762"),
    "638e0a9185229d001bbc8cd3": ("Berlin", "4767"),
    "61edcc57f4d1e2001c57dc87": ("Wien", "2876226"),
    "620d4c8be00700001bf99c92": ("Wien", "4520"),
    "5c532a5135809500190b39cb": ("Wien", "4563"),
}
# The first three say whether a thing is allowed, the last two whether it is required.
PERMISSIONS = ("redistribution", "modification", "commercial_use", "attribution", "share_alike")
OPENAQ_NAMES = {
    "pm25": "pm25",
    "temperature": "temperature",
    "relativehumidity": "relative_humidity",
}
# Read by eye on 6 October 2026. The two names differ and the permissions agree; the owner kept
# the monitors on that basis.
LICENCES = {
    "openaq": {
        "name": "ODC-BY 1.0 in OpenAQ's record; CC-BY in the EEA's legal notice",
        "statements": [
            {"by": "OpenAQ", "url": "https://api.openaq.org/v3/licenses/10",
             "says": "ODC-BY: attribution required; commercial use, modification and "
                     "redistribution allowed; share-alike not required."},
            {"by": "EEA", "url": "https://www.eea.europa.eu/en/legal-notice",
             "says": "EEA materials are published under the CC-BY license [...] may be re-used "
                     "without prior permission, free of charge, for commercial or non-commercial "
                     "purposes, provided that the EEA is always acknowledged as the original "
                     "source of the material and that the original meaning or message of the "
                     "content is not distorted."},
        ],
        "permissions": dict(zip(PERMISSIONS, (True, True, True, True, False), strict=True)),
        "credit": "European Environment Agency (EEA), via OpenAQ",
    },
}  # fmt: skip


def days(first: date, last: date) -> list[str]:
    return [str(first + timedelta(days=n)) for n in range((last - first).days + 1)]


def spacing(stamps: list[str]) -> int:
    """The usual number of seconds between readings."""
    times = sorted(datetime.fromisoformat(stamp) for stamp in stamps)
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    return round(statistics.median(gaps)) if gaps else 0


def openaq(key: str, last: date) -> tuple[dict, list[dict]]:
    """The manifest of the reference monitors, and one row per day file from START to `last`."""
    api, archive, period = "https://api.openaq.org/v3", openaq_file.ARCHIVE, days(START, last)
    stations, rows = [], []
    for monitor in sorted({monitor for _, monitor in PAIRS.values()}, key=int):
        place = json.loads(fetch(f"{api}/locations/{monitor}", key))["results"][0]
        licence = f"{api}/licenses/{place['licenses'][0]['id']}"
        stated = json.loads(fetch(licence, key))["results"][0]
        files = {}
        for month in sorted({day[:7] for day in period}):
            prefix = openaq_file.month_prefix(int(monitor), date.fromisoformat(month + "-01"))
            listing = ET.fromstring(fetch(f"{archive}/?list-type=2&prefix={prefix}"))
            for item in listing.iter(f"{openaq_file.S3}Contents"):
                stamp = item.findtext(f"{openaq_file.S3}Key").rsplit("-", 1)[1][:8]
                md5 = item.findtext(f"{openaq_file.S3}ETag").strip('"')  # S3's ETag: the file's MD5
                day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
                files[day] = (md5, item.findtext(f"{openaq_file.S3}Size"))
        have = [day for day in period if day in files]
        rows += [{"station": monitor, "series": "location", "date": day, "md5": files[day][0],
                  "bytes": files[day][1]} for day in have]  # fmt: skip
        folder = openaq_file.month_prefix(int(monitor), date.fromisoformat(have[0]))
        name = f"location-{monitor}-{have[0].replace('-', '')}.csv.gz"
        _, table = openaq_file.parse_day_file(fetch(f"{archive}/{folder}{name}"))
        sensors = {row["sensors_id"]: row for row in table}  # as the first day file names them
        stations.append({
            "id": monitor, "name": place["name"],
            "city": next(city for city, near in PAIRS.values() if near == monitor),
            "timezone": place["timezone"],
            "latitude": place["coordinates"]["latitude"],
            "longitude": place["coordinates"]["longitude"],
            "provider": place["provider"]["name"],
            "licence_in_source_record": {"name": stated["name"], "url": licence} | {
                "redistribution": stated["redistributionAllowed"],
                "modification": stated["modificationAllowed"],
                "commercial_use": stated["commercialUseAllowed"],
                "attribution": stated["attributionRequired"],
                "share_alike": stated["shareAlikeRequired"],
            },
            "sensors": [{"id": id, "parameter": OPENAQ_NAMES.get(row["parameter"]),
                         "name_as_found": row["parameter"], "unit_as_found": row["units"]}
                        for id, row in sorted(sensors.items())],
            "seconds_between_rows": spacing(
                [row["datetime"] for row in table if row["parameter"] == "pm25"]
            ),
            "first_reading": place["datetimeFirst"]["utc"],
            "dates_with_no_file": {"location": [day for day in period if day not in files]},
        })  # fmt: skip
    return manifest("openaq", last, stations), rows


def manifest(source: str, last: date, stations: list[dict]) -> dict:
    span = {"from": str(START), "to": str(last), "list": f"{source}-files.csv", "hash": "md5"}
    return {
        "source": source,
        "written": f"{datetime.now(UTC):%Y-%m-%d}",
        "files": span,
        "licence": LICENCES[source],
        "stations": stations,
    }


def validate(manifest: dict, rows: list[dict]) -> list[str]:
    """Everything that is wrong with a manifest and its file list; nothing if it is sound."""
    problems = []
    licence, span = manifest["licence"], manifest["files"]
    allowed = licence.get("permissions", {})
    if sorted(allowed) != sorted(PERMISSIONS) or {type(v) for v in allowed.values()} != {bool}:
        problems.append("licence: the five permissions must each be true or false")
    if not (licence.get("name") and licence.get("credit")):
        problems.append("licence: the name or the credit line is missing")
    statements = licence.get("statements", [])
    if not statements or not all(s.get("url") and s.get("says") for s in statements):
        problems.append("licence: every statement needs its text and its address")
    period = set(days(date.fromisoformat(span["from"]), date.fromisoformat(span["to"])))
    listed: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{32}", row["md5"]) or row["date"] not in period:
            problems.append(f"file list: {row['station']} {row['date']} has a bad hash or date")
        listed.setdefault((row["station"], row["series"]), set()).add(row["date"])
    if sum(len(dates) for dates in listed.values()) != len(rows):
        problems.append("file list: a file is listed twice")
    ids = [station["id"] for station in manifest["stations"]]
    if len(set(ids)) != len(ids) or {station for station, _ in listed} - set(ids):
        problems.append("stations: an id appears twice, or the file list names an unknown one")
    for station in manifest["stations"]:
        where = f"station {station['id']}"
        try:
            ZoneInfo(station["timezone"])
        except (KeyError, ValueError):
            problems.append(f"{where}: unknown timezone")
        kinds = [sensor["parameter"] for sensor in station["sensors"] if sensor["parameter"]]
        if kinds.count("pm25") != 1 or len(set(kinds)) != len(kinds):
            problems.append(f"{where}: needs exactly one PM2.5 sensor, and no parameter twice")
        if not all(sensor["unit_as_found"] for sensor in station["sensors"] if sensor["parameter"]):
            problems.append(f"{where}: a sensor has no unit text")
        stated = station.get("licence_in_source_record")
        if stated and {key: stated.get(key) for key in PERMISSIONS} != allowed:
            problems.append(f"{where}: the source's own licence record disagrees with the manifest")
        for series, gaps in station["dates_with_no_file"].items():
            have = listed.get((station["id"], series), set())
            if have & set(gaps) or have | set(gaps) != period:
                problems.append(f"{where}: {series} needs a file or a gap for every date, not both")
    return problems


def read(source: str) -> tuple[dict, list[dict]]:
    """A committed manifest and its file list."""
    with open(OUT / f"{source}-files.csv", newline="") as table:
        return json.loads((OUT / f"{source}.json").read_text()), list(csv.DictReader(table))


def main() -> int:
    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        sys.exit("Set OPENAQ_API_KEY to your OpenAQ API key first. It is read, never printed.")
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    for built, rows in [openaq(key, datetime.now(UTC).date() - SETTLED)]:
        source = built["source"]
        (OUT / f"{source}.json").write_text(json.dumps(built, indent=2, ensure_ascii=False) + "\n")
        with open(OUT / f"{source}-files.csv", "w", newline="") as table:
            writer = csv.DictWriter(table, ["station", "series", "date", "md5", "bytes"])
            writer.writeheader()
            writer.writerows(rows)
        problems = validate(*read(source))
        gaps = sum(len(d) for s in built["stations"] for d in s["dates_with_no_file"].values())
        print(f"{source}: {len(built['stations'])} stations, {len(rows)} files, {gaps} gaps")
        print("".join(f"  PROBLEM {problem}\n" for problem in problems), end="")
        failed += len(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
