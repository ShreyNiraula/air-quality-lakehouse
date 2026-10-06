"""The vocabulary check, on small made-up tables shaped like the CF and UCUM ones. No network."""

import xml.etree.ElementTree as ET

from airquality.checks.vocabulary import check, read_ucum

CF = """<standard_name_table>
<entry id="mass_concentration_of_pm2p5_ambient_aerosol_particles_in_air">
  <canonical_units>kg m-3</canonical_units></entry>
<entry id="air_temperature"><canonical_units>K</canonical_units></entry>
<entry id="relative_humidity"><canonical_units>1</canonical_units></entry>
<alias id="an_old_name"><entry_id>air_temperature</entry_id></alias>
</standard_name_table>"""
UCUM = ET.fromstring("""<root xmlns="http://unitsofmeasure.org/ucum-essence">
<prefix Code="u"><name>micro</name></prefix>
<base-unit Code="g"><name>gram</name></base-unit>
<base-unit Code="m"><name>meter</name></base-unit>
<unit Code="Cel" isMetric="yes"><name>degree Celsius</name></unit>
<unit Code="%" isMetric="no"><name>percent</name></unit>
</root>""")


def differing(cf=CF):
    return [line for agrees, line in check(ET.fromstring(cf), UCUM) if not agrees]


def test_tables_that_agree_with_the_plan_give_no_difference():
    assert differing() == []
    assert len(check(ET.fromstring(CF), UCUM)) == 6


def test_a_name_that_is_gone_or_only_an_alias_differs():
    renamed = CF.replace('entry id="air_temperature"', 'entry id="temperature_of_air"')
    assert [line.split(":")[0:2] for line in differing(renamed)] == [
        ["temperature", " CF name air_temperature"]
    ]


def test_a_changed_cf_unit_differs_only_where_the_plan_states_one():
    assert len(differing(CF.replace("kg m-3", "g m-3"))) == 1
    assert differing(CF.replace("<canonical_units>1<", "<canonical_units>%<")) == []


def test_ucum_units_are_read_from_the_tables():
    assert read_ucum("ug/m3", UCUM) == "micro gram per meter to the power 3"
    assert read_ucum("Cel", UCUM) == "degree Celsius"
    assert read_ucum("μg/m3", UCUM) is None  # a Greek mu is not a UCUM prefix
    assert read_ucum("u%", UCUM) is None  # percent is not metric, so it takes no prefix
    assert read_ucum("ug/m³", UCUM) is None  # a superscript three is not a UCUM power
