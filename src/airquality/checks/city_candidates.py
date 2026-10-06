"""Task 0.7: list cities where a reference monitor has low-cost sensors within about 1 km.

    uv run python -m airquality.checks.city_candidates [--radius 1.0]

Reference monitors come from the OpenAQ API, which needs a key in the environment variable
OPENAQ_API_KEY. Low-cost sensors are openSenseMap boxes. A pair counts only if both have reported
PM2.5 since 1 January 2025 or earlier and within the last 30 days. For the cities with at least
three pairs, each source's archive is then asked whether it holds PM2.5 readings of the monitor
or the box on a few sample days. The key is never printed.
"""

import argparse
import itertools
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from time import sleep
from typing import NamedTuple

from airquality.checks import openaq_file, opensensemap
from airquality.checks.opensensemap import BOX_FOLDER, folders, parameter

OPENAQ = "https://api.openaq.org/v3"
MONITORS = f"{OPENAQ}/locations?monitor=true&mobile=false&parameters_id=2&limit=1000"
BOXES = "https://api.opensensemap.org/boxes?exposure=outdoor&format=json&full=true"
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
    pm25: tuple[str, ...] = ()  # boxes only: the ids of its PM2.5 sensors


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


def reporting(record: dict, now: datetime) -> bool:
    """True if an OpenAQ record first reported on START or earlier and last within RECENT."""
    first, last = ((record.get(key) or {}).get("utc") for key in ("datetimeFirst", "datetimeLast"))
    return throughout(first, last, now)


def throughout(first: str | None, last: str | None, now: datetime) -> bool:
    newest = str((now - RECENT).date())
    return bool(first and last) and first[:10] <= str(START) and last[:10] >= newest


def monitors(locations: list[dict], now: datetime) -> list[Place]:
    """OpenAQ reference monitors that have reported throughout the period, by any sensor."""
    kept = []
    for place in locations:
        spot = place.get("coordinates") or {}
        if reporting(place, now) and spot.get("latitude") is not None:
            measures = {sensor["parameter"]["name"] for sensor in place.get("sensors", [])}
            locality = (place.get("locality") or "").strip()  # some are blank or say "None"
            town = place["name"] if locality in ("", "None") else locality
            town = re.sub(r"^\d+\s+", "", town).title()  # some start with a postcode
            city = f"{town}, {(place.get('country') or {}).get('code')}"
            also = " and ".join(sorted(measures & WEATHER)) or "neither"
            point = (spot["latitude"], spot["longitude"])
            kept.append(Place(str(place["id"]), place["name"], *point, city, also))
    return kept


def pm25_throughout(sensors: list[dict], now: datetime) -> bool:
    """True if one of a monitor's sensors is PM2.5 and has itself reported throughout."""
    return any(s["parameter"]["name"] == "pm25" and reporting(s, now) for s in sensors)


def boxes(listed: list[dict], now: datetime) -> list[Place]:
    """Outdoor openSenseMap boxes made on START or earlier whose PM2.5 sensor reported lately."""
    kept = []
    for box in listed:
        spot = (box.get("currentLocation") or {}).get("coordinates")
        pm25 = [sensor for sensor in box.get("sensors", []) if parameter(sensor) == "pm25"]
        read = [(sensor.get("lastMeasurement") or {}).get("createdAt") or "" for sensor in pm25]
        running = throughout(box.get("createdAt"), max(read, default=""), now)
        if spot and running and box.get("exposure") == "outdoor":
            ids = tuple(sensor["_id"] for sensor in pm25)
            kept.append(Place(box["_id"], box.get("name") or "", spot[1], spot[0], pm25=ids))
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
    """Pairs grouped into cities: no two monitors of a city are more than CITY_KM apart."""
    groups: list[list[Pair]] = []
    for pair in sorted(found, key=lambda pair: (pair.monitor.id, pair.box.id)):
        fits = (g for g in groups if all(km(pair.monitor, p.monitor) <= CITY_KM for p in g))
        if (home := next(fits, None)) is None:
            groups.append(home := [])
        home.append(pair)
    return sorted(groups, key=lambda group: (-len(group), label(group)))


def label(group: list[Pair]) -> str:
    """The commonest locality among a city's pairs."""
    return Counter(pair.monitor.city for pair in group).most_common(1)[0][0]


