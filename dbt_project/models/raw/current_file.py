"""The file versions the pointer names: the only ones readers use (plan.md, "Ingestion contract").

One row per file, with its station and day and the path of its validated copy in the store. The
store is the folder that ingestion (task 1.6) writes to, with the pointer's SQLite file in it.
"""

from pathlib import Path

from airquality.ingest import KEYS
from airquality.storage import SqlitePointer

COLUMNS = (
    "file varchar, version varchar, source varchar, station_id varchar, day date, path varchar"
)


def model(dbt, session):
    store = Path(dbt.config.get("store")).resolve()
    rows = []
    if (store / "pointer.sqlite").is_file():
        for file, current in sorted(SqlitePointer(store / "pointer.sqlite").entries().items()):
            source, _, name = file.partition("/")
            station, day = KEYS[source][0](name)
            path = store / "validated" / file / current.version
            rows.append((file, current.version, source, station, day, str(path)))
    session.execute(f"CREATE OR REPLACE TEMP TABLE current_file_rows ({COLUMNS})")
    if rows:
        session.executemany("INSERT INTO current_file_rows VALUES (?, ?, ?, ?, ?, ?)", rows)
    return session.sql("SELECT * FROM current_file_rows")
