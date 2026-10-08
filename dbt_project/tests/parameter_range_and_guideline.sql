-- A parameter's valid range must have room in it. A guideline has both its value and its name or
-- neither, and its value lies inside the valid range. The rows returned are the ones that fail.
select parameter
from {{ ref('parameter') }}
where not (valid_min < valid_max)
   or (guideline_value is null) <> (guideline_name is null)
   or guideline_value not between valid_min and valid_max
