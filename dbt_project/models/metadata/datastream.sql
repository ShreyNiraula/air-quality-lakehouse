-- One row per sensor measuring one parameter at one station in one unit: SensorThings'
-- Datastream. The unit is the vocabulary's stored unit, which every reading is converted to.
select
    registry.source || '/' || registry.sensor_id || '/' || registry.parameter as datastream_key,
    registry.source || '/' || registry.station_id as station_key,
    registry.source || '/' || registry.sensor_id as sensor_key,
    registry.parameter,
    parameter.unit,
    registry.start_date
from {{ ref('registry') }} as registry
inner join {{ ref('parameter') }} as parameter on registry.parameter = parameter.parameter
