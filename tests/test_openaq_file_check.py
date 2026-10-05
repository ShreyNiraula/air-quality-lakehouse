"""The OpenAQ file check, on made-up files shaped like the real ones. No network is used."""

import gzip
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from airquality.checks.openaq_file import (
    check,
    hour_labels,
    in_station_time,
    lag_hours,
    parse_listing,
)

DAY = date(2026, 1, 10)
BERLIN = ZoneInfo("Europe/Berlin")  # UTC+1 in January
MICROGRAMS = "µg/m³"
LISTING = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
<Contents><Key>records/csv.gz/locationid=7/year=2026/month=01/location-7-20260109.csv.gz</Key>
<LastModified>2026-01-12T23:00:10.000Z</LastModified></Contents>
<Contents><Key>records/csv.gz/locationid=7/year=2026/month=01/location-7-20260110.csv.gz</Key>
<LastModified>2026-01-13T23:00:20.000Z</LastModified></Contents>
</ListBucketResult>"""


def day_file(first_hour=1, hours=24, unit=MICROGRAMS, header=None, offset="+01:00"):
    """A gzipped day file for one PM2.5 sensor in Berlin, with every field quoted as OpenAQ does."""
    names = "location_id,sensors_id,location,datetime,lat,lon,parameter,units,value".split(",")
    lines = [header or ",".join(f'"{name}"' for name in names)]
    start = datetime(DAY.year, DAY.month, DAY.day)
    for hour in range(first_hour, first_hour + hours):
        stamp = (start + timedelta(hours=hour)).isoformat() + offset
        lines.append(f'7,70,"Made up","{stamp}","1.0","2.0","pm25","{unit}","{hour}.5"')
    return gzip.compress("\n".join(lines).encode("utf-8"))


def findings(raw, now=datetime(2026, 1, 14, 12, tzinfo=UTC)):
    return {
        finding.name: finding for finding in check(DAY, raw, parse_listing(LISTING), now, BERLIN)
    }


def test_file_shaped_like_the_real_ones_matches_every_expectation():
    result = findings(day_file())
    assert [name for name, finding in result.items() if finding.matches is False] == []
    assert result["Header line as written"].found.startswith('"location_id","sensors_id"')


def test_hours_named_by_their_start_differ():
    result = findings(day_file(first_hour=0))
    assert result["Timestamps name each hour by its"].matches is False
    assert result["Field names"].matches is True


def test_another_unit_differs_before_and_after_normalizing():
    result = findings(day_file(unit="mg/m³"))
    assert result["PM2.5 unit text"].matches is False
    assert result["PM2.5 unit after NFKC, as the unit rule compares it"].matches is False


def test_renamed_field_or_empty_file_is_reported_and_ends_the_check():
    header = "location_id,sensor_id,location,datetime,lat,lon,parameter,units,value"
    renamed = findings(day_file(header=header))
    assert renamed["Field names"].matches is False
    assert "PM2.5 unit text" not in renamed
    empty = findings(day_file(hours=0))
    assert empty["Field names"].matches is True
    assert empty["Rows in the file"].matches is False


def test_half_hourly_rows_differ():
    lines = gzip.decompress(day_file(hours=2)).decode().splitlines()
    lines.insert(2, lines[1].replace("T01:00:00", "T01:30:00"))
    raw = gzip.compress("\n".join(lines).encode())
    assert findings(raw)["Usual time between rows of one sensor"].matches is False


def test_hour_labels_needs_a_boundary_hour_to_decide():
    at = [datetime(2026, 1, 10, hour) for hour in (5, 6)]
    assert hour_labels(DAY, at) == "unclear"
    assert hour_labels(DAY, [*at, datetime(2026, 1, 11, 0)]) == "end"
    assert hour_labels(DAY, [*at, datetime(2026, 1, 10, 0)]) == "start"
    assert hour_labels(DAY, [datetime(2026, 1, 10, 0), datetime(2026, 1, 11, 0)]) == "unclear"


def test_timestamps_in_another_zone_than_the_station_differ():
    name = "UTC offset of the timestamps, against Europe/Berlin at those times"
    assert findings(day_file())[name].matches is True
    assert findings(day_file(offset="+00:00"))[name].matches is False


def test_offsets_are_compared_timestamp_by_timestamp():
    # 29 March 2026 in Berlin: 01:30 is still UTC+1 and 03:30 is already UTC+2.
    right = ["2026-03-29T01:30+01:00", "2026-03-29T03:30+02:00"]
    swapped = ["2026-03-29T01:30+02:00", "2026-03-29T03:30+01:00"]
    assert in_station_time([datetime.fromisoformat(stamp) for stamp in right], BERLIN)
    assert not in_station_time([datetime.fromisoformat(stamp) for stamp in swapped], BERLIN)


def test_lag_is_counted_from_the_end_of_the_local_day():
    # The local day of 10 January at UTC+1 ends at 23:00 UTC; the listing says 72 hours later.
    lags = lag_hours(parse_listing(LISTING), BERLIN)
    assert [round(lag, 1) for lag in lags] == [72.0, 72.0]
    # Summer time starts in Berlin on 29 March 2026, so that local day ends at 22:00 UTC.
    across = {date(2026, 3, 27): datetime(2026, 3, 30, 23, tzinfo=UTC)}
    across[date(2026, 3, 29)] = datetime(2026, 4, 1, 22, tzinfo=UTC)
    assert lag_hours(across, BERLIN) == [72.0, 72.0]
    assert findings(day_file())[
        "Hours from the end of the local day until the file is written"
    ].found.startswith("median 72.0")


def test_days_past_the_lag_without_a_file_are_counted():
    late = findings(day_file(), now=datetime(2026, 1, 17, 12, tzinfo=UTC))
    assert "3 later days are due" in late["Newest day with a file"].found
    on_time = findings(day_file())
    assert "0 later days are due" in on_time["Newest day with a file"].found
