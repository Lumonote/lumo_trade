import pytest

from analysis.panel.registry import load_personas, SCHOOLS


def test_registry_loads_51_personas():
    personas = load_personas()
    assert len(personas) == 51
    flagship = [p for p in personas if p["tier"] == "flagship"]
    stub = [p for p in personas if p["tier"] == "stub"]
    assert len(flagship) == 12
    assert len(stub) == 39


def test_registry_covers_seven_schools():
    personas = load_personas()
    schools = {p["school"] for p in personas}
    assert schools == set(SCHOOLS.keys())  # A..G
    assert SCHOOLS["A"] == "价值派" and SCHOOLS["F"] == "游资派"


def test_registry_entries_have_required_fields():
    personas = load_personas()
    for p in personas:
        assert {"id", "name", "school", "tier", "rule", "voice"} <= set(p.keys())
        assert p["school"] in SCHOOLS
        assert p["tier"] in ("flagship", "stub")


def test_registry_ids_unique():
    ids = [p["id"] for p in load_personas()]
    assert len(ids) == len(set(ids))
