"""Task 0.5b: read real openSenseMap files and its licence statement, and print what is found.

    uv run python -m airquality.checks.opensensemap [--date 2025-01-01]

Every finding is printed with the address it was read from. Where `plan.md` states an expectation
the finding is marked as matching it or not, and the exit code is 1 if one does not.
"""

import argparse
import json
import re
import statistics
import sys
import unicodedata
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import sleep
from typing import NamedTuple

ARCHIVE = "https://archive.opensensemap.org"
SITE_TEXT = "https://opensensemap.org/translations/en_US.json"  # the site's own wording
SUMMARY = "https://opendatacommons.org/licenses/pddl/summary/"
BOX = "5ac38bcf850005001bfd2559"  # one outdoor box with an SDS011 and a DHT22
START = date(2025, 1, 1)  # the first day plan.md loads
SAMPLE = 20  # boxes read for the names, the units and the value ranges
BOX_FOLDER = re.compile(r'href="\./([0-9a-f]{24}-[^"/]*/)"')  # a box's folder in a day's listing
RANGES = {"temperature": (-60, 60), "relative_humidity": (0, 100)}  # proposed in plan.md
# How this check tells a parameter from a sensor's name and unit. The names are typed by owners.
# The units are written as they read after NFKC: a Greek mu and a plain 3.
RULES = {
    "pm25": (r"pm\s?2[.,]5", {"μg/m3"}),
    "temperature": (r"temp", {"°C"}),
    "relative_humidity": (r"feucht|humid", {"%", "%rF"}),
}
NOT_AIR = r"boden|soil|beet|wasser|water"  # names of sensors in the ground or in water


class Box(NamedTuple):
    url: str
    meta: dict  # the box's JSON metadata file
    files: dict[str, str]  # sensor id -> the text of its CSV file


@dataclass
class Finding:
    name: str
    found: str
    source: str
    expected: str | None = None  # None: plan.md states no expectation
    matches: bool | None = None


def folders(listing: str) -> dict[date, datetime]:
    """Each day folder with the time the listing says it was last modified."""
    found = re.findall(r'href="\./(\d{4}-\d\d-\d\d)/".*?datetime="([^"]+)"', listing, re.S)
    return {date.fromisoformat(day): datetime.fromisoformat(when) for day, when in found}


def unit_of(sensor: dict) -> str:
    return unicodedata.normalize("NFKC", (sensor.get("unit") or "").strip())  # as the unit rule


def parameter(sensor: dict) -> str | None:
    """The parameter a sensor measures, by `RULES`, or None."""
    title = sensor.get("title") or ""
    for name, (pattern, units) in RULES.items():
        named = re.search(pattern, title, re.I) and not re.search(NOT_AIR, title, re.I)
        if named and unit_of(sensor) in units:
            return name
    return None


def sensors(box: Box) -> dict[str, list[dict]]:
    """Every sensor of a box that `RULES` places, by its parameter."""
    placed = {}
    for sensor in box.meta.get("sensors", []):
        if name := parameter(sensor):
            placed.setdefault(name, []).append(sensor)
    return placed


def readings(text: str) -> list[tuple[str, float]]:
    rows = [line.split(",") for line in text.splitlines()[1:]]
    number = r"-?\d+(\.\d+)?"
    return [
        (row[0], float(row[1])) for row in rows if len(row) == 2 and re.fullmatch(number, row[1])
    ]


def spread(values: list[float], unit: str) -> str:
    if not values:
        return "nothing to measure"
    middle = statistics.median(values)
    return f"median {middle:.1f}, least {min(values):.1f}, most {max(values):.1f} {unit}".strip()


def spacing(text: str) -> str:
    stamps = [datetime.fromisoformat(stamp) for stamp, _ in readings(text)]
    stamps = sorted(t if t.tzinfo else t.replace(tzinfo=UTC) for t in stamps)  # none given: UTC
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
    return spread(gaps, "seconds")


