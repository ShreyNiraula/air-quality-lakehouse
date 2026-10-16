"""The backfill: one station's month is loaded, and running it again downloads nothing new.

The archive is played by the test data of January 2025, so no test reaches the network.
"""

import gzip
import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from airquality import openaq
from airquality.backfill import Step, backfill, main, sequencer
from airquality.storage import DirectoryStorage, SqlitePointer

STATION, MONTH = "3019", date(2025, 1, 1)
DAYS = openaq.days(MONTH)


class Archive:
    """The OpenAQ archive of one station, from the test data, counting its downloads."""

    def __init__(self, missing: tuple[date, ...] = ()):
        self.files = {
            day: (openaq.FIXTURES / openaq.key(STATION, day)).read_bytes()
            for day in DAYS
            if day not in missing
        }
        self.written = {day: datetime(2025, 2, 1, tzinfo=UTC) for day in self.files}
        self.downloads: list[date] = []
        self.fail_on: date | None = None

    def reissue(self, day: date, content: bytes) -> None:
        self.files[day] = content
        self.written[day] += timedelta(days=30)

    def find(self, station: str, month: date) -> dict[date, openaq.Listed]:
        assert (station, month) == (STATION, MONTH)
        return {
            day: openaq.Listed(
                openaq.key(station, day),
                hashlib.md5(content).hexdigest(),
                len(content),
                self.written[day],
            )
            for day, content in self.files.items()
        }

    def download(self, station: str, day: date) -> bytes | None:
        if day == self.fail_on:
            raise ConnectionError("the connection dropped")
        self.downloads.append(day)
        return self.files.get(day)


@pytest.fixture
def store(tmp_path):
    return DirectoryStorage(tmp_path), SqlitePointer(tmp_path / "pointer.sqlite")


def run(archive: Archive, store) -> list[Step]:
    storage, pointer = store
    return backfill(STATION, [MONTH], storage, pointer, archive.find, archive.download, pause=0)


def file(day: date) -> str:
    return f"openaq/{openaq.key(STATION, day)}"


def test_a_month_is_loaded_and_running_again_downloads_nothing_new(store):
    archive = Archive()
    steps = run(archive, store)
    assert steps == [Step(day, "downloaded", "validated") for day in DAYS]
    _, pointer = store
    assert sorted(pointer.entries()) == sorted(file(day) for day in DAYS)
    assert pointer.get(file(DAYS[0])).version == hashlib.sha256(archive.files[DAYS[0]]).hexdigest()

    archive.downloads.clear()
    assert run(archive, store) == [Step(day, "skipped") for day in DAYS]
    assert archive.downloads == []


def test_a_day_the_archive_does_not_hold_is_left_out(store):
    archive = Archive(missing=(date(2025, 1, 23),))
    steps = run(archive, store)
    assert len(steps) == 30 and date(2025, 1, 23) not in {step.day for step in steps}
    assert date(2025, 1, 23) not in archive.downloads


def test_a_run_that_stops_half_way_is_finished_by_the_next(store):
    archive = Archive()
    archive.fail_on = date(2025, 1, 10)
    with pytest.raises(ConnectionError):
        run(archive, store)
    assert len(archive.downloads) == 9

    archive.fail_on, archive.downloads = None, []
    steps = run(archive, store)
    assert [step.action for step in steps] == ["skipped"] * 9 + ["downloaded"] * 22
    assert archive.downloads == DAYS[9:]
    assert len(store[1].entries()) == 31


class FailingPointer:
    """A pointer that fails on one file, as when the process stops after the file is landed."""

    def __init__(self, pointer, fails_on: str):
        self.pointer, self.fails_on = pointer, fails_on

    def move(self, key, version, sequencer):
        if key == self.fails_on:
            raise ConnectionError("the pointer could not be reached")
        return self.pointer.move(key, version, sequencer)

    def get(self, key):
        return self.pointer.get(key)


def test_a_landed_file_that_was_not_ingested_is_ingested_without_downloading_it_again(store):
    storage, pointer = store
    archive = Archive()
    failing = FailingPointer(pointer, file(DAYS[4]))
    with pytest.raises(ConnectionError):
        backfill(STATION, [MONTH], storage, failing, archive.find, archive.download, pause=0)
    assert pointer.get(file(DAYS[4])) is None

    archive.downloads.clear()
    steps = run(archive, store)
    assert steps[4] == Step(DAYS[4], "resumed", "validated")
    assert archive.downloads == DAYS[5:]
    assert pointer.get(file(DAYS[4])) is not None


