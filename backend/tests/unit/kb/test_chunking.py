from app.kb.chunking import chunk_text, embedding_text, species_names, split_units


def words(chunk: str) -> int:
    return len(chunk.split())


def sentences(n: int, each: int = 10) -> str:
    """n sentences of `each` words, numbered so they can be told apart."""
    return " ".join(
        f"Sentence {i} " + " ".join(["word"] * (each - 2)) + "." for i in range(1, n + 1)
    )


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == [] and chunk_text("   \n\n ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("One short sentence. Another one.", target_words=150) == [
        "One short sentence. Another one."
    ]


def test_long_text_is_split_and_each_chunk_stays_near_the_target():
    chunks = chunk_text(sentences(40), target_words=60, overlap_sentences=1)
    assert len(chunks) > 3
    assert all(words(c) <= 60 + 10 for c in chunks)  # target plus at most one sentence


def test_overlap_repeats_the_last_sentence_of_the_previous_chunk():
    chunks = chunk_text(sentences(30), target_words=50, overlap_sentences=1)
    last_of_first = split_units(chunks[0])[-1]
    assert split_units(chunks[1])[0] == last_of_first


def test_no_overlap_when_disabled():
    chunks = chunk_text(sentences(30), target_words=50, overlap_sentences=0)
    assert split_units(chunks[1])[0] != split_units(chunks[0])[-1]


def test_every_sentence_survives_chunking():
    text = sentences(25)
    joined = " ".join(chunk_text(text, target_words=40, overlap_sentences=1))
    assert all(f"Sentence {i} " in joined for i in range(1, 26))


def test_line_breaks_are_boundaries_even_without_full_stops():
    text = "Warning signs\nStraining to pass urine\nCrying in the litter box"
    assert split_units(text) == [
        "Warning signs",
        "Straining to pass urine",
        "Crying in the litter box",
    ]


def test_abbreviations_do_not_end_a_sentence():
    units = split_units("Some breeds, e.g. Siberian huskies, are prone to this. It is uncommon.")
    assert units == ["Some breeds, e.g. Siberian huskies, are prone to this.", "It is uncommon."]


def test_one_enormous_sentence_is_cut_into_windows():
    chunks = chunk_text(" ".join(["word"] * 400) + ".", target_words=100, overlap_sentences=0)
    assert len(chunks) == 4 and all(words(c) <= 100 for c in chunks)


def test_no_chunk_consists_only_of_the_overlap():
    chunks = chunk_text(sentences(12, each=40), target_words=45, overlap_sentences=1)
    assert len(chunks) == len(set(chunks))
    assert all(len(split_units(c)) >= 1 and words(c) > 0 for c in chunks)


def test_chunking_is_deterministic():
    text = sentences(30)
    assert chunk_text(text, 50, 1) == chunk_text(text, 50, 1)


def test_embedding_text_has_a_header_but_the_stored_chunk_would_not():
    assert embedding_text("Title", ["CAT", "DOG"], "Body.") == "Title (CAT, DOG). Body."


def test_species_names_accepts_enums_and_strings():
    import enum

    class S(enum.StrEnum):
        CAT = "CAT"

    assert species_names([S.CAT, "DOG"]) == ["CAT", "DOG"]
