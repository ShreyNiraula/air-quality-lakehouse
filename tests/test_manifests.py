"""The source manifests: the committed ones are sound, and each kind of broken one is named."""

import copy

import pytest

from airquality.manifests import PERMISSIONS, read, spacing, validate

SENSOR = {"id": "7", "parameter": "pm25", "name_as_found": "pm25", "unit_as_found": "µg/m³"}
MANIFEST = {
    "files": {"from": "2025-01-01", "to": "2025-01-03"},
    "licence": {
        "name": "A licence",
        "credit": "A source",
        "statements": [{"by": "A source", "url": "https://example.org", "says": "Free to use."}],
        "permissions": dict.fromkeys(PERMISSIONS, True),
    },
    "stations": [
        {
            "id": "1",
            "name": "A station",
            "city": "Berlin",
            "provider": "A source",
            "latitude": 52.5,
            "longitude": 13.4,
            "first_reading": "2025-01-01T00:00:00Z",
            "last_reading": "2025-01-03T23:00:00Z",
            "timezone": "Europe/Berlin",
            "sensors": [SENSOR],
            "licence_in_source_record": dict.fromkeys(PERMISSIONS, True),
            "dates_with_no_file": {"location": ["2025-01-02"]},
        }
    ],
}
ROWS = [
    {"station": "1", "series": "location", "date": day, "md5": "0123456789abcdef" * 2}
    for day in ("2025-01-01", "2025-01-03")
]


@pytest.mark.parametrize(
    ("source", "stations", "files"), [("openaq", 6, 3000), ("opensensemap", 7, 700)]
)
def test_the_committed_manifests_are_sound(source, stations, files):
    manifest, rows = read(source)
    assert validate(manifest, rows) == []
    assert {station["city"] for station in manifest["stations"]} == {"Berlin", "Wien"}
    assert len(manifest["stations"]) == stations and len(rows) > files


def broken(change):
    manifest, rows = copy.deepcopy(MANIFEST), copy.deepcopy(ROWS)
    change(manifest, manifest["stations"][0], rows)
    return validate(manifest, rows)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda m, s, r: None, None),
        (lambda m, s, r: m["licence"]["permissions"].pop("share_alike"), "five permissions"),
        (lambda m, s, r: m["licence"].update(credit=""), "credit line is missing"),
        (lambda m, s, r: m["licence"]["statements"][0].pop("url"), "its address"),
        (lambda m, s, r: r[0].update(md5="not a hash"), "bad hash or date"),
        (lambda m, s, r: r[0].update(date="2024-12-31"), "bad hash or date"),
        (lambda m, s, r: r.append(dict(r[0])), "listed twice"),
        (lambda m, s, r: r.append(r[0] | {"station": "9"}), "unknown one"),
        (lambda m, s, r: s.update(timezone="Mars/Olympus"), "unknown timezone"),
        (lambda m, s, r: s.update(latitude=None, provider=""), "no provider, latitude"),
        (lambda m, s, r: s["sensors"].append(dict(SENSOR)), "exactly one PM2.5"),
        (lambda m, s, r: s["sensors"][0].update(unit_as_found=""), "no unit text"),
        (lambda m, s, r: s["licence_in_source_record"].update(share_alike=False), "disagrees"),
        (lambda m, s, r: s["dates_with_no_file"]["location"].clear(), "for every date"),
        (lambda m, s, r: s["dates_with_no_file"]["location"].append("2025-01-01"), "not both"),
    ],
)
def test_each_kind_of_broken_manifest_is_named(change, problem):
    found = broken(change)
    assert (found == []) if problem is None else any(problem in line for line in found), found


def test_spacing_is_the_usual_gap_in_seconds():
    hours = [f"2025-01-01T{hour:02}:00:00+01:00" for hour in (3, 1, 2, 7)]
    assert spacing(hours) == 3600
    assert spacing(hours[:1]) == 0
