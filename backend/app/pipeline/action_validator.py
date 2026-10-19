"""The deterministic action validator (P05b §5b.2, FR-74, NFR-30, ADR-18 §4).

What `app.pipeline.safety` is to the category, this is to the action text: the
last thing between a fluent model answer and something a staff member reads off
the screen and does. No model call, no session, no clock, no settings — same
inputs, same output, on a laptop and in the evaluation harness (NFR-23).

The boundary it enforces is FR-28 as ADR-18 §1 narrowed it. Actions are
triage-level handling only: escalate, prepare, monitor, what to ask the owner,
transport precautions. "Prepare oxygen and alert the veterinarian" is in scope;
"give 0.2 mg/kg butorphanol" is not, and no prompt wording is trusted to keep it
that way.

Two things differ from the recommendation validator, both on purpose:

- **An uncited action is dropped, not labelled.** FR-22 keeps an uncited
  recommendation and lowers its confidence, because a category is still needed.
  FR-74 has no such obligation: an action with nothing behind it is noise, and
  the baseline set is already there to fall back on (FR-72).
- **Rejections are counted, never corrected.** Nothing here rewrites text. A
  rejected action disappears and the tally is surfaced, so a high rejection rate
  reads as a prompt problem to fix in M6b — not as a reason to loosen a rule
  (ADR-18 §4).

Rules run in the order P05b §5b.2 lists them and the **first** rule an action
fails is the reason recorded. So `"Give butorphanol 0.2 mg/kg IV"` is reported as
`CONTAINS_DOSE` rather than `CONTAINS_DRUG`: it is both, and the order is fixed
so the stored code is the same every time.

The words every rule screens against live in `app.pipeline.blocklists`.
"""

import logging
import re
import uuid
from collections.abc import Hashable, Iterable
from typing import TypeVar

from sqlalchemy.orm import Session

from app.models.enums import VTLCategory
from app.pipeline.blocklists import (
    DIAGNOSIS_TERMS,
    DOSE_FREQUENCIES,
    DOSE_RATE_TERMS,
    DOSE_ROUTES,
    DOSE_UNITS,
    DRUG_NAMES,
    GENERIC_DRUG_TERMS,
    HEDGE_TERMS,
)
from app.pipeline.types import Passage, SuggestedAction
from app.repositories.pipeline_repository import PipelineRepository

__all__ = [
    "CONTAINS_DIAGNOSIS",
    "CONTAINS_DOSE",
    "CONTAINS_DRUG",
    "DUPLICATE",
    "HEDGE_WINDOW",
    "MAX_WORDS",
    "NO_VALID_CITATION",
    "REJECTION_REASONS",
    "TOO_LONG",
    "action_lines",
    "baseline_actions",
    "baseline_line_failure",
    "validate",
]

logger = logging.getLogger(__name__)

# The machine-readable rejection codes stored on the recommendation's
# `rejection_reasons` (subphase 5b.3). Codes, not prose: the UI never shows them
# and the evaluation harness counts them (M7).
#
# `NO_VALID_CITATION` deliberately repeats the value used by
# `app.pipeline.safety`: it is the same condition, FR-22 and FR-74 only differ in
# what they do about it.
NO_VALID_CITATION = "NO_VALID_CITATION"
TOO_LONG = "TOO_LONG"
CONTAINS_DOSE = "CONTAINS_DOSE"
CONTAINS_DRUG = "CONTAINS_DRUG"
CONTAINS_DIAGNOSIS = "CONTAINS_DIAGNOSIS"
DUPLICATE = "DUPLICATE"

# In the order the rules run, which is the order a reason can first appear.
REJECTION_REASONS: tuple[str, ...] = (
    NO_VALID_CITATION,
    TOO_LONG,
    CONTAINS_DOSE,
    CONTAINS_DRUG,
    CONTAINS_DIAGNOSIS,
    DUPLICATE,
)

# An action is one instruction, not a paragraph (SuggestedAction.text, FR-73).
MAX_WORDS = 25

# How near a hedge has to be, in words, for a diagnosis term to read as a
# question rather than an assertion (P05b §5b.2 rule 5).
HEDGE_WINDOW = 3


def _alternation(terms: Iterable[str]) -> str:
    """A regex alternation of literal terms, longest first.

    Longest first so `mcg` is tried before `g` and `pleural effusion` before any
    shorter term that starts the same way; `re` takes the first branch that
    matches, not the longest.
    """
    return "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))


def _phrase_pattern(term: str) -> str:
    """A word-bounded pattern for one block-list term, allowing a plural `s`.

    The plural is what makes `"Start antibiotics"` fail on the term
    `antibiotic` (P05b §5b.2). Internal whitespace is relaxed to `\\s+` so
    `calcium  gluconate` matches too.
    """
    body = r"\s+".join(re.escape(word) for word in term.split())
    return rf"\b{body}s?\b"


