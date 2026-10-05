"""The openSenseMap check, on made-up pages and files shaped like the real ones. No network."""

from datetime import date

import pytest

from airquality.checks.opensensemap import BOX_FOLDER, Box, check, folders, parameter

DAY = date(2025, 1, 3)
BOX = "a" * 24 + "-My_Box/"
ROW = """<a href="./{day}/"><span class="name">{day}/</span></a></td>
<td class="hideable"><time datetime="{modified}">x</time></td>"""
SITE = {
    "DOWNLOAD_LICENSE": 'All data is licensed under <a href="http://opendatacommons.org/licenses/'
    'pddl/summary/">Public Domain Dedication and License 1.0</a> and free to use.',
    "ARCHIVE": "Archive",
}
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


def box(sensors=SENSORS, pm="3.30", stamp="2025-01-03T00:02:27.710Z", temperature="13.70"):
    files = {
        "b" * 24: f"createdAt,value\n{stamp},{pm}\n2025-01-03T00:05:00.000Z,4.00\n",
        "c" * 24: f"createdAt,value\n{stamp},{temperature}\n2025-01-03T00:05:00.000Z,nan\n",
        "d" * 24: f"createdAt,value\n{stamp},99.90\n",
    }
    return Box("https://example.org/box/", {"exposure": "outdoor", "sensors": sensors}, files)


def findings(pages=None, own=None, sample=None, site=SITE, summary=SUMMARY):
    result = check(DAY, pages or listing(), 2, own or box(), sample or [box()], site, summary)
    return {finding.name: finding for finding in result}


def differing(**inputs):
    return [name for name, finding in findings(**inputs).items() if finding.matches is False]


def test_inputs_shaped_like_the_real_ones_match_every_expectation():
    result = findings()
    assert differing() == []
    assert "PM2.5 [µg/m³] SDS 011 -> pm25" in result["Sensors of the box"].found
    assert result["Sampled boxes with PM2.5, temperature and humidity"].found == "1"
    assert result["Names of temperature sensors in the sample"].found == "Temperatur [°C] x1"


def test_the_listing_gives_each_day_folder_and_the_lag_after_the_utc_day():
    assert folders(listing())[date(2025, 1, 2)].isoformat() == "2025-01-03T08:10:12+00:00"
    assert BOX_FOLDER.findall(f'<a href="./{BOX}">x</a> <a href="./2025-01-01/">y</a>') == [BOX]
    lag = findings()["Hours from the end of a UTC day until its folder was last modified"]
    assert lag.found == "median 8.2, least 8.2, most 8.2 hours, over the newest 3 days"


def test_a_day_without_a_folder_is_named():
    result = findings(pages=listing(("2025-01-01", "2025-01-03")))["Day folders in the archive"]
    assert result.matches is False
    assert result.found.endswith("1 days since 2025-01-01 have none: 2025-01-02")


def test_a_box_without_a_humidity_sensor_differs():
    assert differing(own=box(sensors=SENSORS[:3])) == ["Sensors of the box"]


@pytest.mark.parametrize("stamp", ["2025-01-02T23:59:00.000Z", "2025-01-03T00:02:27"])
def test_a_timestamp_on_another_day_or_without_z_differs(stamp):
    assert differing(own=box(stamp=stamp)) == ["Timestamps in the PM2.5 file"]


def test_a_reading_outside_the_proposed_range_is_counted_and_text_is_skipped():
    result = findings(sample=[box(), box(temperature="-146.10")])
    found = result["temperature against the proposed -60 to 60"]
    assert found.matches is False
    assert found.found.startswith("1 of 2 readings outside, in 1 of 2 boxes")


def test_a_site_or_a_summary_that_does_not_state_the_licence_differs():
    assert differing(site={"ARCHIVE": "Archive"}) == ["Licence named in the site's own text"]
    assert differing(summary="<p>Terms apply.</p>") == ["Conditions of that licence"]


CASES = [
    ("Feinstaub PM2,5", "µg/m³", "pm25"),
    ("PM2.5", "μg/m³ ", "pm25"),  # a Greek mu, and a trailing space
    ("PM10", "µg/m³", None),
    ("Luftfeuchte", "%rF", "relative_humidity"),
    ("battery", "%", None),
    ("Temperatur", "K", None),
    ("Bodentemperatur", "°C", "temperature"),  # soil, not air: a name alone cannot tell
]


@pytest.mark.parametrize(("title", "unit", "expected"), CASES)
def test_a_sensor_is_placed_by_its_name_and_unit(title, unit, expected):
    assert parameter({"title": title, "unit": unit}) == expected
