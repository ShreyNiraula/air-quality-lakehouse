"""Task 1.5: check a delivered file against its source's contract, before it is stored.

    reasons = validate(content, station, day, contract)    # no reasons: the file is valid

The checks are about the file's shape only: it opens, its header is the contract's, it has
rows, every row is of the station and the day the file is named for, and the units pass the unit
rule. A value is never judged here. A reading out of range and a day with few hours are real
input, which the models count; a file that fails a check is quarantined with its reasons.
"""

import csv
import gzip
import io
import zlib
from datetime import date, datetime, timedelta

from airquality.contracts import Contract
from airquality.units import accepted, passes


def rows_of(content: bytes, contract: Contract) -> list[list[str]]:
    """The file as rows of texts, the header first. Raises ValueError if it does not open."""
    try:
        raw = gzip.decompress(content) if contract.format.endswith(".gz") else content
        # Strict: without it a quote that is never closed takes the rest of the file as one field.
        text = io.StringIO(raw.decode("utf-8"), newline="")
        return [row for row in csv.reader(text, strict=True) if row]
    except (OSError, EOFError, zlib.error, UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"the file does not open: {error}") from error


def validate(
    content: bytes,
    station: str,
    day: date,
    contract: Contract,
    units: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """Every reason why a file of `station` and `day` breaks its contract; none if it is valid.

    `units` are the unit texts that pass for each parameter, by default `accepted(contract)`.
    """
    units = accepted(contract) if units is None else units
    try:
        table = rows_of(content, contract)
    except ValueError as error:
        return [str(error)]
    if not table:
        return ["the file is empty"]
    if tuple(table[0]) != contract.fields:
        return [f"the header is {','.join(table[0])}, and not {','.join(contract.fields)}"]
    if len(table) == 1:
        return ["the file has a header and no rows"]
    role, period = contract.roles, timedelta(seconds=contract.seconds)
    called = {entry.name: parameter for parameter, entry in contract.parameters.items()}
    found: dict[str, tuple[int, str]] = {}  # each kind of fault: how many rows, and the first

    def fault(number: int, kind: str, first: str) -> None:
        count, example = found.get(kind, (0, f"row {number} {first}"))
        found[kind] = (count + 1, example)

    for number, texts in enumerate(table[1:], start=1):
        if len(texts) != len(contract.fields):
            fault(number, "the wrong number of fields", f"has {len(texts)} fields")
            continue
        row = dict(zip(contract.fields, texts, strict=True))
        time, unit = row[role["time"]], row[role["unit"]]
        if row[role["station"]] != station:
            fault(number, "another station", f"is of {row[role['station']]}, not {station}")
        try:
            stamp = datetime.fromisoformat(time)
        except ValueError:
            fault(number, "a time that cannot be read", f"has {time!r}")
        else:
            # The day is the one the period starts on, by the clock the timestamp itself names.
            start = (stamp - period if contract.marks == "end" else stamp).date()
            if stamp.tzinfo is None:
                fault(number, "a time with no UTC offset", f"has {time}")
            elif start != day:
                fault(number, "another day", f"is of {start}, not {day}")
        parameter = called.get(row[role["parameter"]])
        if parameter and not passes(unit, units[parameter]):
            fault(number, "a unit that does not pass", f"has {parameter} in {unit!r}")
    rows = len(table) - 1
    return [f"{kind} in {count} of {rows} rows: {first}" for kind, (count, first) in found.items()]
