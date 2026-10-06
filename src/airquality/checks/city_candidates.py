"""Task 0.7: list cities where a reference monitor has low-cost sensors within about 1 km.

    uv run python -m airquality.checks.city_candidates [--radius 1.0]

Reference monitors come from the OpenAQ API, which needs a key in the environment variable
OPENAQ_API_KEY. Low-cost sensors are openSenseMap boxes. A monitor or a box counts only if it
has reported since before 1 January 2025 and within the last 30 days. For the cities with at
least three pairs, each source's archive is then asked whether it holds a file for the monitor
or the box on a few sample days. The key is never printed.
"""

import argparse
import itertools
import json
import math
import os
import re
import sys
import urllib.request
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from time import sleep
from typing import NamedTuple

from airquality.checks import openaq_file, opensensemap
from airquality.checks.opensensemap import BOX_FOLDER, folders, parameter

OPENAQ = "https://api.openaq.org/v3/locations?monitor=true&mobile=false&parameters_id=2&limit=1000"
BOXES = "https://api.opensensemap.org/boxes?exposure=outdoor&format=json"
START = date(2025, 1, 1)  # the first day plan.md loads
RECENT = timedelta(days=30)
CITY_KM = 20  # monitors closer than this to each other are listed as one city
RULE = 3  # plan.md: a city is used only if it has at least three pairs
SAMPLE_DAYS = [date(year, month, 1) for year in (2025, 2026) for month in (1, 4, 7, 10)]
SETTLED = timedelta(days=7)  # both archives hold a day's file by then (checks 0.4 and 0.5b)
WEATHER = {"temperature", "relativehumidity"}  # OpenAQ's names for the two


class Place(NamedTuple):
    id: str
    name: str
    lat: float
    lon: float
    city: str = ""  # monitors only: the locality OpenAQ gives, and the country code
    also: str = ""  # monitors only: which of temperature and humidity it measures


class Pair(NamedTuple):
    monitor: Place
    box: Place
    km: float


def km(a: Place, b: Place) -> float:
    """Great-circle distance between two places."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    half = math.sin((lat2 - lat1) / 2) ** 2
    half += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(half))


def reporting(first: str | None, last: str | None, now: datetime) -> bool:
    """True if the first report is before START and the last one within RECENT of `now`."""
    newest = str((now - RECENT).date())
    return bool(first and last) and first[:10] < str(START) and last[:10] >= newest


def monitors(locations: list[dict], now: datetime) -> list[Place]:
    """OpenAQ reference monitors that have reported throughout the period."""
    kept = []
    for place in locations:
        first, last = ((place.get(k) or {}).get("utc") for k in ("datetimeFirst", "datetimeLast"))
        spot = place.get("coordinates") or {}
        if reporting(first, last, now) and spot.get("latitude") is not None:
            measures = {sensor["parameter"]["name"] for sensor in place.get("sensors", [])}
            locality = (place.get("locality") or "").strip()  # some are blank or say "None"
            town = place["name"] if locality in ("", "None") else locality
            town = re.sub(r"^\d+\s+", "", town).title()  # some start with a postcode
            city = f"{town}, {(place.get('country') or {}).get('code')}"
            also = " and ".join(sorted(measures & WEATHER)) or "neither"
            point = (spot["latitude"], spot["longitude"])
            kept.append(Place(str(place["id"]), place["name"], *point, city, also))
    return kept


def boxes(listed: list[dict], now: datetime) -> list[Place]:
    """Outdoor openSenseMap boxes with a PM2.5 sensor that have reported throughout the period."""
    kept = []
    for box in listed:
        spot = (box.get("currentLocation") or {}).get("coordinates")
        pm25 = any(parameter(sensor) == "pm25" for sensor in box.get("sensors", []))
        running = reporting(box.get("createdAt"), box.get("lastMeasurementAt"), now)
        if spot and pm25 and running and box.get("exposure") == "outdoor":
            kept.append(Place(box["_id"], box.get("name") or "", spot[1], spot[0]))
    return kept


def pairs(reference: list[Place], low_cost: list[Place], radius: float) -> list[Pair]:
    """Every monitor and box that are within `radius` kilometres of each other."""
    by_lat = sorted(low_cost, key=lambda box: box.lat)
    lats = [box.lat for box in by_lat]
    margin = radius / 110  # a degree of latitude is a little over 110 km
    found = []
    for monitor in reference:
        low = bisect_left(lats, monitor.lat - margin)
        high = bisect_right(lats, monitor.lat + margin)
        near = [Pair(monitor, box, km(monitor, box)) for box in by_lat[low:high]]
        found += [pair for pair in near if pair.km <= radius]
    return found


def cities(found: list[Pair]) -> list[list[Pair]]:
    """Pairs grouped into cities: monitors within CITY_KM of one another share a city."""
    groups: list[list[Pair]] = []
    for pair in sorted(found, key=lambda pair: (pair.monitor.id, pair.box.id)):
        near = [g for g in groups if any(km(pair.monitor, other.monitor) <= CITY_KM for other in g)]
        merged = [pair] + [other for group in near for other in group]
        groups = [group for group in groups if group not in near] + [merged]
    return sorted(groups, key=lambda group: (-len(group), label(group)))


def label(group: list[Pair]) -> str:
    """The commonest locality among a city's pairs."""
    return Counter(pair.monitor.city for pair in group).most_common(1)[0][0]


