"""Task 0.6: confirm the vocabulary's standard names and unit spellings at their sources.

    uv run python -m airquality.checks.vocabulary

Reads the CF standard-name table and the UCUM unit tables and prints each row of the vocabulary
in `plan.md` next to what they say. The exit code is 1 if a row differs. The WHO guideline value
is a number in a PDF and is confirmed by eye; see `docs/checks/0.6-vocabulary.md`.
"""

import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

CF_TABLE = "https://cfconventions.org/Data/cf-standard-names/current/src/cf-standard-name-table.xml"
UCUM_TABLES = "https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml"
UCUM = "{http://unitsofmeasure.org/ucum-essence}"
# The vocabulary table of plan.md: parameter, CF standard name, CF's own unit, stored UCUM unit.
VOCABULARY = [
    ("pm25", "mass_concentration_of_pm2p5_ambient_aerosol_particles_in_air", "kg m-3", "ug/m3"),
    ("temperature", "air_temperature", "K", "Cel"),
    ("relative_humidity", "relative_humidity", None, "%"),  # plan.md does not state CF's unit
]


def cf_units(table: ET.Element) -> dict[str, str]:
    """Each current standard name with its canonical unit. Aliases of old names are left out."""
    return {entry.get("id"): entry.findtext("canonical_units") for entry in table.iter("entry")}


def ucum_parts(tables: ET.Element) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Prefix codes and unit codes with their names, and the unit codes that may take a prefix."""
    prefixes = {
        item.get("Code"): item.findtext(f"{UCUM}name") for item in tables.iter(f"{UCUM}prefix")
    }
    bases = list(tables.iter(f"{UCUM}base-unit"))
    units = list(tables.iter(f"{UCUM}unit"))
    names = {item.get("Code"): item.findtext(f"{UCUM}name") for item in bases + units}
    metric = {item.get("Code") for item in bases}
    return (
        prefixes,
        names,
        metric | {item.get("Code") for item in units if item.get("isMetric") == "yes"},
    )


def read_ucum(unit: str, tables: ET.Element) -> str | None:
    """A UCUM unit spelled out in words, or None if a part of it is not in the tables.

    Covers what the vocabulary uses: unit codes with an optional prefix and whole-number power,
    joined by "/".
    """
    prefixes, names, metric = ucum_parts(tables)
    words = []
    for term in unit.split("/"):
        code, power = re.fullmatch(r"(.*?)([0-9]*)", term).groups()
        if code in names:
            word = names[code]
        elif code[:1] in prefixes and code[1:] in metric:
            word = f"{prefixes[code[0]]} {names[code[1:]]}"
        else:
            return None
        words.append(f"{word} to the power {power}" if power else word)
    return " per ".join(words)


def check(cf: ET.Element, ucum: ET.Element) -> list[tuple[bool, str]]:
    """One line per vocabulary entry and source, with whether it agrees with plan.md."""
    units = cf_units(cf)
    lines = []
    for parameter, name, cf_unit, stored in VOCABULARY:
        found = units.get(name)
        agrees = name in units and cf_unit in (None, found)
        expected = f", plan.md says {cf_unit}" if cf_unit else ""
        lines.append((agrees, f"{parameter}: CF name {name}: unit in the table {found}{expected}"))
        words = read_ucum(stored, ucum)
        lines.append(
            (words is not None, f"{parameter}: UCUM unit {stored}: {words or 'not valid'}")
        )
    return lines


def fetch(url: str) -> ET.Element:
    with urllib.request.urlopen(url, timeout=120) as response:
        return ET.fromstring(response.read())


def main() -> int:
    cf, ucum = fetch(CF_TABLE), fetch(UCUM_TABLES)
    print("Vocabulary check (task 0.6)")
    print(f"Run at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC with: python -m {__spec__.name}")
    version, modified = cf.findtext("version_number"), cf.findtext("last_modified")
    print(f"CF standard-name table version {version}, last modified {modified}: {CF_TABLE}")
    print(
        f"UCUM tables version {ucum.get('version')} of {ucum.get('revision-date')}: {UCUM_TABLES}\n"
    )
    lines = check(cf, ucum)
    for agrees, line in lines:
        print(f"[{'match  ' if agrees else 'DIFFERS'}] {line}")
    differing = sum(1 for agrees, _ in lines if not agrees)
    print(f"\n{differing} rows differ from plan.md.")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
