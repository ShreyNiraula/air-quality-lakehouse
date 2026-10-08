"""Task 1.1: the contract that describes a source, and its loader.

A contract is one YAML file per source in `contracts/`. It says what a delivered file looks like
and how to read it: its fields, which field holds what, the time convention, the duplicate key,
what the source calls each parameter and how it spells the unit, and the licence.
`contracts/openaq.yml` is the first one, and its comments explain each entry.

    from airquality.contracts import load
    contract = load("openaq")
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from airquality.manifests import PERMISSIONS

CONTRACTS = Path(__file__).parents[2] / "contracts"
ENTRIES = {
    "source": str,
    "title": str,
    "file": dict,
    "roles": dict,
    "time": dict,
    "duplicate_key": list,
    "parameters": dict,
    "licence": dict,
}
FORMATS = ("csv", "csv.gz")
ROLES = ("station", "sensor", "time", "parameter", "unit", "value")
MARKS = ("start", "end")  # which end of its period a timestamp names
KINDS = {str: "text", dict: "group of named entries", list: "list"}


class ContractError(ValueError):
    """A contract that cannot be used, with everything that is wrong with it."""


@dataclass(frozen=True)
class Parameter:
    name: str  # what the source calls it
    units: tuple[str, ...]  # every spelling of its unit, as the source writes it


@dataclass(frozen=True)
class Contract:
    source: str
    title: str
    format: str
    fields: tuple[str, ...]  # the header line, in order
    roles: dict[str, str]  # each of ROLES, and the field that holds it
    marks: str  # one of MARKS
    seconds: int  # the length of the period a timestamp names
    duplicate_key: tuple[str, ...]
    parameters: dict[str, Parameter]  # by the vocabulary's name
    licence: dict  # name, credit, and the five permissions


class _NoRepeats(yaml.SafeLoader):
    """YAML keeps the last of two entries with one name and says nothing. This loader notes them."""

    def __init__(self, stream):
        super().__init__(stream)
        self.repeated: list[str] = []

    def construct_mapping(self, node, deep=False):
        names = [self.construct_object(key, deep=True) for key, _ in node.value]
        self.repeated += sorted({str(name) for name in names if names.count(name) > 1})
        return super().construct_mapping(node, deep)


def texts(value: object) -> bool:
    """Whether this is a list of different, non-empty texts, with at least one in it."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
        and len(set(value)) == len(value)
    )


def validate(document: object) -> list[str]:
    """Everything that is wrong with a contract; nothing if it is sound.

    An entry that is missing or of the wrong kind is named, and the other entries are still
    checked, so one problem does not hide another.
    """
    if not isinstance(document, dict):
        return ["a contract is a group of named entries"]
    problems = [f"unknown entry: {name}" for name in document if name not in ENTRIES]
    usable = {}  # the entries that can be read; each of the others gets its one line here
    for name, kind in ENTRIES.items():
        if isinstance(document.get(name), kind):
            usable[name] = document[name]
        else:
            problems.append(f"{name}: missing, or not a {KINDS[kind]}")
    if not all(usable.get(name, "unusable").strip() for name in ("source", "title")):
        problems.append("source and title: neither may be empty")
    fields = usable.get("file", {}).get("fields")
    if "file" in usable:
        if usable["file"].get("format") not in FORMATS:
            problems.append(f"file: format must be one of {', '.join(FORMATS)}")
        if not texts(fields):
            problems.append("file: fields must be a list of different names")

    def named(names) -> bool:
        """Whether each is a field of the file. Not asked while the fields themselves are wrong."""
        return not texts(fields) or all(name in fields for name in names)

    roles = usable.get("roles")
    if roles is not None and (sorted(roles, key=str) != sorted(ROLES) or not named(roles.values())):
        problems.append(f"roles: each of {', '.join(ROLES)} must name one of the file's fields")
    if "time" in usable:
        time = usable["time"]
        if time.get("marks") not in MARKS:
            problems.append("time: marks must be start or end")
        if type(time.get("seconds")) is not int or time["seconds"] <= 0:
            problems.append("time: seconds must be a whole number above zero")
    key = usable.get("duplicate_key")
    if key is not None and not (texts(key) and named(key)):
        problems.append("duplicate_key: must be a list of the file's fields, each one once")
    if "parameters" in usable:
        problems += _parameters(usable["parameters"])
    if "licence" in usable:
        licence = usable["licence"]
        allowed = licence.get("permissions")
        if not all(
            isinstance(licence.get(k), str) and licence[k].strip() for k in ("name", "credit")
        ):
            problems.append("licence: the name or the credit line is missing")
        if (
            not isinstance(allowed, dict)
            or sorted(allowed, key=str) != sorted(PERMISSIONS)
            or {type(value) for value in allowed.values()} != {bool}
        ):
            problems.append("licence: the five permissions must each be true or false")
    return problems


def _parameters(parameters: dict) -> list[str]:
    problems = [] if parameters else ["parameters: the source must deliver at least one"]
    called = []
    for parameter, entry in parameters.items():
        entry = entry if isinstance(entry, dict) else {}
        name = entry.get("name")
        if not (isinstance(parameter, str) and isinstance(name, str) and name.strip()):
            # YAML reads a bare `no`, `on` or `yes` as true or false, and `no` is a pollutant.
            problems.append(f"parameters: {parameter} needs its name as text, in quotes if need be")
        else:
            called.append(name)
        if not texts(entry.get("units")):
            problems.append(f"parameters: {parameter} needs a list of its unit spellings")
    if len(set(called)) != len(called):
        problems.append("parameters: two of them have the same name in the source")
    return problems


def parse(text: str, source: str) -> Contract:
    """The contract written in `text`, which must be the contract of `source`."""
    loader = _NoRepeats(text)
    try:
        document = loader.get_single_data()
    except yaml.YAMLError as error:  # nothing can be checked in a text that cannot be read
        raise ContractError(f"{source}: not YAML: {error}") from error
    finally:
        loader.dispose()
    problems = [f"an entry is written twice: {name}" for name in loader.repeated]
    problems += validate(document)
    stated = document.get("source") if isinstance(document, dict) else None
    if isinstance(stated, str) and stated != source:
        problems.append(f"source: says {stated}, and the file is {source}.yml")
    if problems:
        raise ContractError(f"{source}: " + "; ".join(problems))
    return Contract(
        source=source,
        title=document["title"],
        format=document["file"]["format"],
        fields=tuple(document["file"]["fields"]),
        roles=dict(document["roles"]),
        marks=document["time"]["marks"],
        seconds=document["time"]["seconds"],
        duplicate_key=tuple(document["duplicate_key"]),
        parameters={
            parameter: Parameter(entry["name"], tuple(entry["units"]))
            for parameter, entry in document["parameters"].items()
        },
        licence=document["licence"],
    )


def load(source: str, folder: Path = CONTRACTS) -> Contract:
    """The contract of a source, or a ContractError that names everything wrong with it."""
    return parse((folder / f"{source}.yml").read_text(encoding="utf-8"), source)
