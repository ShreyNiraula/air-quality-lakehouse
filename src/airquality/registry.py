"""Task 1.2: write the registry seed of the dbt project from the source manifests.

    uv run python -m airquality.registry    rewrites dbt_project/seeds/registry.csv

The registry has one row per station and parameter: the station, and the one sensor whose rows
are used for that parameter. It holds the sources and cities in REGISTERED, and of their sensors
only those that measure a parameter of the vocabulary, `dbt_project/seeds/parameter.csv`.
"""

import csv
import io
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from airquality import manifests

SEEDS = Path(__file__).parents[2] / "dbt_project" / "seeds"
# Milestone 1 is one source and one city. Task 2.4 adds Wien and the openSenseMap boxes.
REGISTERED = {"openaq": ("Berlin",)}
COLUMNS = (
    "source",
    "station_id",
    "station_name",
    "city",
    "latitude",
    "longitude",
    "timezone",
    "provider",
    "licence",
    "credit",
    "sensor_id",
    "parameter",
    "start_date",
)


def vocabulary() -> list[str]:
    """The names of the parameters in the vocabulary seed."""
    with open(SEEDS / "parameter.csv", newline="", encoding="utf-8") as table:
        return [row["parameter"] for row in csv.DictReader(table)]


def rows(manifest: dict, cities: tuple[str, ...], parameters: list[str]) -> list[dict]:
    """The registry rows of one source: its stations in `cities`, for `parameters` only."""
    licence, period = manifest["licence"], date.fromisoformat(manifest["files"]["from"])
    found = []
    for station in manifest["stations"]:
        if station["city"] not in cities:
            continue
        # A station that began after the period did starts on the local day of its first reading.
        # The manifest gives that reading for the station, not for each of its sensors.
        first = datetime.fromisoformat(station["first_reading"])
        began = first.astimezone(ZoneInfo(station["timezone"])).date()
        shared = {name: station[name] for name in ("city", "latitude", "longitude", "timezone")}
        for sensor in station["sensors"]:
            if sensor["parameter"] in parameters:
                found.append(shared | {
                    "source": manifest["source"],
                    "station_id": station["id"],
                    "station_name": station["name"],
                    "provider": station["provider"],
                    "licence": licence["name"],
                    "credit": licence["credit"],
                    "sensor_id": sensor["id"],
                    "parameter": sensor["parameter"],
                    "start_date": str(max(period, began)),
                })  # fmt: skip
    return sorted(found, key=lambda row: (row["city"], row["station_id"], row["parameter"]))


def build() -> str:
    """The registry seed as text, from the committed manifests."""
    parameters, text = vocabulary(), io.StringIO()
    writer = csv.DictWriter(text, COLUMNS, lineterminator="\n")
    writer.writeheader()
    for source, cities in REGISTERED.items():
        manifest, _ = manifests.read(source)
        writer.writerows(rows(manifest, cities, parameters))
    return text.getvalue()


def main() -> int:
    (SEEDS / "registry.csv").write_text(build(), encoding="utf-8")
    print(f"Wrote {SEEDS / 'registry.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
