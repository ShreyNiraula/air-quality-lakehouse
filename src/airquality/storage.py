"""Task 1.3: where the pipeline keeps files, and its record of which file version is current.

Two small interfaces, `Storage` and `Pointer`, with their local versions: files in a directory,
and the pointer in a SQLite file. Ingestion (task 1.6) uses only the interfaces, so the same
function runs on AWS with the S3 and DynamoDB versions of task 5.4.

A file is delivered more than once, and its deliveries can arrive in any order. So a write that
is repeated must change nothing, and the pointer only ever moves forward.
"""

import contextlib
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SEQUENCER = re.compile(r"[0-9A-F]{1,32}")
WIDTH = 32  # every sequencer is stored at this length, so that text order is their order


class Storage(Protocol):
    """Files under keys like `validated/<file>/<sha256>`. Writing a key again replaces it."""

    def write(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes:
        """The file's content. A key with no file raises KeyError."""
        ...

    def exists(self, key: str) -> bool: ...


@dataclass(frozen=True)
class Current:
    """What the pointer says of one file: its current version, and the event that set it."""

    version: str  # the content's SHA-256
    sequencer: str  # as stored: in capitals, at full length


class Pointer(Protocol):
    """Which version of each file is current. Readers use only the versions it names."""

    def move(self, key: str, version: str, sequencer: str) -> bool:
        """Name `version` as current, unless an event at least as new has already been applied.

        Returns whether the pointer moved. A sequencer orders the events of one file, as S3's
        does: a hexadecimal number as text, and the larger one is the newer event.
        """
        ...

    def get(self, key: str) -> Current | None: ...

    def entries(self) -> dict[str, Current]:
        """Every file that has a pointer."""
        ...


def padded(sequencer: str) -> str:
    """A sequencer at full length. S3 says to pad on the left before comparing two of them."""
    if not SEQUENCER.fullmatch(sequencer.upper()):
        raise ValueError(
            f"not a sequencer, which is 1 to {WIDTH} hexadecimal digits: {sequencer!r}"
        )
    return sequencer.upper().rjust(WIDTH, "0")


class DirectoryStorage:
    """`Storage` in a directory: a key is a path below it."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not key or key.endswith("/") or self.root not in path.parents:
            raise ValueError(f"not a key below the storage directory: {key!r}")
        return path

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside its place and then moved there in one step, so a reader sees the whole
        # file or none of it, and a write that fails half way leaves what was there.
        handle, part = tempfile.mkstemp(dir=path.parent, prefix=".part-")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            os.replace(part, path)
        except BaseException:
            Path(part).unlink(missing_ok=True)
            raise

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise KeyError(key) from None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class SqlitePointer:
    """`Pointer` in a SQLite file, the owner's choice of 7 October 2026."""

    def __init__(self, database: Path):
        self.database = Path(database)
        self._run(
            "CREATE TABLE IF NOT EXISTS pointer ("
            "key TEXT PRIMARY KEY, version TEXT NOT NULL, sequencer TEXT NOT NULL)"
        )

    def _run(self, sql: str, *values: str) -> tuple[list[tuple], int]:
        """One statement in its own transaction: its rows, and how many rows it changed."""
        with contextlib.closing(sqlite3.connect(self.database, timeout=30)) as con, con:
            done = con.execute(sql, values)
            return done.fetchall(), done.rowcount

    def move(self, key: str, version: str, sequencer: str) -> bool:
        if not (key and version):
            raise ValueError("a pointer needs the file's key and its version")
        # One statement, so that two events arriving together cannot both read the old pointer:
        # the row is written if there is none, and replaced only by a newer event.
        _, changed = self._run(
            "INSERT INTO pointer (key, version, sequencer) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET version = excluded.version, "
            "sequencer = excluded.sequencer WHERE excluded.sequencer > pointer.sequencer",
            key,
            version,
            padded(sequencer),
        )
        return changed == 1

    def get(self, key: str) -> Current | None:
        rows, _ = self._run("SELECT version, sequencer FROM pointer WHERE key = ?", key)
        return Current(*rows[0]) if rows else None

    def entries(self) -> dict[str, Current]:
        rows, _ = self._run("SELECT key, version, sequencer FROM pointer")
        return {key: Current(version, sequencer) for key, version, sequencer in rows}
