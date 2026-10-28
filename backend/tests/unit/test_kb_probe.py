from scripts.kb_probe import base_ranking, base_slug
from scripts.vignette_coverage import OK, RETIRED, SUCCESSOR, UNKNOWN, resolve


def test_base_slug_removes_a_trailing_revision_suffix():
    assert base_slug("seizures-dog-cat-rev2") == "seizures-dog-cat"
    assert base_slug("urinary-obstruction-cat-rev12") == "urinary-obstruction-cat"


def test_base_slug_leaves_other_slugs_alone():
    assert base_slug("seizures-dog-cat") == "seizures-dog-cat"
    assert base_slug("rev2-dog") == "rev2-dog"
    assert base_slug("ear-rev2-dog-cat") == "ear-rev2-dog-cat"


def test_base_ranking_merges_an_original_and_its_revision_at_the_best_position():
    ranked = ["bleeding-dog-cat-rev2", "trauma-dog-cat", "bleeding-dog-cat", "ear-dog-cat"]
    assert base_ranking(ranked) == ["bleeding-dog-cat", "trauma-dog-cat", "ear-dog-cat"]


def test_resolve_classifies_a_vignette_slug():
    active = ["bleeding-dog-cat-rev2", "ear-dog-cat"]
    stored = {"bleeding-dog-cat", "ear-dog-cat", "walkthrough-entry", *active}
    assert resolve("ear-dog-cat", active, stored) == (OK, "ear-dog-cat")
    assert resolve("bleeding-dog-cat", active, stored) == (SUCCESSOR, "bleeding-dog-cat-rev2")
    assert resolve("walkthrough-entry", active, stored) == (RETIRED, None)
    assert resolve("no-such-entry", active, stored) == (UNKNOWN, None)