def check(
    day: date, now: datetime, listing: str, box: Box, sample: list[Box], site: dict, summary: str
) -> list[Finding]:
    """Every finding. `site` is the site's text by key, `summary` the licence summary page."""
    modified = folders(listing)
    due = (now - timedelta(days=2)).date()  # a day's folder is expected once two days have passed
    wanted = [START + timedelta(days=n) for n in range((due - START).days + 1)]
    missing = [str(d) for d in wanted if d not in modified]
    lags = [(modified[d] - datetime.fromisoformat(f"{d}T00:00+00:00")).total_seconds() / 3600 - 24
            for d in sorted(modified)[-30:]]  # fmt: skip
    own = sensors(box)
    files = {name: box.files.get(group[0]["_id"], "") for name, group in own.items()}
    stamps = [stamp for text in files.values() for stamp, _ in readings(text)]
    heads = {text.split("\n", 1)[0].strip() for text in box.files.values()}
    licences = sorted({text for text in site.values() if "opendatacommons.org" in str(text)})
    conditions = re.search(r"[^.<>]*imposes no restrictions[^.<>]*\.", summary)
    findings = [
        Finding(
            "Day folders in the archive",
            f"{min(modified)} to {max(modified)}; {len(missing)} days from {START} to {due} have "
            + ("none: " + ", ".join(missing) if missing else "none"),
            ARCHIVE,
            f"a folder for every day from {START} to two days before the run, at the top level",
            not missing,
        ),
        Finding(
            "Sensors of the box",
            "; ".join(
                f"{s.get('title')} [{s.get('unit')}] {s.get('sensorType')} -> {parameter(s)}"
                for s in box.meta.get("sensors", [])
            ),  # fmt: skip
            box.url,
            "PM2.5, temperature and humidity in one box, joined by the box id",
            set(own) == set(RULES),
        ),
        Finding(
            "First line of each sensor file of the box",
            " | ".join(sorted(heads)) or "no file",
            box.url,
            "createdAt,value",
            heads == {"createdAt,value"},
        ),
        Finding(
            "Timestamps in the three sensor files of the box",
            f"first {min(stamps)}, last {max(stamps)}" if stamps else "no reading",
            box.url,
            f"readings in each file, all on {day} and in UTC (ending in Z)",
            all(readings(text) for text in files.values())
            and all(s.startswith(str(day)) and s.endswith("Z") for s in stamps),
        ),
        Finding(
            "Time between readings, per sensor file of the box",
            "; ".join(f"{name}: {spacing(text)}" for name, text in files.items()),
            box.url,
        ),
        Finding(
            "Hours from the end of a UTC day until its folder was last modified",
            f"{spread(lags, 'hours')}, over the newest {len(lags)} days",
            ARCHIVE,
        ),
        Finding(
            "Licence named in the site's own text",
            " | ".join(re.sub(r"<[^>]+>", "", text) for text in licences) or "none",
            SITE_TEXT,
            "a licence for the data is named",
            any("licenses/pddl" in text for text in licences),
        ),
        Finding(
            "Conditions of that licence",
            conditions.group().strip() if conditions else "the sentence was not found",
            SUMMARY,
            "no conditions",
            conditions is not None,
        ),
    ]
    source = f"{len(sample)} boxes of {day}, spread over the folder"
    placed = [sensors(b) for b in sample]
    complete = sum(1 for own in placed if set(own) == set(RULES))
    exposure = Counter(str(b.meta.get("exposure")) for b in sample)
    units = set().union(*(units for _, units in RULES.values()))
    every = [s for b in sample for s in b.meta.get("sensors", [])]
    skipped = sorted({f"{s.get('title')} [{s.get('unit')}]" for s in every
                      if unit_of(s) in units and not parameter(s)})  # fmt: skip
    findings += [
        Finding("Where the sampled boxes stand", str(dict(exposure.most_common())), source),
        Finding("Sampled boxes with PM2.5, temperature and humidity", str(complete), source),
        Finding("Sampled sensors in these units that the rule skips", "; ".join(skipped), source),
    ]
    for name in RULES:
        named = Counter(f"{s['title']} [{s.get('unit')}]" for own in placed
                        for s in own.get(name, []))  # fmt: skip
        found = "; ".join(f"{label} x{count}" for label, count in named.most_common())
        findings.append(Finding(f"Names of {name} sensors in the sample", found, source))
    for name, (low, high) in RANGES.items():
        each = [[value for _, value in readings(b.files.get(s["_id"], ""))]
                for b, o in zip(sample, placed, strict=True) for s in o.get(name, [])]  # fmt: skip
        read = [one for one in each if one]
        values = [value for one in read for value in one]
        out = sum(1 for value in values if not low <= value <= high)
        bad = sum(1 for one in read if any(not low <= value <= high for value in one))
        found = f"{out} of {len(values)} readings outside, in {bad} of {len(read)} sensors read"
        found += f"; {len(each) - len(read)} more sensors had no reading; {spread(values, '')}"
        title = f"{name} against the proposed {low} to {high}"
        matches = bool(values) and out == 0  # nothing read proves nothing
        findings.append(Finding(title, found, source, "readings, and none outside", matches))
    return findings


def fetch(url: str) -> str:
    sleep(0.1)  # be polite to the server
    request = urllib.request.Request(url, headers={"User-Agent": "airquality-check"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8")


def read_box(url: str) -> Box:
    """A box's metadata and the files of its PM2.5, temperature and humidity sensors."""
    names = re.findall(r'href="\./([^"]+)"', fetch(url))
    described = [name for name in names if name.endswith(".json")]
    meta = json.loads(fetch(url + described[0])) if described else {}
    wanted = {s["_id"] for group in sensors(Box(url, meta, {})).values() for s in group}
    files = {name[:24]: fetch(url + name) for name in names if name[:24] in wanted}
    return Box(url, meta, files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat, help="default: the newest day folder")
    args = parser.parse_args()
    listing = fetch(ARCHIVE + "/")
    day = args.date or max(folders(listing))
    names = BOX_FOLDER.findall(fetch(f"{ARCHIVE}/{day}/"))
    own = next((name for name in names if name.startswith(BOX)), None)
    if own is None:
        sys.exit(f"Box {BOX} has no folder on {day}; try another --date.")
    spread_out = names[:: max(1, len(names) // SAMPLE)][:SAMPLE]
    box = read_box(f"{ARCHIVE}/{day}/{own}")
    sample = [read_box(f"{ARCHIVE}/{day}/{name}") for name in spread_out]
    site, summary = json.loads(fetch(SITE_TEXT)), fetch(SUMMARY)
    findings = check(day, datetime.now(UTC), listing, box, sample, site, summary)
    command = " ".join(["python -m airquality.checks.opensensemap", *sys.argv[1:]])
    print("openSenseMap check (task 0.5b)")
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
