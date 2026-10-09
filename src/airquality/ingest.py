"""Task 1.6: take in one delivered file. Validate it, store it, and move its pointer.

    outcome = ingest(event, storage, pointer)

A source delivers a file by writing it under `landing/<source>/<the key the source gives it>`,
and the write raises an event. The event names the landing key, the MD5 of what was written,
and a sequencer that orders the events of that key, as an S3 notification does. Ingestion does,
in this order (`plan.md`, "Ingestion contract"):

1. Read the landing file. If it is gone, or no longer the content the event names, a newer
   delivery has overwritten it, and that delivery's own event will follow: stop.
2. Validate it against its source's contract (task 1.5).
3. Write it to `validated/<file>/<sha256>`, or to `quarantine/<file>/<sha256>` with a
   `.reasons` file beside it. The same content always goes to the same place, so a retry
   overwrites it with the same bytes.
4. For a valid file only, move the file's pointer to that version, unless a newer event
   already has.

A failure anywhere leaves at most a stored version that the pointer does not name, which no
reader uses; running the same event again finishes the work.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from airquality import contracts, openaq
from airquality.storage import Pointer, Storage
from airquality.validation import validate

LANDING = "landing/"
# For each source: the station and day its key names, and the key it gives a station and day.
KEYS: dict[str, tuple[Callable[[str], tuple[str, date]], Callable[[str, date], str]]] = {
    "openaq": (openaq.named, openaq.key)
}


@dataclass(frozen=True)
class Event:
    """A file written under `landing/`, as its notification describes it."""

    key: str  # the landing key: landing/<source>/<the source's key>
    md5: str  # the MD5 of the content written, in hexadecimal: S3's ETag of a simple upload
    sequencer: str  # hexadecimal; a later write of the same key has a larger one


@dataclass(frozen=True)
class Outcome:
    status: str  # "validated", "quarantined", or "overwritten" when nothing was done
    file: str = ""  # the pointer's key: the landing key without `landing/`
    version: str = ""  # the content's SHA-256
    moved: bool = False  # whether the pointer now names this version because of this event
    reasons: tuple[str, ...] = ()  # why the file was quarantined


def reasons_of(source: str, name: str, content: bytes) -> list[str]:
    """Why a delivered file is not valid; none if it is."""
    if source not in KEYS:
        return [f"no source is called {source!r}"]
    named, key = KEYS[source]
    try:
        station, day = named(name)
    except ValueError as error:
        return [str(error)]
    # The whole key, folders included, must be the one the source gives that station and day.
    if name != key(station, day):
        return [f"the key is {name}, and not {key(station, day)}"]
    return validate(content, station, day, contracts.load(source))


def ingest(event: Event, storage: Storage, pointer: Pointer) -> Outcome:
    if not event.key.startswith(LANDING):
        raise ValueError(f"not a key under {LANDING}: {event.key!r}")
    try:
        content = storage.read(event.key)
    except KeyError:
        return Outcome("overwritten")
    if hashlib.md5(content).hexdigest() != event.md5.strip('"').lower():
        return Outcome("overwritten")

    file = event.key.removeprefix(LANDING)
    source, _, name = file.partition("/")
    version = hashlib.sha256(content).hexdigest()
    reasons = reasons_of(source, name, content)
    if reasons:
        storage.write(f"quarantine/{file}/{version}", content)
        storage.write(f"quarantine/{file}/{version}.reasons", "\n".join(reasons).encode())
        return Outcome("quarantined", file, version, reasons=tuple(reasons))
    storage.write(f"validated/{file}/{version}", content)
    moved = pointer.move(file, version, event.sequencer)
    return Outcome("validated", file, version, moved)
