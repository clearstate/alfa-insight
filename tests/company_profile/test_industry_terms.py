"""Словарь отраслевых терминов contracts/industry_terms.yaml."""
from collections import Counter

from services.company_profile.features import load_rules
from services.company_profile.industry_terms import (
    load_industry_terms, match_company, prefixes_for, sections_for, validate_prefix,
)
from services.company_profile.okved import OkvedDirectory


def test_entries_well_formed():
    entries = load_industry_terms()
    assert len(entries) >= 30
    rule_ids = {r["id"] for r in load_rules()["industry_topics"]}
    for eid, e in entries.items():
        assert e["terms"], eid
        assert all(t == t.lower() for t in e["terms"]), eid
        assert e["industry_rule"] is None or e["industry_rule"] in rule_ids, eid
        for p in e["okved_prefixes"]:
            assert validate_prefix(p["prefix"]), (eid, p)
            assert p["verified"] in ("data", "classifier")
            assert (p["example_okved"] is not None) == (p["verified"] == "data")


def test_terms_unique_across_entries():
    counts = Counter(t for e in load_industry_terms().values() for t in e["terms"])
    assert [t for t, n in counts.items() if n > 1] == []


def test_no_prefix_in_two_entries_at_same_level():
    counts = Counter(p["prefix"] for e in load_industry_terms().values() for p in e["okved_prefixes"])
    assert [p for p, n in counts.items() if n > 1] == []


def test_sections_derived_from_prefixes():
    d = OkvedDirectory(load_rules()["okved_sections"])
    entries = load_industry_terms()
    assert sections_for(prefixes_for(entries, ["retail"]), d) == ["G"]
    assert sections_for(prefixes_for(entries, ["oil_gas"]), d) == ["B", "C", "G", "H"]


def test_prefix_match_is_more_precise_than_section():
    entries = load_industry_terms()
    retail = prefixes_for(entries, ["retail"])
    assert match_company(retail, ["47", "47.1", "47.11"]) == ["47"]   # розница
    assert match_company(retail, ["45", "45.3", "45.31", "45.31.1"]) == []   # опт автозапчастей, тоже раздел G
    assert match_company(prefixes_for(entries, ["precious_metals"]), ["07", "07.2", "07.29", "07.29.4"]) == ["07.29.4"]


def test_precious_metals_rule_fixed():
    rule = next(r for r in load_rules()["industry_topics"] if r["id"] == "precious_metals")
    assert "46.72.2" not in rule["okved_prefixes"] and "07.29.4" in rule["okved_prefixes"]