# --- Rule 3: dose expressions ---------------------------------------------
# A number immediately followed by a unit: `0.2mg`, `2 mL`, `5 cc`, `2 grams`.
# No `\b` before the unit, because there is no word boundary inside `2mg`; a
# trailing `s` is allowed so only singular units have to be listed. A bare number
# is not a dose, which is what keeps "recheck every 15 minutes" usable.
_DOSE_NUMBER_UNIT = re.compile(rf"\d\s*(?:{_alternation(DOSE_UNITS)})s?\b", re.IGNORECASE)

# Per-weight forms are a dose with or without a number attached.
_DOSE_RATE = re.compile(rf"\b(?:{_alternation(DOSE_RATE_TERMS)})\b", re.IGNORECASE)

# A route only counts with a number *before* it — `20 mg PO`, `2 mL SC`. Matching
# a number after it would reject "recheck the patient in 15 minutes", and a real
# dose expression puts the route last anyway.
_DOSE_ROUTE = re.compile(rf"\d\s*(?:{_alternation(DOSE_ROUTES)})\b", re.IGNORECASE)

# Dosing frequencies. `q4h`-style intervals are a pattern; the abbreviations are
# not English words, so they are blocked on their own.
_DOSE_FREQUENCY = re.compile(rf"\bq\d+h\b|\b(?:{_alternation(DOSE_FREQUENCIES)})\b", re.IGNORECASE)

_DOSE_PATTERNS = (_DOSE_NUMBER_UNIT, _DOSE_RATE, _DOSE_ROUTE, _DOSE_FREQUENCY)

# --- Rule 4: medication names ---------------------------------------------
_DRUG_PATTERN = re.compile(
    "|".join(_phrase_pattern(term) for term in (*DRUG_NAMES, *GENERIC_DRUG_TERMS)),
    re.IGNORECASE,
)

# --- Rules 5 and 6: tokens ------------------------------------------------
# Word tokens for the hedge-distance test, and the normal form used to collapse
# duplicates. Both drop punctuation, so "Prepare oxygen." and "prepare oxygen"
# are one action.
_WORD = re.compile(r"[a-z0-9]+")

_DIAGNOSIS_PHRASES = tuple(term.split() for term in DIAGNOSIS_TERMS)
_HEDGE_PHRASES = tuple(term.split() for term in HEDGE_TERMS)

_T = TypeVar("_T", bound=Hashable)


def _unique(values: Iterable[_T]) -> list[_T]:
    """De-duplicate, preserving first-seen order.

    Order matters: a stored `cited_chunk_ids` list is read back on the review
    screen and asserted on in tests, so it has to be the same list every time.
    """
    seen: set[_T] = set()
    result: list[_T] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _normalized(text: str) -> str:
    """The form duplicates are compared on: lowercase words, single-spaced."""
    return " ".join(_words(text))


def _spans(tokens: list[str], phrase: list[str]) -> list[tuple[int, int]]:
    """Every `[start, end)` token span where `phrase` occurs in `tokens`."""
    width = len(phrase)
    return [
        (index, index + width)
        for index in range(len(tokens) - width + 1)
        if tokens[index : index + width] == phrase
    ]


def _contains_dose(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DOSE_PATTERNS)


def _contains_drug(text: str) -> bool:
    return _DRUG_PATTERN.search(text) is not None


def _asserts_diagnosis(text: str) -> bool:
    """True when a diagnosis term is stated as fact rather than hedged.

    "The dog has pneumonia" asserts; "rule out obstruction", "ask whether the cat
    has asthma" and "watch for signs of obstruction" do not. The test is
    positional: a hedge within `HEDGE_WINDOW` words of the term, on either side,
    makes it a question — "obstruction suspected" is as ordinary as "suspected
    obstruction".

    Deliberately crude. It cannot read a sentence, so it errs toward rejecting
    (ADR-18 consequences), and an action that trips it should be reworded by the
    prompt rather than argued with here.
    """
    tokens = _words(text)
    hedges = [span for phrase in _HEDGE_PHRASES for span in _spans(tokens, phrase)]
    for phrase in _DIAGNOSIS_PHRASES:
        for start, end in _spans(tokens, phrase):
            hedged = any(
                0 <= start - hedge_end <= HEDGE_WINDOW or 0 <= hedge_start - end <= HEDGE_WINDOW
                for hedge_start, hedge_end in hedges
            )
            if not hedged:
                return True
    return False


