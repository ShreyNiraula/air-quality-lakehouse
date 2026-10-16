-- The raw table holds exactly the file versions the pointer names: no row of an older version,
-- and every current file has its rows (a valid file has at least one). Rows returned fail.
(
    select distinct file, version, 'held but not current' as problem from {{ ref('raw') }}
    except
    select file, version, 'held but not current' from {{ ref('current_file') }}
)
union all
(
    select file, version, 'current but not held' from {{ ref('current_file') }}
    where source = 'openaq'
    except
    select distinct file, version, 'current but not held' from {{ ref('raw') }}
)
