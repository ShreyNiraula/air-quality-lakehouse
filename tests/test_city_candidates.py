"""The city candidates script, on made-up monitors and boxes shaped like the real ones."""

from datetime import UTC, datetime

from airquality.checks import city_candidates
from airquality.checks.city_candidates import boxes, cities, label, monitors, pairs

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
FRESH = {"lastMeasurement": {"createdAt": "2026-10-05T00:00:00.000Z"}}


def monitor(id=1, lat=52.5, lon=13.4, first="2020-01-01", last="2026-10-05", also=(), **more):
    return {
        "id": id,
        "name": f"Station {id}",
        "locality": "10115 berlin",
        "country": {"code": "DE"},
        "coordinates": {"latitude": lat, "longitude": lon},
        "datetimeFirst": {"utc": f"{first}T00:00:00Z"},
        "datetimeLast": {"utc": f"{last}T00:00:00Z"},
        "sensors": [{"parameter": {"name": name}} for name in ["pm25", *also]],
    } | more


def box(id="a", lat=52.5, lon=13.4, created="2024-06-01", last="2026-10-05", **more):
    dust = {"lastMeasurement": {"createdAt": f"{last}T00:00:00.000Z"}}
    return {
        "_id": id * 24,
        "name": f"Box {id}",
        "exposure": "outdoor",
        "createdAt": f"{created}T00:00:00.000Z",
        "currentLocation": {"coordinates": [lon, lat]},  # openSenseMap puts longitude first
        "sensors": [
            {"_id": f"{id}-pm25", "title": "PM2.5", "unit": "µg/m³"} | dust,
            {"_id": f"{id}-temp", "title": "Temperatur", "unit": "°C"} | FRESH,
        ],
    } | more


def test_a_monitor_counts_only_if_it_started_by_2025_and_reported_recently():
    listed = [
        monitor(1, also=["temperature", "relativehumidity"]),
        monitor(2, first="2025-01-01"),  # started on the first day of the period
        monitor(3, first="2025-01-02"),
        monitor(4, last="2026-09-01"),  # stopped more than 30 days ago
        monitor(5, datetimeLast=None),
        monitor(6, coordinates={"latitude": None, "longitude": None}),
        monitor(7, locality="None"),  # OpenAQ writes the word for some places
    ]
    kept = monitors(listed, NOW)
    assert [place.id for place in kept] == ["1", "2", "7"]
    assert (kept[0].city, kept[0].also) == ("Berlin, DE", "relativehumidity and temperature")
    assert (kept[2].city, kept[2].also) == ("Station 7, DE", "neither")


def test_a_monitor_is_kept_only_if_its_pm25_sensor_itself_reported_throughout():
    def sensor(name, first="2020-01-01", last="2026-10-05"):
        return monitor(first=first, last=last) | {"parameter": {"name": name}}

    kept = city_candidates.pm25_throughout
    assert kept([sensor("no2"), sensor("pm25")], NOW)
    assert not kept([sensor("no2"), sensor("pm25", first="2025-06-01")], NOW)  # added later
    assert not kept([sensor("no2"), sensor("pm25", last="2026-08-01")], NOW)  # stopped
    assert not kept([sensor("no2")], NOW)


def test_a_box_counts_only_if_it_is_outdoor_and_its_pm25_sensor_reported_throughout():
    listed = [
        box("a"),
        box("b", exposure="indoor"),
        box("c", sensors=[{"_id": "c-pm10", "title": "PM10", "unit": "µg/m³"} | FRESH]),
        box("d", created="2025-01-01"),  # made on the first day of the period
        box("e", created="2025-01-02"),
        box("f", last="2026-08-01"),  # its temperature sensor still reports, its PM2.5 does not
        box("0", currentLocation=None),
        box("1", sensors=[{"_id": "1-pm25", "title": "PM2.5", "unit": "µg/m³"}]),  # never read
    ]
    kept = boxes(listed, NOW)
    assert [(place.id[0], place.lat, place.lon) for place in kept] == [
        ("a", 52.5, 13.4),
        ("d", 52.5, 13.4),
    ]
    assert kept[0].pm25 == ("a-pm25",)


def test_pairs_are_within_the_radius_and_grouped_into_cities():
    reference = monitors([monitor(1), monitor(2, lat=52.55), monitor(3, lat=48.1, lon=11.6)], NOW)
    listed = [
        box("a", lat=52.504),  # 0.44 km from monitor 1
        box("b", lat=52.5, lon=13.41),  # 0.68 km from monitor 1
        box("c", lat=52.52),  # 2.2 km from monitor 1: too far
        box("d", lat=52.551),  # 0.11 km from monitor 2, which is 5.6 km from monitor 1
        box("e", lat=48.1, lon=11.6),  # at monitor 3, in another city
    ]
    low_cost = boxes(listed, NOW)
    found = pairs(reference, low_cost, 1.0)
    near = sorted((p.monitor.id, p.box.id[0], round(p.km, 2)) for p in found)
    assert near == [("1", "a", 0.44), ("1", "b", 0.68), ("2", "d", 0.11), ("3", "e", 0.0)]
    assert len(pairs(reference, low_cost, 2.5)) == 5
    groups = cities(found)
    assert [(label(g), len(g)) for g in groups] == [("Berlin, DE", 3), ("Berlin, DE", 1)]
    lines = city_candidates.report(groups, {"1": 6, "a" * 24: 7}, 8)
    assert lines[1].split() == ["3", "3", "2", "neither", "Berlin,", "DE"]
    assert lines[3:5] == ["", "Berlin, DE: 3 pairs"]  # the city with one pair gets no detail
    assert lines[5:7] == [
        "  0.44 km  monitor 1 Station 1: PM2.5 on 6 of 8 sample days; also measures neither",
        "           box " + "a" * 24 + " Box a: PM2.5 on 7 of 8 sample days",
    ]
    assert len(lines) == 11


def test_a_city_never_spans_more_than_20_km():
    spots = [52.0, 52.135, 52.27]  # 15 km apart: the first and the last are 30 km apart
    reference = monitors([monitor(n, lat=lat) for n, lat in enumerate(spots)], NOW)
    low_cost = boxes([box("abc"[n], lat=lat) for n, lat in enumerate(spots)], NOW)
    assert [len(group) for group in cities(pairs(reference, low_cost, 1.0))] == [2, 1]
