"""Parse and validate a vignette CSV (P09 §9.2 task 1, FR-64).

Pure: bytes in, rows and errors out. It never touches the database, so slug
resolution and storing the set live in `EvaluationService`, and a file can be
checked without an administrator or a session.

Every row is checked and every problem is reported, by the line the row starts on
(the header is line 1). A quoted description may run over several lines, so the
number is the reader's record start, not a count of records: an administrator who
opens the file in a spreadsheet or an editor lands on the right row either way.

Any error rejects the whole file. A half-imported set would make a metrics run
quietly cover fewer vignettes than its author thought it did.

The text is English (FR-18, ADR-16) and fictitious: nothing here detects a
language or cleans a description.
"""

import csv
import io
from dataclasses import dataclass, field

from app.models.enums import Species, VTLCategory
from app.schemas.case import DESCRIPTION_MAX_LENGTH, DESCRIPTION_MIN_LENGTH

__all__ = [
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "REQUIRED_COLUMNS",
    "ParsedVignette",
    "ParseResult",
    "RowError",
    "parse_vignette_csv",
]

REQUIRED_COLUMNS = (
    "external_id",
    "species",
    "description",
    "reference_category",
    "relevant_entry_slugs",
)

# FR-64 asks for 50-100 vignettes. The ceiling is for a mistake — the wrong file —
# not a policy, and keeps a request from holding a worker on a huge upload.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500

EXTERNAL_ID_MAX_LENGTH = 100
SLUG_SEPARATOR = ";"

# Reported for problems with the file as a whole rather than one row.
FILE_ROW = 0


@dataclass(frozen=True)
class RowError:
    row: int
    field: str | None
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"row": self.row, "field": self.field, "message": self.message}


@dataclass(frozen=True)
class ParsedVignette:
    row: int
    external_id: str
    species: Species
    description: str
    reference_category: VTLCategory
    relevant_slugs: list[str]


@dataclass
class ParseResult:
    vignettes: list[ParsedVignette] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _choice(value: str, enum: type[Species] | type[VTLCategory]) -> Species | VTLCategory | None:
    try:
        return enum(value.strip().upper())
    except ValueError:
        return None


def _slugs(raw: str) -> list[str]:
    """Slugs split on `;`, trimmed and without repeats, in the order written."""
    slugs: list[str] = []
    for part in raw.split(SLUG_SEPARATOR):
        slug = part.strip()
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def _check_row(
    row_number: int, record: dict[str, str], seen_ids: dict[str, int], result: ParseResult
) -> None:
    errors: list[RowError] = []

    external_id = (record.get("external_id") or "").strip()
    if not external_id:
        errors.append(RowError(row_number, "external_id", "Enter an ID for this vignette."))
    elif len(external_id) > EXTERNAL_ID_MAX_LENGTH:
        errors.append(
            RowError(
                row_number,
                "external_id",
                f"The ID must be at most {EXTERNAL_ID_MAX_LENGTH} characters.",
            )
        )
    elif external_id in seen_ids:
        errors.append(
            RowError(
                row_number,
                "external_id",
                f"The ID {external_id} is already used on row {seen_ids[external_id]}.",
            )
        )
    else:
        seen_ids[external_id] = row_number

    species = _choice(record.get("species") or "", Species)
    if species is None:
        errors.append(RowError(row_number, "species", "Species must be DOG or CAT."))

    description = (record.get("description") or "").strip()
    if len(description) < DESCRIPTION_MIN_LENGTH:
        errors.append(
            RowError(
                row_number,
                "description",
                f"The description must be at least {DESCRIPTION_MIN_LENGTH} characters.",
            )
        )
    elif len(description) > DESCRIPTION_MAX_LENGTH:
        errors.append(
            RowError(
                row_number,
                "description",
                f"The description must be at most {DESCRIPTION_MAX_LENGTH} characters.",
            )
        )

    category = _choice(record.get("reference_category") or "", VTLCategory)
    if category is None:
        errors.append(
            RowError(
                row_number,
                "reference_category",
                "The reference category must be RED, ORANGE, YELLOW, GREEN or BLUE.",
            )
        )

    if errors or not isinstance(species, Species) or not isinstance(category, VTLCategory):
        result.errors.extend(errors)
        return

    result.vignettes.append(
        ParsedVignette(
            row=row_number,
            external_id=external_id,
            species=species,
            description=description,
            reference_category=category,
            relevant_slugs=_slugs(record.get("relevant_entry_slugs") or ""),
        )
    )


def parse_vignette_csv(content: bytes) -> ParseResult:
    """Validate a vignette file. `errors` is empty when the file is usable."""
    result = ParseResult()

    if len(content) > MAX_FILE_BYTES:
        limit_mb = MAX_FILE_BYTES // (1024 * 1024)
        result.errors.append(RowError(FILE_ROW, None, f"The file is larger than {limit_mb} MB."))
        return result

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        result.errors.append(RowError(FILE_ROW, None, "The file must be UTF-8 text."))
        return result

    lines = _NumberedLines(io.StringIO(text, newline=""))
    reader = csv.DictReader(lines)
    header = [name.strip() for name in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        result.errors.append(RowError(1, None, f"The header row is missing: {', '.join(missing)}."))
        return result
    reader.fieldnames = header

    seen_ids: dict[str, int] = {}
    rows = 0
    try:
        while True:
            lines.start_record()
            record = next(reader, None)
            if record is None:
                break
            rows += 1
            if rows > MAX_ROWS:
                result.errors.append(
                    RowError(lines.record_start, None, f"The file has more than {MAX_ROWS} rows.")
                )
                break
            _check_row(
                lines.record_start,
                {key: value or "" for key, value in record.items() if key},
                seen_ids,
                result,
            )
    except csv.Error as error:
        result.errors.append(RowError(lines.line, None, f"The file is not valid CSV: {error}."))
        return result

    if rows == 0 and not result.errors:
        result.errors.append(RowError(FILE_ROW, None, "The file has no vignettes."))
    return result


class _NumberedLines:
    """Feeds lines to the CSV reader and remembers where the current record began.

    The reader's own `line_num` is where a record *ended*. A description in quotes
    may span several lines, so the row an administrator needs to find is the line
    it started on: the first non-blank line pulled after `start_record()`.
    """

    def __init__(self, source: io.StringIO) -> None:
        self._source = source
        self.line = 0
        self.record_start = 0
        self._waiting = False

    def start_record(self) -> None:
        self._waiting = True

    def __iter__(self) -> "_NumberedLines":
        return self

    def __next__(self) -> str:
        line = next(self._source)
        self.line += 1
        if self._waiting and line.strip():
            self.record_start = self.line
            self._waiting = False
        return line