def report(groups: list[list[Pair]], present: dict[str, int], days: int) -> list[str]:
    """One line per city, then every pair of the cities that have at least RULE pairs.

    `present`: by monitor or box id, on how many of the `days` sample days it has PM2.5 readings.
    """
    lines = ["pairs  boxes  monitors  temperature or humidity at a monitor  city"]
    for group in groups:
        n_boxes, n_monitors = len({p.box.id for p in group}), len({p.monitor.id for p in group})
        weather = "; ".join(sorted({p.monitor.also for p in group} - {"neither"})) or "neither"
        lines.append(f"{len(group):5}  {n_boxes:5}  {n_monitors:8}  {weather:36}  {label(group)}")
    for group in (group for group in groups if len(group) >= RULE):
        lines += ["", f"{label(group)}: {len(group)} pairs"]
        for p in sorted(group, key=lambda p: (p.monitor.id, p.km)):
            seen = [f"PM2.5 on {present.get(place.id, 0)} of {days} sample days" for place in p[:2]]
            lines += [
                f"  {p.km:.2f} km  monitor {p.monitor.id} {p.monitor.name}: {seen[0]};"
                f" also measures {p.monitor.also}",
                f"           box {p.box.id} {p.box.name}: {seen[1]}",
            ]
    return lines


def fetch(url: str, key: str | None = None) -> bytes:
    """What the address returns, or nothing if it does not exist."""
    sleep(1.1 if key else 0.1)  # OpenAQ allows 60 requests a minute
    headers = {"User-Agent": "airquality-check"} | ({"X-API-Key": key} if key else {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        return b""


def sampled(place: Place, days: list[date], listings: list[list[str]]) -> int:
    """On how many of `days` the archive holds PM2.5 readings of a monitor or a box.

    `listings`: the box folders of each of the days in the openSenseMap archive.
    """
    count = 0
    for day, names in zip(days, listings, strict=True):
        if place.pm25:  # a box: its folder of the day holds a file of one of its PM2.5 sensors
            folder = next((name for name in names if name.startswith(place.id)), None)
            files = fetch(f"{opensensemap.ARCHIVE}/{day}/{folder}").decode() if folder else ""
            count += any(f'"./{sensor}-' in files for sensor in place.pm25)
        else:  # a monitor: its file of the day holds PM2.5 rows
            month = openaq_file.month_prefix(int(place.id), day)
            raw = fetch(f"{openaq_file.ARCHIVE}/{month}location-{place.id}-{day:%Y%m%d}.csv.gz")
            rows = openaq_file.parse_day_file(raw)[1] if raw else []
            count += any(row["parameter"] == "pm25" for row in rows)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--radius", type=float, default=1.0, help="kilometres; plan.md says 1")
    args = parser.parse_args()
    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        sys.exit("Set OPENAQ_API_KEY to your OpenAQ API key first. It is read, never printed.")
    now = datetime.now(UTC)
    locations: list[dict] = []
    for page in itertools.count(1):
        locations += json.loads(fetch(f"{MONITORS}&page={page}", key))["results"]
        if len(locations) < 1000 * page:
            break
    reference, low_cost = monitors(locations, now), boxes(json.loads(fetch(BOXES)), now)
    found = pairs(reference, low_cost, args.radius)
    sensors: dict[str, list[dict] | None] = {}
    for id in sorted({pair.monitor.id for pair in found}):
        try:
            sensors[id] = json.loads(fetch(f"{OPENAQ}/locations/{id}/sensors", key))["results"]
        except urllib.error.HTTPError:  # OpenAQ answers for a few monitors with a server error
            sensors[id] = None
    sure = {id for id, own in sensors.items() if own and pm25_throughout(own, now)}
    unread = [id for id, own in sensors.items() if own is None]
    groups = cities([pair for pair in found if pair.monitor.id in sure])
    archived = folders(fetch(opensensemap.ARCHIVE + "/").decode())
    days = [d for d in SAMPLE_DAYS if d in archived and d <= (now - SETTLED).date()]
    listings = [
        BOX_FOLDER.findall(fetch(f"{opensensemap.ARCHIVE}/{day}/").decode()) for day in days
    ]
    places = {q for group in groups if len(group) >= RULE for p in group for q in p[:2]}
    present = {place.id: sampled(place, days, listings) for place in places}
    command = " ".join(["python -m airquality.checks.city_candidates", *sys.argv[1:]])
    print("City candidates (task 0.7)")
    print(f"Run at {now:%Y-%m-%d %H:%M} UTC with: {command}")
    print(f"{len(reference)} reference monitors and {len(low_cost)} boxes reported on {START} or")
    print(f"earlier and in the last {RECENT.days} days. {len(sensors)} of the monitors have a box")
    print(f"within {args.radius} km, and {len(sure)} of those have a PM2.5 sensor that itself")
    print("reported throughout. Left out because OpenAQ gave no sensor list for them: monitors")
    print(f"{', '.join(unread) or 'none'}. Sample days: {', '.join(map(str, days))}\n")
    print("\n".join(report(groups, present, len(days))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
