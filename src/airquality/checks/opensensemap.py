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
RULES = {
    "pm25": (r"pm\s?2[.,]5", "µg/m³"),
    "temperature": (r"temp", "°C"),
    "relative_humidity": (r"feucht|humid", "%"),
}


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


def parameter(sensor: dict) -> str | None:
    """The parameter a sensor measures, by `RULES`, or None. Units are compared after NFKC."""
    title, unit = sensor.get("title") or "", (sensor.get("unit") or "").strip()
    for name, (pattern, wanted) in RULES.items():
        same_unit = unicodedata.normalize("NFKC", unit).startswith(
            unicodedata.normalize("NFKC", wanted)
        )
        if re.search(pattern, title, re.I) and same_unit:
            return name
    return None


def sensors(box: Box) -> dict[str, dict]:
    """The first sensor of each parameter in a box."""
    placed = {}
    for sensor in box.meta.get("sensors", []):
        placed.setdefault(parameter(sensor), sensor)
    placed.pop(None, None)
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
    day: date, listing: str, boxes: int, box: Box, sample: list[Box], site: dict, summary: str
) -> list[Finding]:
    """Every finding. `site` is the site's text by key, `summary` the licence summary page."""
    modified = folders(listing)
    wanted = [START + timedelta(days=n) for n in range((max(modified) - START).days + 1)]
    missing = [str(d) for d in wanted if d not in modified]
    recent = sorted(modified)[-30:]
    lags = [(modified[d] - datetime.fromisoformat(f"{d}T00:00+00:00")).total_seconds() / 3600 - 24
            for d in recent]  # fmt: skip
    own = sensors(box)
    files = {name: box.files.get(sensor["_id"], "") for name, sensor in own.items()}
    stamps = [stamp for stamp, _ in readings(files.get("pm25", ""))]
    heads = {text.split("\n", 1)[0].strip() for text in box.files.values()}
    licences = sorted({text for text in site.values() if "opendatacommons.org" in str(text)})
    conditions = re.search(r"[^.<>]*imposes no restrictions[^.<>]*\.", summary)
    findings = [
        Finding(
            "Day folders in the archive",
            f"{min(modified)} to {max(modified)}; {len(missing)} days since {START} have none"
            + (": " + ", ".join(missing) if missing else ""),
            ARCHIVE,
            f"a folder for every day since {START}, all at the top level",
            not missing,
        ),
        Finding(f"Boxes with a folder on {day}", str(boxes), f"{ARCHIVE}/{day}/"),
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
            "Timestamps in the PM2.5 file",
            f"first {min(stamps)}, last {max(stamps)}" if stamps else "no PM2.5 reading",
            box.url,
            f"all on {day}, in UTC (ending in Z)",
            bool(stamps) and all(s.startswith(str(day)) and s.endswith("Z") for s in stamps),
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
    findings += [
        Finding("Where the sampled boxes stand", str(dict(exposure.most_common())), source),
        Finding("Sampled boxes with PM2.5, temperature and humidity", str(complete), source),
    ]
    for name in RULES:
        named = Counter(f"{own[name]['title']} [{own[name]['unit']}]" for own in placed
                        if name in own)  # fmt: skip
        found = "; ".join(f"{label} x{count}" for label, count in named.most_common())
        findings.append(Finding(f"Names of {name} sensors in the sample", found, source))
    for name, (low, high) in RANGES.items():
        per_box = [[value for _, value in readings(b.files.get(own[name]["_id"], ""))]
                   for b, own in zip(sample, placed, strict=True) if name in own]  # fmt: skip
        values = [value for box_values in per_box for value in box_values]
        out = sum(1 for value in values if not low <= value <= high)
        bad = sum(1 for box_values in per_box if any(not low <= v <= high for v in box_values))
        found = f"{out} of {len(values)} readings outside, in {bad} of {len(per_box)} boxes"
        title, found = (
            f"{name} against the proposed {low} to {high}",
            f"{found}; {spread(values, '')}",
        )
        findings.append(Finding(title, found, source, "no reading outside", out == 0))
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
    wanted = {sensor["_id"] for sensor in sensors(Box(url, meta, {})).values()}
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
    findings = check(day, listing, len(names), box, sample, site, summary)
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
