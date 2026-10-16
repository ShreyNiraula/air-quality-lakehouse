-- One row per device: SensorThings' Sensor. Its type follows from its source: OpenAQ's archive
-- holds regulatory monitors. A source with no type here fails the not_null test of schema.yml.
select distinct
    source || '/' || sensor_id as sensor_key,
    source,
    sensor_id,
    source || '/' || station_id as station_key,
    case source when 'openaq' then 'reference monitor' end as sensor_type
from {{ ref('registry') }}
