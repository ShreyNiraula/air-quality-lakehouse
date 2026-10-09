-- One row per monitoring site: OGC SensorThings' Thing with its Location. The registry repeats a
-- station on each of its rows, one per parameter; a station whose rows disagree gives two rows
-- here, which the uniqueness test of schema.yml refuses.
select distinct
    source || '/' || station_id as station_key,
    source,
    station_id,
    station_name,
    city,
    latitude,
    longitude,
    timezone,
    provider,
    licence,
    credit
from {{ ref('registry') }}
