-- A valid hour has no reason, and an invalid hour has one. Rows returned fail.
select datastream_key, hour_start
from {{ ref('hourly') }}
where is_valid = (invalid_reason is not null)
