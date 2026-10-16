"""The ingest function, and the four ingestion tests listed under "Publish gate" in `plan.md`:
a duplicate event, a broken newer version, a stale replay, and a failure between the write and
the pointer move.
"""

import gzip
import hashlib
from datetime import date

import pytest

from airquality import openaq
from airquality.ingest import Event, Outcome, ingest
from airquality.storage import Current, DirectoryStorage, SqlitePointer

STATION, DAY = "3019", date(2025, 1, 1)
FILE = f"openaq/{openaq.key(STATION, DAY)}"
LANDING = f"landing/{FILE}"
REAL = (openaq.FIXTURES / openaq.key(STATION, DAY)).read_bytes()
LINES = gzip.decompress(REAL).decode("utf-8").splitlines()
SHORT = gzip.compress(("\n".join(LINES[:7]) + "\n").encode())  # a valid re-issue: six rows
BROKEN = gzip.compress(LINES[0].encode() + b"\n")  # a header and no rows


@pytest.fixture
def storage(tmp_path):
    return DirectoryStorage(tmp_path / "files")


@pytest.fixture
def pointer(tmp_path):
    return SqlitePointer(tmp_path / "pointer.sqlite")


def deliver(storage, content: bytes, sequencer: str, key: str = LANDING) -> Event:
    """Write a file under landing/, as a source does, and return the event that write raises."""
    storage.write(key, content)
    return Event(key, hashlib.md5(content).hexdigest(), sequencer)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def stored(tmp_path) -> list[str]:
    """Every stored file outside landing/, by key."""
    root = tmp_path / "files"
    keys = (path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    return sorted(key for key in keys if not key.startswith("landing/"))


def test_a_valid_file_is_stored_under_its_hash_and_the_pointer_names_it(storage, pointer, tmp_path):
    outcome = ingest(deliver(storage, REAL, "0A"), storage, pointer)
    assert outcome == Outcome("validated", FILE, sha(REAL), moved=True)
    assert stored(tmp_path) == [f"validated/{FILE}/{sha(REAL)}"]
    assert storage.read(f"validated/{FILE}/{sha(REAL)}") == REAL
    assert pointer.get(FILE).version == sha(REAL)


def test_a_duplicate_event_gives_one_pointer_and_one_object(storage, pointer, tmp_path):
    event = deliver(storage, REAL, "0A")
    first, again = ingest(event, storage, pointer), ingest(event, storage, pointer)
    assert first.moved and again == Outcome("validated", FILE, sha(REAL), moved=False)
    assert stored(tmp_path) == [f"validated/{FILE}/{sha(REAL)}"]
    assert list(pointer.entries()) == [FILE] and pointer.get(FILE).version == sha(REAL)


def test_a_broken_newer_version_is_quarantined_and_the_pointer_stays(storage, pointer, tmp_path):
    ingest(deliver(storage, REAL, "0A"), storage, pointer)
    outcome = ingest(deliver(storage, BROKEN, "0B"), storage, pointer)
    assert outcome == Outcome(
        "quarantined", FILE, sha(BROKEN), reasons=("the file has a header and no rows",)
    )
    assert pointer.get(FILE).version == sha(REAL)
    assert stored(tmp_path) == [
        f"quarantine/{FILE}/{sha(BROKEN)}",
        f"quarantine/{FILE}/{sha(BROKEN)}.reasons",
        f"validated/{FILE}/{sha(REAL)}",
    ]
    assert storage.read(f"quarantine/{FILE}/{sha(BROKEN)}") == BROKEN
    assert storage.read(f"quarantine/{FILE}/{sha(BROKEN)}.reasons") == outcome.reasons[0].encode()


def test_a_stale_event_replayed_later_does_not_move_the_pointer_back(storage, pointer, tmp_path):
    old = deliver(storage, REAL, "0A")
    ingest(old, storage, pointer)
    ingest(deliver(storage, SHORT, "0B"), storage, pointer)
    # The landing file is now the newer version, so the old event no longer describes it.
    assert ingest(old, storage, pointer) == Outcome("overwritten")
    # An older event of the same content as the landing file reaches the pointer, which refuses.
    stale = Event(LANDING, hashlib.md5(SHORT).hexdigest(), "09")
    assert ingest(stale, storage, pointer) == Outcome("validated", FILE, sha(SHORT), moved=False)
    assert pointer.get(FILE).version == sha(SHORT) and pointer.get(FILE).sequencer == "B"
    assert stored(tmp_path) == sorted(f"validated/{FILE}/{sha(c)}" for c in (REAL, SHORT))


@pytest.mark.parametrize(
    "deliveries",
    [((REAL, "0A"), (SHORT, "0B")), ((SHORT, "0B"), (REAL, "0A"))],
    ids=["older first", "newer first"],
)
def test_the_newer_event_wins_whichever_order_the_two_arrive_in(deliveries, storage, pointer):
    moved = [
        ingest(deliver(storage, content, sequencer), storage, pointer).moved
        for content, sequencer in deliveries
    ]
    # The newer one moves the pointer either way; the older one only if it came first.
    assert moved == ([True, True] if deliveries[0][1] == "0A" else [True, False])
    assert pointer.get(FILE) == Current(sha(SHORT), "B")


class FailingPointer:
    """A pointer whose first move fails, as when the process stops after the object is written."""

    def __init__(self, pointer):
        self.pointer, self.failed = pointer, False

    def move(self, key, version, sequencer):
        if not self.failed:
            self.failed = True
            raise ConnectionError("the pointer could not be reached")
        return self.pointer.move(key, version, sequencer)

    def get(self, key):
        return self.pointer.get(key)

    def entries(self):
        return self.pointer.entries()


def test_a_failure_between_the_write_and_the_pointer_move_is_repaired_by_a_retry(
    storage, pointer, tmp_path
):
    ingest(deliver(storage, REAL, "0A"), storage, pointer)
    event, failing = deliver(storage, SHORT, "0B"), FailingPointer(pointer)
    with pytest.raises(ConnectionError):
        ingest(event, storage, failing)
    # The new version is stored but not named, so readers still use the old one.
    assert f"validated/{FILE}/{sha(SHORT)}" in stored(tmp_path)
    assert pointer.get(FILE).version == sha(REAL)
    assert ingest(event, storage, failing) == Outcome("validated", FILE, sha(SHORT), moved=True)
    assert pointer.get(FILE).version == sha(SHORT)
    assert stored(tmp_path) == sorted(f"validated/{FILE}/{sha(c)}" for c in (REAL, SHORT))


def test_a_file_gone_from_landing_is_left_to_the_event_of_whatever_replaced_it(
    storage, pointer, tmp_path
):
    event = Event(LANDING, hashlib.md5(REAL).hexdigest(), "0A")
    assert ingest(event, storage, pointer) == Outcome("overwritten")
    assert stored(tmp_path) == [] and pointer.entries() == {}


def test_an_s3_etag_in_quotes_and_capitals_names_the_same_content(storage, pointer):
    storage.write(LANDING, REAL)
    event = Event(LANDING, f'"{hashlib.md5(REAL).hexdigest().upper()}"', "0A")
    assert ingest(event, storage, pointer).status == "validated"


def moved(old: str, new: str) -> str:
    """The real file's landing key, with one folder of it changed."""
    assert old in LANDING
    return LANDING.replace(old, new, 1)


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        (f"landing/openaq/{openaq.key('4762', DAY)}", "another station in 72 of 72 rows"),
        (f"landing/openaq/{openaq.key(STATION, date(2025, 1, 2))}", "another day in 72 of 72"),
        ("landing/openaq/elsewhere/day.csv.gz", "not the key of an OpenAQ day file"),
        (f"landing/nosuch/{openaq.key(STATION, DAY)}", "no source is called 'nosuch'"),
        (moved("locationid=3019", "locationid=4762"), "the key is records/csv.gz/locationid=4762"),
        (moved("year=2025", "year=2026"), "the key is records/csv.gz/locationid=3019/year=2026"),
        (moved("month=01", "month=02"), "the key is records/csv.gz/locationid=3019/year=2025/m"),
        (moved("records/", "copies/records/"), "the key is copies/records/"),
    ],
    ids=[
        *("another station's name", "another day's name", "a name not of a day", "no source"),
        *("another station's folder", "another year's folder", "another month's folder"),
        "another archive folder",
    ],
)
def test_a_file_under_a_name_that_does_not_fit_it_is_quarantined(key, reason, storage, pointer):
    outcome = ingest(deliver(storage, REAL, "0A", key), storage, pointer)
    assert outcome.status == "quarantined" and outcome.reasons[0].startswith(reason)
    assert pointer.entries() == {}


def test_a_key_outside_landing_is_refused(storage, pointer):
    with pytest.raises(ValueError, match="not a key under landing/"):
        ingest(Event(f"validated/{FILE}", "0" * 32, "0A"), storage, pointer)
