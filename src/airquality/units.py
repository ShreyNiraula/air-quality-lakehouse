"""Task 1.4: the unit rule. A unit text is cleaned and must then be one the parameter accepts.

A source writes the same unit in more than one way: OpenAQ's files say `µg/m³`, with a micro
sign and a raised 3, for what the vocabulary stores as `ug/m3`. So the text is cleaned first,
and then it must equal the parameter's own unit or a spelling the source's contract lists.
Nothing is converted: a text that names another unit does not pass.

    from airquality.units import accepted, passes
    passes("µg/m³", accepted(load("openaq"))["pm25"])    # True
"""

import csv
import unicodedata

from airquality.contracts import Contract
from airquality.registry import SEEDS


def clean(text: str) -> str:
    """A unit text without the spaces around it, and with look-alike characters made one.

    Unicode's NFKC form turns the micro sign `µ` into the Greek letter `μ`, and a raised `³`
    into a plain `3`.
    """
    return unicodedata.normalize("NFKC", text.strip())


def stored_units() -> dict[str, str]:
    """The unit of each parameter of the vocabulary, the seed `parameter.csv`."""
    with open(SEEDS / "parameter.csv", newline="", encoding="utf-8") as table:
        return {row["parameter"]: row["unit"] for row in csv.DictReader(table)}


def accepted(contract: Contract, stored: dict[str, str] | None = None) -> dict[str, frozenset[str]]:
    """For each parameter a source delivers, every cleaned unit text that passes.

    That is the parameter's own unit and the spellings the contract lists. A contract that maps
    a parameter the vocabulary does not have is refused.
    """
    stored = stored_units() if stored is None else stored
    if unknown := sorted(set(contract.parameters) - set(stored)):
        raise ValueError(
            f"{contract.source}: the vocabulary has no parameter {', '.join(unknown)}; "
            f"it has {', '.join(sorted(stored))}"
        )
    return {
        parameter: frozenset(map(clean, (stored[parameter], *entry.units)))
        for parameter, entry in contract.parameters.items()
    }


def passes(text: str, units: frozenset[str]) -> bool:
    """Whether a unit text, once cleaned, is one of `units`."""
    return clean(text) in units
