"""Task 1.9: load a station's history from the OpenAQ archive, one file at a time.

    uv run python -m airquality.backfill --station 3019 --month 2025-01 --store data

For each day of each month the archive lists, the file is downloaded into `landing/` and given
to `ingest` (task 1.6), exactly as a delivery would be. Downloads are spaced out to be polite to
the archive. A run can stop anywhere and be started again: a day whose listed version is already
in `landing/` is not downloaded again, and is skipped once the pointer names it.
"""

import argparse
import hashlib
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from airquality import openaq
from airquality.ingest import Event, ingest
from airquality.storage import Current, DirectoryStorage, Pointer, SqlitePointer, Storage

PAUSE = 1.0  # seconds between two downloads


@dataclass(frozen=True)
class Step:
    day: date
    action: str  # "downloaded", "resumed" (ingested again from landing/), or "skipped"
    status: str = ""  # what ingestion did: "validated", "quarantined" or "overwritten"


def sequencer(written: datetime) -> str:
    """An event's sequencer from when the archive wrote the file: a re-issue is written later."""
    return f"{round(written.timestamp() * 1_000_000):X}"


def newer(written: datetime, current: Current | None, version: str) -> str:
    """The sequencer for the archive's listed version of a file, whose pointer is `current`.

    The listing names the archive's latest version, so a version other than the current one
    must move the pointer. If the archive wrote both in the same second, the time alone would
    not order them, and the sequencer is set one past the current one.
    """
    listed = sequencer(written)
    if current is None or current.version == version:
        return listed
    if int(listed, 16) > int(current.sequencer, 16):
        return listed
    return f"{int(current.sequencer, 16) + 1:X}"


def backfill(
    station: str,
    months: list[date],
    storage: Storage,
    pointer: Pointer,
    find: Callable[[str, date], dict[date, openaq.Listed]] | None = None,
    download: Callable[[str, date], bytes | None] | None = None,
    pause: float | None = None,
) -> list[Step]:
    """Ingest every file the archive lists for `station` in `months`, oldest first.

    `find` and `download` default to the OpenAQ adapter's, and `pause` to PAUSE.
    """
    find, download = find or openaq.find, download or openaq.download
    pause = PAUSE if pause is None else pause
    steps = []
    for month in months:
        for day, listed in sorted(find(station, month).items()):
            landing, file = f"landing/openaq/{listed.key}", f"openaq/{listed.key}"
            content = storage.read(landing) if storage.exists(landing) else None
            if content is not None and hashlib.md5(content).hexdigest() == listed.md5:
                # Only a version the pointer names is skipped. Any other is ingested again from
                # landing/, which repairs an unfinished quarantine and reports it again.
                current = pointer.get(file)
                if current is not None and current.version == hashlib.sha256(content).hexdigest():
                    steps.append(Step(day, "skipped"))
                    continue
                action = "resumed"
            else:
                time.sleep(pause)
                content = download(station, day)
                if content is None:  # gone from the archive since it was listed
                    continue
                storage.write(landing, content)
                action = "downloaded"
            version = hashlib.sha256(content).hexdigest()
            order = newer(listed.written, pointer.get(file), version)
            event = Event(landing, hashlib.md5(content).hexdigest(), order)
            steps.append(Step(day, action, ingest(event, storage, pointer).status))
    return steps


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", required=True, help="the OpenAQ location id, like 3019")
    parser.add_argument(
        "--month",
        required=True,
        action="append",
        type=lambda text: date.fromisoformat(f"{text}-01"),
        help="a month to load, like 2025-01; give it more than once for several",
    )
    parser.add_argument("--store", type=Path, required=True, help="the folder of the files")
    args = parser.parse_args(arguments)
    args.store.mkdir(parents=True, exist_ok=True)
    storage = DirectoryStorage(args.store)
    pointer = SqlitePointer(args.store / "pointer.sqlite")
    steps = backfill(args.station, args.month, storage, pointer)
    for step in steps:
        print(f"{args.station} {step.day}: {step.action} {step.status}".rstrip())
    counts = {
        action: sum(s.action == action for s in steps) for action in ("downloaded", "resumed")
    }
    skipped = len(steps) - sum(counts.values())
    print(f"{counts['downloaded']} downloaded, {counts['resumed']} resumed, {skipped} skipped")
    return 1 if any(step.status == "quarantined" for step in steps) else 0


if __name__ == "__main__":
    sys.exit(main())
