"""Task 1.8: write the catalog entry of each source, from its contract and the registry.

    uv run python -m airquality.catalog    rewrites catalog/generated/<source>.json

An entry says what a source is and under which terms it may be used. Its names are modelled on
DCAT, the W3C's vocabulary for data catalogs; it is not a DCAT document and claims no
conformance. The contract gives the title, the publisher, the licence, how often the source
adds data and where it is downloaded. The registry gives the time range and the area: the
stations of this source that the platform uses. The files are generated, never edited by hand.
"""

import csv
import json
import sys
from pathlib import Path

from airquality.contracts import CONTRACTS, Contract, load
from airquality.registry import SEEDS

OUT = Path(__file__).parents[2] / "catalog" / "generated"


def registered(source: str) -> list[dict[str, str]]:
    """The rows of the registry seed that belong to a source."""
    with open(SEEDS / "registry.csv", newline="", encoding="utf-8") as table:
        return [row for row in csv.DictReader(table) if row["source"] == source]


def entry(contract: Contract, stations: list[dict[str, str]]) -> dict:
    """The catalog entry of a source, given its rows of the registry."""
    if not stations:
        raise ValueError(f"{contract.source}: the registry has no station of this source")
    east = [float(row["longitude"]) for row in stations]
    north = [float(row["latitude"]) for row in stations]
    return {
        "type": "Dataset",
        "identifier": contract.source,
        "title": contract.title,
        "publisher": contract.publisher,
        "license": contract.licence["name"],
        "rights": f"Credit: {contract.licence['credit']}",
        # From the first day any of its stations is used. No end: the source is still loaded.
        "temporal": {"startDate": min(row["start_date"] for row in stations), "endDate": None},
        "spatial": {
            "places": sorted({row["city"] for row in stations}),
            "bbox": [min(east), min(north), max(east), max(north)],  # west, south, east, north
        },
        "accrualPeriodicity": contract.updates,
        "distribution": [{"downloadURL": contract.download, "format": contract.format}],
    }


def text(source: str) -> str:
    """The catalog file of a source, as it is written."""
    built = entry(load(source), registered(source))
    return json.dumps(built, indent=2, ensure_ascii=False) + "\n"


def main(out: Path = OUT) -> int:
    out.mkdir(parents=True, exist_ok=True)
    sources = sorted(contract.stem for contract in CONTRACTS.glob("*.yml"))
    for source in sources:
        (out / f"{source}.json").write_text(text(source), encoding="utf-8")
        print(f"Wrote {out / source}.json")
    # An entry whose contract is gone is removed: the folder holds one entry per source, no more.
    for left in sorted(set(out.glob("*.json")) - {out / f"{source}.json" for source in sources}):
        left.unlink()
        print(f"Removed {left}, which has no contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
