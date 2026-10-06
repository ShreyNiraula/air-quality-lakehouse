"""The Sensor.Community check, on made-up pages and files shaped like the real ones. No network."""

from datetime import UTC, date, datetime

from airquality.checks.sensor_community import Fetched, check, climate_files, folders, licence_links

DAY = date(2026, 3, 1)
NOW = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)
LISTING = """<a href="2015/">2015/</a>  2023-03-02 18:25
<a href="2025/">2025/</a>  2026-01-08 21:12
<a href="2026-02-28/">2026-02-28/</a></td><td align="right">2026-03-01 04:30  </td>
<a href="2026-03-01/">2026-03-01/</a></td><td align="right">2026-03-02 03:30  </td>
<a href="2026-03-01_dht22_sensor_8.csv">x</a> <a href="2026-03-01_sds011_sensor_7.csv">x</a>
<a href="2026-03-01_bme280_sensor_9.csv">x</a> <a href="csv_per_month/">csv_per_month/</a>"""
PAGE = """<a href=https://www.gnu.org/licenses/gpl-3.0.en.html class="x">Firmware License </a>
<a href=https://opendatacommons.org/licenses/dbcl/1-0/ class="x">DB Contents License </a>
<a href="https://archive.sensor.community/">Archive</a>"""
DUST = """sensor_id;sensor_type;location;lat;lon;timestamp;P1;durP1;ratioP1;P2;durP2;ratioP2
7;SDS011;5;1.0;2.0;2026-03-01T00:01:00;11.00;;;8.50;;
7;SDS011;5;1.0;2.0;2026-03-01T00:03:30;12.00;;;9.00;;
7;SDS011;5;1.0;2.0;2026-03-01T23:58:00;10.00;;;;;
"""
CLIMATE = """sensor_id;sensor_type;location;lat;lon;timestamp;temperature;humidity
8;DHT22;5;1.0;2.0;2026-03-01T00:01:00;14.30;52.80
8;DHT22;5;1.0;2.0;2026-03-01T00:03:30;15.00;60.00
8;DHT22;5;1.0;2.0;2026-03-01T00:06:00;;nan
"""


def findings(dust=DUST, climate=CLIMATE, page=PAGE, live="2026-03-03T11:57:00", day=DAY):
    files = [Fetched(f"https://example.org/{name}", body.encode(), "a GMT time") for name, body in
             (("dust.csv", dust), ("climate.csv", climate))]  # fmt: skip
    result = check(day, NOW, LISTING, *files, [climate.encode()], page, live)
    return {finding.name: finding for finding in result}


def test_inputs_shaped_like_the_real_ones_match_every_expectation():
    result = findings()
    assert [name for name, finding in result.items() if finding.matches is False] == []
    assert result["Dust rows where P2 is above P1"].found == "0 of 3"
    spacing = result["Time between readings, dust file"].found
    assert spacing == "median 43110.0, least 150.0, most 86070.0 seconds"
    headers = result["Column sets among the sampled climate files"].found
    assert headers == "sensor_id;sensor_type;location;lat;lon;timestamp;temperature;humidity"
    assert all(finding.source for finding in result.values())


def test_listing_gives_folders_lag_and_climate_files():
    years, modified = folders(LISTING)
    assert years == ["2015", "2025"]
    assert modified == {
        date(2026, 2, 28): datetime(2026, 3, 1, 4, 30),
        date(2026, 3, 1): datetime(2026, 3, 2, 3, 30),
    }
    lag = "Hours from the end of a UTC day until its folder was last modified, by the listing"
    assert findings()[lag].found == "median 4.0, least 3.5, most 4.5 hours, over 2 days"
    assert climate_files(LISTING + '<a href="2025-06-01_dht22_sensor_8.csv.gz">') == [
        "2026-03-01_dht22_sensor_8.csv",
        "2026-03-01_bme280_sensor_9.csv",
        "2025-06-01_dht22_sensor_8.csv.gz",
    ]


def test_readings_outside_the_proposed_ranges_differ_and_blanks_are_skipped():
    names = ("temperature against the proposed -60 to 60", "humidity against the proposed 0 to 100")
    inside = findings()
    outside = findings(climate=CLIMATE.replace("15.00;60.00", "-140.00;101.50"))
    for name in names:
        assert inside[name].matches is True and inside[name].found.startswith("0 of 2 readings")
        assert outside[name].matches is False
        assert outside[name].found.startswith("1 of 2 readings outside, in 1 files")


def test_a_dust_row_with_p2_above_p1_differs():
    result = findings(dust=DUST.replace(";9.00;", ";13.00;"))
    assert result["Dust rows where P2 is above P1"].matches is False


def test_sensors_at_different_locations_differ():
    name = "Location id in the dust file and in the climate file"
    assert findings(climate=CLIMATE.replace(";5;", ";6;"))[name].matches is False


def test_live_timestamps_in_local_time_differ():
    name = "Newest live reading of the dust sensor, minutes before now in UTC"
    assert findings(live="2026-03-03T12:57:00")[name].matches is False  # an hour ahead of UTC
    assert findings(live="2026-03-03T10:57:00")[name].matches is False  # an hour behind


def test_dust_rows_of_another_day_differ():
    stale = DUST.replace("2026-03-01T23:58:00", "2026-03-02T00:01:00")
    assert findings(dust=stale)["Timestamps in the dust file"].matches is False


def test_a_day_kept_in_a_year_folder_is_checked_without_a_top_level_entry():
    old = findings(day=date(2025, 6, 1), dust=DUST.replace("2026-03-01", "2025-06-01"))
    name = "Last-Modified of the two files of 2025-06-01, and its folder in the listing"
    assert old[name].found.endswith("folder in a year folder")
    assert old["Timestamps in the dust file"].matches is True


def test_a_site_without_a_data_licence_link_differs():
    name = "Licence links on the Sensor.Community site"
    assert (
        findings(page=PAGE.replace("opendatacommons.org/licenses/dbcl", "x.org"))[name].matches
        is False
    )
    assert licence_links(PAGE) == [
        "Firmware License -> https://www.gnu.org/licenses/gpl-3.0.en.html",
        "DB Contents License -> https://opendatacommons.org/licenses/dbcl/1-0/",
    ]
