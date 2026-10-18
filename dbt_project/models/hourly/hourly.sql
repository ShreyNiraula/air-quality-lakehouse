-- One row per measurement stream (datastream) and hour, following the metric rules of plan.md:
-- only the sensor the registry pins for a station and parameter is read; an hour is named by
-- its start; identical duplicate rows count once; an hour is valid only if it has exactly one
-- distinct value, that value is a number, and it lies inside the parameter's valid range.
--
-- Incremental, like `raw`: a build first removes the hours of file versions that are no longer
-- current (pre_hook), then adds the hours of versions it does not hold yet. So a corrected file
-- replaces exactly its own station and day, even when the correction drops rows.
-- depends_on: {{ ref('current_file') }}
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    on_schema_change='fail',
    pre_hook="{% if is_incremental() %}
        delete from {{ this }} as held
        where not exists (
            select 1 from {{ ref('current_file') }} as current
            where current.file = held.file and current.version = held.version
        )
    {% endif %}",
) }}

with readings as (
    select
        registry.source || '/' || registry.sensor_id || '/' || registry.parameter as datastream_key,
        raw.source,
        raw.station_id,
        raw.sensor_id,
        registry.parameter,
        -- The source's time convention, from its contract: OpenAQ stamps an hour with its end.
        case raw.source when 'openaq' then raw.stamped_at - interval 1 hour end as hour_start,
        trim(raw.value) as value_text,
        try_cast(trim(raw.value) as double) as value_number,
        raw.file,
        raw.version
    from {{ ref('raw') }} as raw
    inner join {{ ref('registry') }} as registry
        on raw.source = registry.source
        and raw.station_id = registry.station_id
        and raw.sensor_id = registry.sensor_id
        -- and the line must be of that parameter. OpenAQ names its parameters as the vocabulary
        -- does (contracts/openaq.yml: pm25 is called pm25); tests/test_hourly.py checks that.
        and raw.parameter = registry.parameter
    {% if is_incremental() %}
    where not exists (
        select 1 from {{ this }} as held
        where held.file = raw.file and held.version = raw.version
    )
    {% endif %}
),

hours as (
    select
        datastream_key,
        source,
        station_id,
        sensor_id,
        parameter,
        hour_start,
        count(*) as rows_found,
        -- distinct values: numbers compared as numbers, anything else as text
        count(distinct value_number)
            + count(distinct case when value_number is null then value_text end) as distinct_values,
        count(*) filter (where value_number is null) as rows_not_a_number,
        min(value_number) as value_number,
        any_value(file) as file,
        any_value(version) as version
    from readings
    group by all
)

select
    hours.datastream_key,
    hours.source,
    hours.station_id,
    hours.sensor_id,
    hours.parameter,
    hours.hour_start,
    case when hours.distinct_values = 1 then hours.value_number end as value,
    hours.distinct_values = 1
        and hours.rows_not_a_number = 0
        and hours.value_number between parameter.valid_min and parameter.valid_max as is_valid,
    case
        when hours.distinct_values > 1 then 'conflicting values'
        when hours.rows_not_a_number > 0 then 'not a number'
        when hours.value_number not between parameter.valid_min and parameter.valid_max
            then 'out of range'
    end as invalid_reason,
    cast(hours.rows_found as integer) as rows_found,
    hours.file,
    hours.version
from hours
inner join {{ ref('parameter') }} as parameter on hours.parameter = parameter.parameter