def report(groups: list[list[Pair]], present: dict[str, int], days: int) -> list[str]:
    """One line per city, then every pair of the cities that have at least RULE pairs.

    `present` gives, by monitor id or box id, on how many of the `days` sample days its archive
    holds a file.
    """
    lines = ["pairs  boxes  monitors  temperature or humidity at a monitor  city"]
    for group in groups:
        n_boxes, n_monitors = len({p.box.id for p in group}), len({p.monitor.id for p in group})
        weather = "; ".join(sorted({p.monitor.also for p in group} - {"neither"})) or "neither"
        lines.append(f"{len(group):5}  {n_boxes:5}  {n_monitors:8}  {weather:36}  {label(group)}")
    for group in (group for group in groups if len(group) >= RULE):
        lines += ["", f"{label(group)}: {len(group)} pairs"]
        for p in sorted(group, key=lambda p: (p.monitor.id, p.km)):
            seen = [
                f"a file on {present.get(place.id, 0)} of {days} sample days" for place in p[:2]
            ]
            lines += [
                f"  {p.km:.2f} km  monitor {p.monitor.id} {p.monitor.name}: {seen[0]};"
                f" also measures {p.monitor.also}",
                f"           box {p.box.id} {p.box.name}: {seen[1]}",
            ]
    return lines


def fetch(url: str, key: str | None = None) -> str:
    sleep(1.1 if key else 0.1)  # OpenAQ allows 60 requests a minute
    headers = {"User-Agent": "airquality-check"} | ({"X-API-Key": key} if key else {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as r:
        return r.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--radius", type=float, default=1.0, help="kilometres; plan.md says 1")
    args = parser.parse_args()
    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        sys.exit("Set OPENAQ_API_KEY to your OpenAQ API key first. It is read, never printed.")
    now = datetime.now(UTC)
    locations = []
    for page in itertools.count(1):
        results = json.loads(fetch(f"{OPENAQ}&page={page}", key))["results"]
        locations += results
        if len(results) < 1000:
            break
    reference, low_cost = monitors(locations, now), boxes(json.loads(fetch(BOXES)), now)
    groups = cities(pairs(reference, low_cost, args.radius))
    wanted = [p for group in groups if len(group) >= RULE for p in group]
    archived = folders(fetch(opensensemap.ARCHIVE + "/"))
    days = [d for d in SAMPLE_DAYS if d in archived and d <= (now - SETTLED).date()]
    listings = [
        "".join(BOX_FOLDER.findall(fetch(f"{opensensemap.ARCHIVE}/{day}/"))) for day in days
    ]
    present = {p.box.id: sum(p.box.id in listing for listing in listings) for p in wanted}
    for monitor in {p.monitor.id for p in wanted}:
        months = [openaq_file.month_prefix(int(monitor), day) for day in days]
        listed = [fetch(f"{openaq_file.ARCHIVE}/?list-type=2&prefix={month}") for month in months]
        files = [openaq_file.parse_listing(listing) for listing in listed]
        present[monitor] = sum(day in found for day, found in zip(days, files, strict=True))
    command = " ".join(["python -m airquality.checks.city_candidates", *sys.argv[1:]])
    print("City candidates (task 0.7)")
    print(f"Run at {now:%Y-%m-%d %H:%M} UTC with: {command}")
    print(f"{len(reference)} reference monitors and {len(low_cost)} boxes have reported since")
    print(f"before {START} and in the last {RECENT.days} days. Pairs are within {args.radius} km.")
    print(f"Sample days: {', '.join(map(str, days))}\n")
    print("\n".join(report(groups, present, len(days))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
