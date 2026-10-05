"""The openSenseMap check, on made-up pages and files shaped like the real ones. No network."""

from datetime import UTC, date, datetime

import pytest

from airquality.checks.opensensemap import BOX_FOLDER, Box, check, folders, parameter

DAY, NOW = date(2025, 1, 3), datetime(2025, 1, 5, 12, tzinfo=UTC)
SOIL = {"_id": "e" * 24, "title": "Bodentemperatur", "unit": "°C"}
BOX = "a" * 24 + "-My_Box/"
ROW = """<a href="./{day}/"><span class="name">{day}/</span></a></td>
<td class="hideable"><time datetime="{modified}">x</time></td>"""
SITE = {"L": 'Data: <a href="http://opendatacommons.org/licenses/pddl/summary/">PDDL 1.0</a>'}
SUMMARY = "<p><em>Blank</em>: The PDDL imposes no restrictions on your use of the database.</p>"
SENSORS = [
    {"_id": "a" * 24, "title": "PM10", "unit": "µg/m³", "sensorType": "SDS 011"},
    {"_id": "b" * 24, "title": "PM2.5", "unit": "µg/m³", "sensorType": "SDS 011"},
    {"_id": "c" * 24, "title": "Temperatur", "unit": "°C", "sensorType": "DHT22"},
    {"_id": "d" * 24, "title": "rel. Luftfeuchte", "unit": "%", "sensorType": "DHT22"},
]


def listing(days=("2025-01-01", "2025-01-02", "2025-01-03")):
    rows = [(d, f"{d[:8]}{int(d[8:]) + 1:02}T08:10:12Z") for d in days]  # modified the next day
    return "\n".join(ROW.format(day=d, modified=modified) for d, modified in rows)


def box(sensors=SENSORS, stamp="2025-01-03T00:02:27.710Z", temperature="13.70", pm_stamp=None):
    files = {
        "b" * 24: f"createdAt,value\n{pm_stamp or stamp},3.30\n2025-01-03T00:05:00.000Z,4.00\n",
        "c" * 24: f"createdAt,value\n{stamp},{temperature}\n2025-01-03T00:05:00.000Z,nan\n",
        "d" * 24: f"createdAt,value\n{stamp},99.90\n",
    }
    return Box("https://example.org/box/", {"exposure": "outdoor", "sensors": sensors}, files)


def findings(pages=None, own=None, sample=None, site=SITE, summary=SUMMARY):
    result = check(DAY, NOW, pages or listing(), own or box(), sample or [box()], site, summary)
    return {finding.name: finding for finding in result}


def test_inputs_shaped_like_the_real_ones_match_every_expectation():
    result = findings(sample=[box(sensors=[SOIL, {"title": "Air T", "unit": "°C"}, *SENSORS])])
    assert [name for name, finding in result.items() if finding.matches is False] == []
    assert "PM2.5 [µg/m³] SDS 011 -> pm25" in result["Sensors of the box"].found
    assert result["Sampled boxes with PM2.5, temperature and humidity"].found == "1"
    assert result["Names of temperature sensors in the sample"].found == "Temperatur [°C] x1"
    unplaced = result["Sampled sensors in these units that the rule skips"].found
    assert unplaced == "Air T [°C]; Bodentemperatur [°C]; PM10 [µg/m³]"


def test_the_listing_gives_each_day_folder_and_the_lag_after_the_utc_day():
    assert folders(listing())[date(2025, 1, 2)].isoformat() == "2025-01-03T08:10:12+00:00"
    assert BOX_FOLDER.findall(f'<a href="./{BOX}">x</a> <a href="./2025-01-01/">y</a>') == [BOX]
    lag = findings()["Hours from the end of a UTC day until its folder was last modified"]
    assert lag.found == "median 8.2, least 8.2, most 8.2 hours, over the newest 3 days"


def test_days_without_a_folder_are_named_even_when_they_are_the_newest():
    result = findings(pages=listing(("2025-01-01", "2025-01-02")))["Day folders in the archive"]
    assert result.matches is False
    assert result.found.endswith("1 days from 2025-01-01 to 2025-01-03 have none: 2025-01-03")


STAMPS = "Timestamps in the three sensor files of the box"
BROKEN = [
    ({"own": box(sensors=SENSORS[:3])}, f"Sensors of the box; {STAMPS}"),  # no humidity sensor
    ({"own": box(stamp="2025-01-02T23:59:00.000Z")}, STAMPS),
    ({"own": box(stamp="2025-01-03T00:02:27")}, STAMPS),  # no Z
    ({"own": box(stamp="2025-01-02T23:59:00.000Z", pm_stamp="2025-01-03T00:01:00.000Z")}, STAMPS),
    ({"site": {"ARCHIVE": "Archive"}}, "Licence named in the site's own text"),
    ({"summary": "<p>Terms apply.</p>"}, "Conditions of that licence"),
    (
        {"sample": [box(temperature="nan")]},
        "temperature against the proposed -60 to 60",
    ),  # no value
]


@pytest.mark.parametrize(("inputs", "name"), BROKEN)
def test_one_broken_input_makes_only_its_own_findings_differ(inputs, name):
    result = findings(**inputs)
    assert "; ".join(found for found, f in result.items() if f.matches is False) == name


def test_ranges_read_every_placed_sensor_and_report_those_with_no_reading():
    two = box(sensors=[*SENSORS, {"_id": "f" * 24, "title": "Temperatur (HECA)", "unit": "°C"}])
    two.files["f" * 24] = "createdAt,value\n2025-01-03T00:02:00.000Z,-146.10\n"
    result = findings(sample=[two, box(temperature="nan")])
    found = result["temperature against the proposed -60 to 60"]
    assert found.matches is False
    assert "1 of 2 readings outside, in 1 of 2 sensors read; 1 more sensors had no" in found.found


CASES = [
    ("Feinstaub PM2,5", "µg/m³", "pm25"),
    ("PM2.5", "μg/m³ ", "pm25"),  # a Greek mu, and a trailing space
    ("PM10", "µg/m³", None),
    ("Luftfeuchte", "%rF", "relative_humidity"),
    ("Feuchtigkeit (Hochbeet)", "% nFK", None),  # soil moisture in a raised bed
    ("Bodenfeuchte", "%", None),
    ("Temperatur", "K", None),
]


@pytest.mark.parametrize(("title", "unit", "expected"), CASES)
def test_a_sensor_is_placed_by_its_name_and_unit(title, unit, expected):
    assert parameter({"title": title, "unit": unit}) == expected
