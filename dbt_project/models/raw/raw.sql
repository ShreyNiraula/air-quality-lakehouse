-- Every row of every file version the pointer names, as one long table. The table is
-- incremental: a build reads only the versions it does not hold yet, and replaces all the rows
-- of their files, that is of their stations and days. `--full-refresh` reads every version.
-- Values are kept as the file writes them; the hourly model (task 1.12) judges them.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='file',
    on_schema_change='fail',
) }}

{%- set new_versions -%}
    select path from {{ ref('current_file') }} as current
    where current.source = 'openaq'
    {%- if is_incremental() %}
      and not exists (
          select 1 from {{ this }} as held
          where held.file = current.file and held.version = current.version
      )
    {%- endif %}
    order by path
{%- endset -%}
{%- set paths = run_query(new_versions).columns[0].values() if execute else [] %}

{%- if paths %}
select
    current.source,
    current.station_id,
    current.day,
    rows.sensors_id as sensor_id,
    rows.parameter,
    rows.units as unit,
    cast(rows.datetime as timestamptz) as stamped_at,
    rows.value,
    current.file,
    current.version
from read_csv(
    [{%- for path in paths %}'{{ path }}'{{ ', ' if not loop.last }}{% endfor -%}],
    compression = 'gzip',
    header = true,
    all_varchar = true,
    filename = true
) as rows
inner join {{ ref('current_file') }} as current on rows.filename = current.path
{%- else %}
-- No new version: an empty set of the same shape.
select
    cast(null as varchar) as source,
    cast(null as varchar) as station_id,
    cast(null as date) as day,
    cast(null as varchar) as sensor_id,
    cast(null as varchar) as parameter,
    cast(null as varchar) as unit,
    cast(null as timestamptz) as stamped_at,
    cast(null as varchar) as value,
    cast(null as varchar) as file,
    cast(null as varchar) as version
where false
{%- endif %}
