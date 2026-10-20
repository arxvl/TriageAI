import pytest

from app.kb.retrieval_metrics import recall_at_k, reciprocal_rank, summarize


def test_recall_with_one_expected_entry():
    assert recall_at_k(["a", "b", "c"], ["b"], 5) == 1.0
    assert recall_at_k(["a", "b", "c"], ["z"], 5) == 0.0


def test_recall_only_looks_at_the_top_k():
    assert recall_at_k(["a", "b", "c", "d"], ["d"], 3) == 0.0
    assert recall_at_k(["a", "b", "c", "d"], ["d"], 4) == 1.0


def test_recall_with_two_expected_entries():
    assert recall_at_k(["a", "b", "c"], ["a", "z"], 5) == 0.5


def test_reciprocal_rank():
    assert reciprocal_rank(["a", "b", "c"], ["a"]) == 1.0
    assert reciprocal_rank(["a", "b", "c"], ["c"]) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a", "b"], ["z"]) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_hit():
    assert reciprocal_rank(["x", "b", "a"], ["a", "b"]) == 0.5


def test_summary_by_hand():
    results = [
        (["a", "b"], ["a"]),  # recall 1, rr 1
        (["x", "a"], ["a"]),  # recall 1, rr 0.5
        (["x", "y"], ["a"]),
    ]  # recall 0, rr 0
    out = summarize(results, k=5)
    assert out["queries"] == 3
    assert out["recall@5"] == pytest.approx(2 / 3)
    assert out["mrr"] == pytest.approx(0.5)


def test_bad_input_is_rejected():
    with pytest.raises(ValueError):
        recall_at_k(["a"], [], 5)
    with pytest.raises(ValueError):
        summarize([])
