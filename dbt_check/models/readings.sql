-- The one model of the check. A build replaces the rows that have the same id, so building twice
-- leaves two rows. The check script also builds it as a table and as a view, under other names,
-- to record what the Iceberg catalog refuses.
{{ config(
    materialized=var('as', 'incremental'),
    alias=var('named', 'readings'),
    unique_key='id',
    incremental_strategy='delete+insert',
) }}
select 1 as id, 'pm25' as parameter, 7.5 as value
union all
select 2 as id, 'pm25' as parameter, 9.0 as value
