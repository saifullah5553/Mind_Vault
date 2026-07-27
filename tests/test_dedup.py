from core.dedup import is_duplicate, similarity


def test_similarity_bounds():
    assert similarity("the fall of rome", "the fall of rome") > 0.99
    assert similarity("psychology of fear", "quantum chromodynamics") < 0.5


def test_duplicate_gate():
    corpus = ["The Secret Reason Rome Collapsed", "Why We Procrastinate"]
    dup, score = is_duplicate("The Secret Reason Rome Collapsed", corpus, threshold=0.8)
    assert dup and score > 0.8

    dup2, score2 = is_duplicate("How Ants Build Colonies", corpus, threshold=0.8)
    assert not dup2 and score2 < 0.8


def test_empty_corpus_is_never_duplicate():
    dup, score = is_duplicate("anything", [], threshold=0.8)
    assert not dup and score == 0.0