def _content_failure(text: str) -> str | None:
    """The code of the first content rule this text fails, or None.

    Rules 2 to 5 of P05b §5b.2 — the word limit, dose expressions, medication
    names and asserted diagnoses — in that order. Separate from rule 1 because
    the citation rule does not apply to every caller: a baseline action line
    cites nothing, the approved `URGENCY_ACTIONS` entry being its own provenance
    (FR-72, ADR-18 §2).
    """
    if len(text.split()) > MAX_WORDS:
        return TOO_LONG
    if _contains_dose(text):
        return CONTAINS_DOSE
    if _contains_drug(text):
        return CONTAINS_DRUG
    if _asserts_diagnosis(text):
        return CONTAINS_DIAGNOSIS
    return None


def baseline_line_failure(text: str) -> str | None:
    """The code of the first FR-28 rule one baseline action line fails, or None.

    The knowledge-base workflow screens every line of an `URGENCY_ACTIONS` entry
    with this before the entry can be imported or submitted (P08 §8.2b). Baseline
    text never passes `validate` and is shown to staff verbatim, so without this
    the one action text nobody screens would also be the only one no second pair
    of eyes checks word by word (FR-28, ADR-18 §1).

    The same four rules, the same codes and the same order as a tailored action,
    deliberately: a line a curator writes and a line a model proposes are read off
    the same screen and must meet the same boundary.
    """
    return _content_failure(text)


def _first_failure(text: str, cited_ranks: list[int]) -> str | None:
    """The code of the first rule this action fails, or None if it passes.

    Rules 1 to 5 of P05b §5b.2, in order. Rule 1 is applied to the *already
    filtered* ranks, so the caller decides what a valid citation is and this
    only reports that nothing survived.
    """
    if not cited_ranks:
        return NO_VALID_CITATION
    return _content_failure(text)


def validate(
    actions: list[SuggestedAction],
    passages: list[Passage],
    max_items: int,
) -> tuple[list[SuggestedAction], list[str]]:
    """Screen tailored actions, returning the kept ones and one code per drop.

    Nothing passed in is mutated. A kept action comes back with its citations
    narrowed to the ranks that were actually retrieved, so a rank the model
    invented can never reach `action_suggestions.cited_chunk_ids` (FR-74, DR-09).

    `len(reasons)` is the `rejected_count` of the `ActionPlan` (subphase 5b.3):
    exactly one code per action that was dropped on content or as a duplicate.
    Truncation past `max_items` adds no code — that is a cap, not a rejection,
    and counting it would make a model that returned eight good actions look like
    a safety problem.
    """
    retrieved_ranks = {passage.rank for passage in passages}
    kept: list[SuggestedAction] = []
    reasons: list[str] = []
    seen: set[str] = set()

    for action in actions:
        cited_ranks = _unique([rank for rank in action.cited_ranks if rank in retrieved_ranks])

        failure = _first_failure(action.text, cited_ranks)
        if failure is not None:
            reasons.append(failure)
            continue

        normal = _normalized(action.text)
        if normal in seen:
            reasons.append(DUPLICATE)
            continue
        seen.add(normal)

        kept.append(action.model_copy(update={"cited_ranks": cited_ranks}))

    # Rule 6: truncate last, so the items that survive are the first `max_items`
    # distinct actions the stage proposed, in its own order of preference.
    return kept[: max(max_items, 0)], reasons


def action_lines(content: str) -> list[str]:
    """The actions an `URGENCY_ACTIONS` entry holds: its non-empty lines (FR-72).

    The one split, used both by `baseline_actions` when the pipeline reads an
    approved set and by `schemas.kb.content_problem` when the workflow validates
    one. Two splits could accept a set of four actions and display three.
    """
    return [line.strip() for line in content.splitlines() if line.strip()]


def baseline_actions(
    session: Session,
    category: VTLCategory,
    kb_version_id: uuid.UUID,
) -> list[str]:
    """The baseline action set for one category, verbatim (FR-71, FR-72).

    Read from the ACTIVE `URGENCY_ACTIONS` knowledge-base entry for that category
    in that KB version, one action per line. Curated content, so it does not go
    through `validate`: it has already passed the same approval gate as every
    other clinical entry (BR-04, BR-10, ADR-18 §2).

    A missing entry returns `[]` and logs a warning rather than raising. A gap in
    the knowledge base is a content problem for M5 to fill; it must never fail
    the actions job or touch the case status (FR-77).
    """
    content = PipelineRepository(session).active_urgency_actions_content(category, kb_version_id)
    if content is None:
        logger.warning(
            "No ACTIVE URGENCY_ACTIONS entry: category=%s kb_version_id=%s",
            category.value,
            kb_version_id,
        )
        return []
    return action_lines(content)
