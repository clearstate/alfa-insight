"""ОКВЭД и правила конфига."""
from services.company_profile.features import load_rules
from services.company_profile.okved import OkvedDirectory, matches_prefix, okved_levels


def test_okved_levels():
    assert okved_levels("46.34.2") == ("46", "46.3", "46.34", "46.34.2")
    assert okved_levels("41.2") == ("41", "41.2")
    assert okved_levels("41.20") == ("41", "41.2", "41.20")
    assert okved_levels("68.32.11") == ("68", "68.3", "68.32", "68.32.1", "68.32.11")
    assert okved_levels("99") == ("99",)
    assert okved_levels("62.0") == ("62", "62.0")
    for bad in ("", "4", "46.", "46.345", "AB.12", "46.34.123", "45.3.1", "4.5", "46..1"):
        assert okved_levels(bad) is None


def test_okved_sections():
    d = OkvedDirectory(load_rules()["okved_sections"])
    assert d.parse("47.11").section == "G"
    assert d.parse("01.11").section == "A"
    assert d.parse("35.11").section == "D"
    assert d.parse("04.00") is None or d.parse("04.00").section is None  # класса 04 нет в ОКВЭД2


def test_consumer_rule_excludes_wholesale_parts():
    rules = load_rules()
    prefixes = rules["factors"]["consumer_exposure"]["okved_prefixes"]
    assert matches_prefix(okved_levels("45.31.1"), prefixes) == []   # опт автозапчастей
    assert matches_prefix(okved_levels("45.32"), prefixes) == ["45.32"]
    assert matches_prefix(okved_levels("47.11"), prefixes) == ["47"]


def test_every_section_division_unique():
    seen = {}
    for letter, spec in load_rules()["okved_sections"].items():
        for div in range(spec["from"], spec["to"] + 1):
            assert div not in seen, (div, letter, seen.get(div))
            seen[div] = letter
