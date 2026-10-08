"""The storage and the pointer: a repeated write is harmless, and the pointer never moves back.

The tests that take `storage` or `pointer` test the interface, not the local version: task 5.4
runs them against the S3 and DynamoDB versions by adding those to the two fixtures.
"""

import random
import threading

import pytest

from airquality.storage import Current, DirectoryStorage, SqlitePointer, padded

KEY, OLD, NEW = "landing/openaq/location-3019-20250101.csv.gz", "a" * 64, "b" * 64


@pytest.fixture
def storage(tmp_path):
    return DirectoryStorage(tmp_path / "files")


@pytest.fixture
def pointer(tmp_path):
    return SqlitePointer(tmp_path / "pointer.sqlite")


def test_a_file_that_is_written_can_be_read(storage):
    assert not storage.exists(f"validated/{KEY}/{OLD}")
    storage.write(f"validated/{KEY}/{OLD}", b"one day of readings")
    assert storage.exists(f"validated/{KEY}/{OLD}")
    assert storage.read(f"validated/{KEY}/{OLD}") == b"one day of readings"
    assert not storage.exists(f"validated/{KEY}") and not storage.exists(f"validated/{KEY}/{NEW}")


def test_a_duplicate_write_is_harmless(storage, tmp_path):
    for _ in range(2):
        storage.write(f"validated/{KEY}/{OLD}", b"one day of readings")
    assert storage.read(f"validated/{KEY}/{OLD}") == b"one day of readings"
    assert [path.name for path in (tmp_path / "files").rglob("*") if path.is_file()] == [OLD]


def test_a_file_delivered_again_replaces_the_one_before(storage):
    storage.write(KEY, b"the first delivery")
    storage.write(KEY, b"the second")
    assert storage.read(KEY) == b"the second"


def test_a_file_that_is_not_there_is_a_key_error(storage):
    storage.write(f"validated/{KEY}/{OLD}", b"one day of readings")
    for missing in ("validated/nothing", f"validated/{KEY}", f"validated/{KEY}/{OLD}/below"):
        with pytest.raises(KeyError):
            storage.read(missing)


@pytest.mark.parametrize("key", ["", "..", "../outside", "/etc/hosts", "validated/../..", "a/"])
def test_a_key_outside_the_directory_is_refused(storage, key, tmp_path):
    uses = (
        lambda: storage.write(key, b"x"),
        lambda: storage.read(key),
        lambda: storage.exists(key),
    )
    for use in uses:
        with pytest.raises(ValueError, match="not a key"):
            use()
    assert [path.name for path in tmp_path.rglob("*")] == []


def test_a_write_that_fails_leaves_the_file_that_was_there(storage, tmp_path, monkeypatch):
    storage.write(KEY, b"the first delivery")

    def fail(*_):
        raise OSError("the disk is full")

    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(OSError, match="disk is full"):
        storage.write(KEY, b"the second")
    monkeypatch.undo()
    assert storage.read(KEY) == b"the first delivery"
    assert len([path for path in (tmp_path / "files").rglob("*") if path.is_file()]) == 1


def test_the_first_event_sets_the_pointer_and_a_newer_one_moves_it(pointer):
    assert pointer.get(KEY) is None and pointer.entries() == {}
    assert pointer.move(KEY, OLD, "0055AED6DCD90281E5") is True
    assert pointer.get(KEY) == Current(OLD, padded("0055AED6DCD90281E5"))
    assert pointer.move(KEY, NEW, "0055AED6DCD90281E6") is True
    assert pointer.get(KEY).version == NEW


def test_an_older_event_cannot_move_the_pointer_back(pointer):
    pointer.move(KEY, NEW, "0055AED6DCD90281E6")
    assert pointer.move(KEY, OLD, "0055AED6DCD90281E5") is False
    assert pointer.get(KEY) == Current(NEW, padded("0055AED6DCD90281E6"))


def test_a_duplicate_event_changes_nothing(pointer):
    assert pointer.move(KEY, OLD, "0055AED6DCD90281E5") is True
    assert pointer.move(KEY, OLD, "0055AED6DCD90281E5") is False
    assert pointer.move(KEY, NEW, "0055aed6dcd90281e5") is False  # the same event, in small letters
    assert pointer.entries() == {KEY: Current(OLD, padded("0055AED6DCD90281E5"))}


def test_sequencers_are_compared_as_numbers_whatever_their_length(pointer):
    assert pointer.move(KEY, OLD, "FF") is True
    assert pointer.move(KEY, NEW, "100") is True  # as plain text, "100" sorts before "FF"
    assert pointer.move(KEY, OLD, "00FF") is False
    assert pointer.get(KEY).version == NEW


def test_each_file_has_its_own_pointer(pointer):
    pointer.move(KEY, NEW, "9")
    assert pointer.move("landing/another", OLD, "1") is True
    assert {key: now.version for key, now in pointer.entries().items()} == {
        KEY: NEW,
        "landing/another": OLD,
    }


@pytest.mark.parametrize(
    ("key", "version", "sequencer"),
    [("", OLD, "1"), (KEY, "", "1"), (KEY, OLD, ""), (KEY, OLD, "12G4"), (KEY, OLD, "1" * 33)],
)
def test_an_event_that_cannot_be_ordered_is_refused(pointer, key, version, sequencer):
    with pytest.raises(ValueError):
        pointer.move(key, version, sequencer)
    assert pointer.entries() == {}


def test_events_that_arrive_together_leave_the_newest(pointer):
    events = [f"{number:X}" for number in range(1, 201)]
    random.Random(7).shuffle(events)

    def deliver(mine):
        for sequencer in mine:
            pointer.move(KEY, f"version-{sequencer}", sequencer)

    threads = [threading.Thread(target=deliver, args=(events[n::4],)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert pointer.get(KEY) == Current("version-C8", padded("C8"))


def test_the_local_pointer_is_kept_in_its_file(tmp_path):
    SqlitePointer(tmp_path / "pointer.sqlite").move(KEY, OLD, "1")
    assert SqlitePointer(tmp_path / "pointer.sqlite").get(KEY).version == OLD
