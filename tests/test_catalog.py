"""The catalog entry of a source: it is generated, and it says what the contract says."""

import dataclasses
import json

import pytest

from airquality import catalog
from airquality.contracts import load

OPENAQ = load("openaq")
STATION = {"city": "Berlin", "latitude": "52.5", "longitude": "13.4", "start_date": "2025-01-01"}


def test_the_committed_entry_is_what_the_contract_and_the_registry_give():
    committed = (catalog.OUT / "openaq.json").read_text(encoding="utf-8")
    assert committed == catalog.text("openaq")
    assert sorted(path.stem for path in catalog.OUT.glob("*.json")) == sorted(
        path.stem for path in catalog.CONTRACTS.glob("*.yml")
    )


def test_the_openaq_entry_agrees_with_its_contract():
    entry = json.loads((catalog.OUT / "openaq.json").read_text(encoding="utf-8"))
    assert entry["identifier"] == OPENAQ.source and entry["title"] == OPENAQ.title
    assert entry["publisher"] == OPENAQ.publisher
    assert entry["license"] == OPENAQ.licence["name"]
    assert entry["rights"] == f"Credit: {OPENAQ.licence['credit']}"
    assert entry["accrualPeriodicity"] == OPENAQ.updates
    assert entry["distribution"] == [{"downloadURL": OPENAQ.download, "format": OPENAQ.format}]


def test_the_openaq_entry_covers_the_stations_of_the_registry():
    entry, stations = json.loads(catalog.text("openaq")), catalog.registered("openaq")
    assert len(stations) == 3 and entry["spatial"]["places"] == ["Berlin"]
    west, south, east, north = entry["spatial"]["bbox"]
    for station in stations:
        assert west <= float(station["longitude"]) <= east
        assert south <= float(station["latitude"]) <= north
    assert (west, north) == (13.318250000381642, 52.51407199975142)  # two of the three monitors
    assert entry["temporal"] == {"startDate": "2025-01-01", "endDate": None}


def test_an_entry_follows_a_change_of_the_contract_or_of_the_registry():
    changed = dataclasses.replace(OPENAQ, title="Another title", updates="hourly")
    wien = STATION | {"city": "Wien", "latitude": "48.2", "longitude": "16.4"}
    late = STATION | {"start_date": "2025-06-01"}
    entry = catalog.entry(changed, [late, wien])
    assert (entry["title"], entry["accrualPeriodicity"]) == ("Another title", "hourly")
    assert entry["spatial"] == {"places": ["Berlin", "Wien"], "bbox": [13.4, 48.2, 16.4, 52.5]}
    assert entry["temporal"]["startDate"] == "2025-01-01"
    assert catalog.entry(OPENAQ, [late])["temporal"]["startDate"] == "2025-06-01"


def test_a_source_with_no_station_in_the_registry_has_no_entry():
    assert catalog.registered("elsewhere") == []
    with pytest.raises(ValueError, match="openaq: the registry has no station of this source"):
        catalog.entry(OPENAQ, [])