def test_a_reissued_file_is_downloaded_again_and_becomes_current(store):
    archive = Archive()
    run(archive, store)
    lines = gzip.decompress(archive.files[DAYS[2]]).decode().splitlines()
    shorter = gzip.compress(("\n".join(lines[:7]) + "\n").encode())
    archive.reissue(DAYS[2], shorter)

    archive.downloads.clear()
    steps = run(archive, store)
    assert archive.downloads == [DAYS[2]]
    assert steps[2] == Step(DAYS[2], "downloaded", "validated")
    assert store[1].get(file(DAYS[2])).version == hashlib.sha256(shorter).hexdigest()


def quarantined(archive: Archive) -> str:
    """Make the archive's first day a file with a header and no rows; return its quarantine key."""
    header = gzip.decompress(archive.files[DAYS[0]]).decode().splitlines()[0]
    archive.files[DAYS[0]] = gzip.compress(header.encode() + b"\n")
    return f"quarantine/{file(DAYS[0])}/{hashlib.sha256(archive.files[DAYS[0]]).hexdigest()}"


def test_a_quarantined_file_is_checked_again_from_landing_without_downloading_it(store):
    archive = Archive()
    quarantined(archive)
    assert run(archive, store)[0] == Step(DAYS[0], "downloaded", "quarantined")
    assert store[1].get(file(DAYS[0])) is None

    archive.downloads.clear()
    assert run(archive, store)[0] == Step(DAYS[0], "resumed", "quarantined")
    assert archive.downloads == []


def test_a_quarantine_left_without_its_reason_is_finished_by_the_next_run(store):
    storage, _ = store
    archive = Archive()
    key = quarantined(archive)
    run(archive, store)
    (storage.root / f"{key}.reasons").unlink()  # as if the run stopped before writing it

    run(archive, store)
    assert storage.read(f"{key}.reasons") == b"the file has a header and no rows"


def test_the_command_fails_while_a_day_is_quarantined(tmp_path, monkeypatch):
    archive = Archive()
    quarantined(archive)
    monkeypatch.setattr(openaq, "find", archive.find)
    monkeypatch.setattr(openaq, "download", archive.download)
    monkeypatch.setattr("airquality.backfill.PAUSE", 0)
    arguments = ["--station", STATION, "--month", "2025-01", "--store", str(tmp_path)]
    assert main(arguments) == 1
    assert main(arguments) == 1  # and again on the next run, though nothing is downloaded


def test_a_reissue_written_in_the_same_second_still_becomes_current(store):
    archive = Archive()
    run(archive, store)
    lines = gzip.decompress(archive.files[DAYS[2]]).decode().splitlines()
    shorter = gzip.compress(("\n".join(lines[:7]) + "\n").encode())
    archive.files[DAYS[2]] = shorter  # a new version, listed with the same time as the first

    steps = run(archive, store)
    assert steps[2] == Step(DAYS[2], "downloaded", "validated")
    assert store[1].get(file(DAYS[2])).version == hashlib.sha256(shorter).hexdigest()


def test_a_later_write_has_a_larger_sequencer():
    first = datetime(2025, 2, 1, tzinfo=UTC)
    earlier, later = sequencer(first), sequencer(first + timedelta(microseconds=1))
    assert len(earlier) < len(later) or (len(earlier) == len(later) and earlier < later)
    assert int(sequencer(first + timedelta(days=30)), 16) > int(earlier, 16)


def test_the_command_reports_each_day_and_the_totals(tmp_path, monkeypatch, capsys):
    archive = Archive()
    monkeypatch.setattr(openaq, "find", archive.find)
    monkeypatch.setattr(openaq, "download", archive.download)
    monkeypatch.setattr("airquality.backfill.PAUSE", 0)
    store = tmp_path / "a folder not made yet"
    arguments = ["--station", STATION, "--month", "2025-01", "--store", str(store)]
    assert main(arguments) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "31 downloaded, 0 resumed, 0 skipped"
    assert main(arguments) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "0 downloaded, 0 resumed, 31 skipped"
