"""The unit rule: PM2.5 passes in its three spellings, and every other unit is refused."""

import dataclasses

import pytest

from airquality.contracts import Parameter, load
from airquality.units import accepted, clean, passes, stored_units

OPENAQ = load("openaq")
MICRO, MU = "µ", "μ"  # the micro sign, and the Greek letter it looks like


def test_cleaning_makes_the_micro_sign_and_the_raised_three_plain():
    assert clean(f"{MICRO}g/m³") == f"{MU}g/m3"
    assert clean(f" {MU}g/m3\n") == f"{MU}g/m3"
    assert clean("ug/m3") == "ug/m3"


def test_pm25_accepts_its_own_unit_and_the_spelling_openaq_lists():
    assert stored_units() == {"pm25": "ug/m3"}
    assert OPENAQ.parameters["pm25"].units == (f"{MICRO}g/m³",)
    assert accepted(OPENAQ) == {"pm25": frozenset({"ug/m3", f"{MU}g/m3"})}


@pytest.mark.parametrize(
    "text",
    [f"{MICRO}g/m³", f"{MU}g/m3", "ug/m3", f"{MU}g/m³", f"  {MICRO}g/m³ ", "ug/m³"],
)
def test_pm25_passes_in_each_of_its_spellings(text):
    assert passes(text, accepted(OPENAQ)["pm25"])


@pytest.mark.parametrize(
    "text",
    ["mg/m3", f"{MICRO}g/m²", "ppm", "ppb", "UG/M3", f"{MICRO}g / m³", "g/m3", f"{MICRO}g", ""],
)
def test_pm25_in_any_other_unit_is_refused(text):
    assert not passes(text, accepted(OPENAQ)["pm25"])


def test_a_spelling_passes_only_for_the_parameter_that_lists_it():
    stored = {"pm25": "ug/m3", "temperature": "Cel"}
    parameters = OPENAQ.parameters | {"temperature": Parameter("temperature", ("c", "℃"))}
    units = accepted(dataclasses.replace(OPENAQ, parameters=parameters), stored)
    assert units["temperature"] == frozenset({"Cel", "c", "°C"})  # one sign becomes two
    assert passes("°C", units["temperature"]) and not passes("°C", units["pm25"])
    assert not passes("ug/m3", units["temperature"]) and not passes("K", units["temperature"])


def test_a_contract_with_a_parameter_the_vocabulary_lacks_is_refused():
    with pytest.raises(
        ValueError, match="openaq: the vocabulary has no parameter pm25; it has no2"
    ):
        accepted(OPENAQ, {"no2": "ug/m3"})
