"""The source contracts: OpenAQ's loads, and each kind of broken one is named."""

import copy

import pytest
import yaml

from airquality import manifests
from airquality.checks import openaq_file
from airquality.contracts import CONTRACTS, ContractError, load, parse, validate

TEXT = (CONTRACTS / "openaq.yml").read_text(encoding="utf-8")


def test_the_openaq_contract_loads_as_check_0_4_found_the_files():
    contract = load("openaq")
    assert ",".join(contract.fields) == openaq_file.EXPECTED_FIELDS
    assert contract.format == "csv.gz"
    assert (contract.marks, contract.seconds) == ("end", 3600)
    assert contract.duplicate_key == ("sensors_id", "datetime")
    assert contract.roles["station"] == "location_id" and contract.roles["unit"] == "units"
    assert contract.parameters["pm25"].units == (openaq_file.EXPECTED_PM25_UNIT,)


def test_the_openaq_contract_agrees_with_its_manifest():
    contract, (manifest, _) = load("openaq"), manifests.read("openaq")
    for part in ("name", "credit", "permissions"):
        assert contract.licence[part] == manifest["licence"][part]
    called = {parameter: entry.name for parameter, entry in contract.parameters.items()}
    for station in manifest["stations"]:
        assert station["seconds_between_rows"] == contract.seconds
        placed = [sensor for sensor in station["sensors"] if sensor["parameter"] in called]
        assert [sensor["parameter"] for sensor in placed] == ["pm25"]
        for sensor in placed:
            assert sensor["name_as_found"] == called[sensor["parameter"]]
            assert sensor["unit_as_found"] in contract.parameters[sensor["parameter"]].units


def broken(change):
    document = yaml.safe_load(TEXT)
    change(document)
    return validate(document)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda d: None, None),
        (lambda d: d.update(colour="blue"), "unknown entry: colour"),
        (lambda d: d.pop("time"), "time: missing"),
        (lambda d: d.update(roles=["datetime"]), "roles: missing, or not a group"),
        (lambda d: d.update(title=" "), "neither may be empty"),
        (lambda d: d["file"].update(format="xlsx"), "format must be one of"),
        (lambda d: d["file"]["fields"].append("value"), "list of different names"),
        (lambda d: d["file"].pop("fields"), "list of different names"),
        (lambda d: d["roles"].pop("unit"), "roles: each of"),
        (lambda d: d["roles"].update(colour="value"), "roles: each of"),
        (lambda d: d["roles"].update(value="reading"), "roles: each of"),
        (lambda d: d["time"].update(marks="middle"), "marks must be start or end"),
        (lambda d: d["time"].update(seconds=0), "whole number above zero"),
        (lambda d: d["time"].update(seconds=True), "whole number above zero"),
        (lambda d: d["time"].update(seconds="3600"), "whole number above zero"),
        (lambda d: d.update(duplicate_key=[]), "duplicate_key: must be"),
        (lambda d: d["duplicate_key"].append("sensor"), "duplicate_key: must be"),
        (lambda d: d["duplicate_key"].append("datetime"), "duplicate_key: must be"),
        (lambda d: d["parameters"].clear(), "at least one"),
        (lambda d: d["parameters"].update(pm25="pm25"), "pm25 needs its name as text"),
        (lambda d: d["parameters"]["pm25"].update(name=False), "pm25 needs its name as text"),
        (lambda d: d["parameters"]["pm25"].update(units=[]), "pm25 needs a list of its unit"),
        (lambda d: d["parameters"]["pm25"].update(units="µg/m³"), "pm25 needs a list of its unit"),
        (
            lambda d: d["parameters"].update(pm10=copy.deepcopy(d["parameters"]["pm25"])),
            "the same name in the source",
        ),
        (lambda d: d["licence"].update(credit=""), "credit line is missing"),
        (lambda d: d["licence"]["permissions"].pop("share_alike"), "five permissions"),
        (lambda d: d["licence"]["permissions"].update(attribution="yes"), "five permissions"),
        (lambda d: d["licence"].update(permissions=None), "five permissions"),
    ],
)
def test_each_kind_of_broken_contract_is_named(change, problem):
    found = broken(change)
    assert (found == []) if problem is None else any(problem in line for line in found), found


def test_one_problem_does_not_hide_another():
    def change(d):
        d.pop("time")
        d.update(roles=["datetime"], colour="blue")
        d["file"].update(format="xlsx")
        d["duplicate_key"].append("sensor")
        d["parameters"]["pm25"].update(name=False, units=[])
        d["licence"].update(credit="")

    found = broken(change)
    assert [line.split(":")[0] for line in found] == [
        *("unknown entry", "roles", "time", "file", "duplicate_key"),
        *("parameters", "parameters", "licence"),
    ], found


def test_a_wrong_list_of_fields_is_one_problem_not_three():
    assert broken(lambda d: d["file"].update(fields="datetime")) == [
        "file: fields must be a list of different names"
    ]


def test_a_contract_that_is_not_a_group_of_entries_is_refused():
    assert validate(["source", "openaq"]) == ["a contract is a group of named entries"]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (TEXT.replace("source: openaq", "source: openaqi"), "says openaqi"),
        (TEXT + "title: Another title\n", "written twice: title"),
        (TEXT.replace("    name: pm25", "    name: no"), "needs its name as text"),
        (TEXT.replace("marks: end", "marks: [end"), "not YAML"),
        (TEXT.replace("seconds: 3600", "seconds: 0") + "colour: blue\n", "colour; time: seconds"),
        (
            TEXT.replace("source: openaq", "source: openaqi") + "title: Another\ntime: 3600\n",
            "twice: time; an entry is written twice: title; time: missing.*; source: says openaqi",
        ),
    ],
    ids=["another source", "an entry twice", "a bare no", "not YAML", "two problems", "four"],
)
def test_a_broken_file_is_refused_with_its_source_and_every_problem(text, problem):
    assert text != TEXT
    with pytest.raises(ContractError, match=problem) as refused:
        parse(text, "openaq")
    assert str(refused.value).startswith("openaq: ")


def test_a_missing_contract_is_not_mistaken_for_a_broken_one(tmp_path):
    (tmp_path / "copy.yml").write_text(TEXT.replace("source: openaq", "source: copy"), "utf-8")
    assert load("copy", tmp_path).source == "copy"
    with pytest.raises(FileNotFoundError):
        load("openaq", tmp_path)
