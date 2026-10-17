"""Turning stored evidence spans into character offsets (FR-13, FR-31).

The extraction stage records, for each value it reported, the span of text that
supports it — as the text itself, not as offsets (`pipeline/types.py`,
`EvidenceSpan`). That is the right thing to store: offsets into a string are
meaningless once anyone wonders which string, and a quoted phrase survives being
read by a human later.

The review screen needs offsets, though, because it wraps each span in a `<mark>`
(W-04 panel 1). So they are derived here, at read time, by exact substring search
against the de-identified text the extraction was produced from
(`extraction_results.input_text`).

Deterministic and model-free: this is a string search, nothing more. A span that
does not match comes back `found=false` rather than being dropped, so the screen
can say that a highlight is missing instead of quietly showing fewer than the
extraction claimed.
"""

from app.schemas.review import EvidenceSpanOut


def locate(spans: object, input_text: str | None) -> list[EvidenceSpanOut]:
    """Map each stored span onto `input_text`, in the order it was stored.

    Two cases produce `found=false` for everything:

    * `input_text` is None — the extraction predates migration 0004, so there is
      no text to search and no way to reconstruct it;
    * the span's text is empty, which is not a span.

    **Repeated phrases.** Two spans can quote the same words — "vomiting" may be
    the evidence for both the complaint and the frequency. Searching from the
    start each time would stack both highlights on the first occurrence, so a
    cursor per distinct text makes the *n*-th span quoting a phrase resolve to
    its *n*-th occurrence. When the phrase occurs fewer times than it is cited,
    the surplus spans report `found=false`: a wrong highlight is worse than a
    missing one, and this is also what a span that genuinely no longer matches
    looks like.

    `spans` is read defensively because it comes out of a JSONB column. A row
    written in an unexpected shape yields no spans rather than raising — a
    malformed span must not make a case unreadable.
    """
    if not isinstance(spans, list):
        return []

    located: list[EvidenceSpanOut] = []
    # Where to resume searching for each distinct text already seen.
    cursors: dict[str, int] = {}

    for span in spans:
        if not isinstance(span, dict):
            continue
        field = span.get("field")
        text = span.get("text")
        if not isinstance(field, str) or not isinstance(text, str):
            continue

        start = _find(input_text, text, cursors)
        if start is None:
            located.append(
                EvidenceSpanOut(field=field, text=text, start=None, end=None, found=False)
            )
            continue

        cursors[text] = start + len(text)
        located.append(
            EvidenceSpanOut(field=field, text=text, start=start, end=start + len(text), found=True)
        )

    return located


def _find(input_text: str | None, text: str, cursors: dict[str, int]) -> int | None:
    """The offset of this span's occurrence of `text`, or None if there is none."""
    if not input_text or not text:
        return None
    found = input_text.find(text, cursors.get(text, 0))
    return None if found < 0 else found
