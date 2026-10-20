"""Sentence-packing chunker for knowledge-base entries (M5)."""

from __future__ import annotations

import re

# Protected so that "e.g. Siberian huskies" is not treated as the end of a sentence.
_ABBREVIATIONS = ("e.g.", "i.e.", "vs.", "approx.", "etc.", "Dr.")
_DOT = "\u2024"  # a look-alike character that cannot end a sentence
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_units(text: str) -> list[str]:
    """Break text into sentence-sized units. Line breaks always split; so do sentence ends."""
    units: list[str] = []
    for line in re.split(r"\n+", text.strip()):
        line = line.strip()
        if not line:
            continue
        for abbr in _ABBREVIATIONS:
            line = line.replace(abbr, abbr.replace(".", _DOT))
        for part in _SENTENCE_END.split(line):
            part = part.replace(_DOT, ".").strip()
            if part:
                units.append(part)
    return units


def _windows(unit: str, size: int) -> list[str]:
    """A single sentence longer than a whole chunk is cut into word windows."""
    words = unit.split()
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def chunk_text(text: str, target_words: int = 150, overlap_sentences: int = 1) -> list[str]:
    """Pack sentences into chunks of about `target_words`, repeating the last
    `overlap_sentences` sentences at the start of the next chunk for context."""
    units: list[str] = []
    for unit in split_units(text):
        units.extend(_windows(unit, target_words) if len(unit.split()) > target_words else [unit])

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in units:
        words = len(unit.split())
        if current and current_words + words > target_words:
            chunks.append(" ".join(current))
            current = current[-overlap_sentences:] if overlap_sentences else []
            current_words = sum(len(u.split()) for u in current)
        current.append(unit)
        current_words += words
    if current:
        chunks.append(" ".join(current))
    return chunks


def species_names(species) -> list[str]:
    """Works whether the entry holds enum members or plain strings."""
    return [getattr(s, "value", s) for s in species]


def embedding_text(title: str, species: list[str], chunk: str) -> str:
    """What is EMBEDDED. The header gives every chunk its context. It is deliberately
    NOT stored in kb_chunks.text, so reviewers and the generator read clean passages."""
    return f"{title} ({', '.join(species)}). {chunk}"
