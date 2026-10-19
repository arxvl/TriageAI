"""The two YAML file formats the knowledge-base importer reads (P08 §8.2, FR-56).

`knowledge_base/entries/<slug>.yaml` is one clinical entry;
`knowledge_base/red_flags.yaml` is every red-flag rule. Both are curated by hand
and committed to the repository — FR-55 forbids fetching knowledge-base content
from anywhere at run time, so a file in the repository is the only way content
arrives in bulk.

Four things here are deliberate.

**The bounds come from `schemas/kb.py`, not from a second copy.** `SLUG_PATTERN`,
`RULE_CODE_PATTERN`, the 50–1,500 word content rule and `word_count` are imported
from the API schemas, so a file the importer accepts is an entry W-08 would also
accept. If they diverged, an entry could be imported that could never be
submitted.

**`extra="forbid"` on every model.** A misspelled key in a curated file is a
silent omission otherwise: `red_flag_code:` would import an entry citing no rule
at all. Forbidding unknown keys turns that into a reported error naming the key.
It is also what keeps `kind:` and `urgency_category:` out until subphase 8.2b
adds urgency-action import (ADR-18).

**A rule file imports placeholder rules.** `is_placeholder` defaults to `True`:
a rule that arrived from a file has not been through the approval workflow, and
the flag is exactly what keeps it out of `get_active_rules` outside development
(NFR-08, BR-04). Approval is a person's act in W-08, never a line in a file.

**Errors are values, not exceptions.** `parse_entry_file` returns `FileError`
rows so the importer can report *every* problem in *every* file in one run, which
is what P08 §8.2 asks for ("Report every error with its file and field").

Nothing in this module touches a session or the network: it parses text
(CLAUDE.md §7).
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.validation_messages import field_from_location, plain_message
from app.models.enums import Species, VTLCategory
from app.schemas.kb import (
    CONTENT_MAX_LENGTH,
    RULE_CODE_PATTERN,
    SLUG_PATTERN,
    require_word_count,
)

__all__ = [
    "ENTRY_FILE_GLOB",
    "ENTRY_SUBDIR",
    "FileError",
    "KBEntryFile",
    "RULES_FILENAME",
    "RedFlagRuleFile",
    "RedFlagRulesFile",
    "SourceBlock",
    "parse_entry_file",
    "parse_rules_file",
]

# Where the importer looks, relative to the knowledge-base directory.
ENTRY_SUBDIR = "entries"
ENTRY_FILE_GLOB = "*.yaml"
RULES_FILENAME = "red_flags.yaml"


@dataclass(frozen=True)
class FileError:
    """One problem in one file, as the importer prints it.

    `field` is the dotted path inside the document (`source.url`, `rules.3.code`)
    or `None` for a problem with the file as a whole — unreadable YAML, or a
    document that is not a mapping.
    """

    path: Path
    field: str | None
    message: str

    def line(self) -> str:
        where = f"{self.path.name}" + (f" [{self.field}]" if self.field else "")
        return f"  {where}: {self.message}"


# --- The formats ----------------------------------------------------------


class SourceBlock(BaseModel):
    """The published source an entry was written from (FR-50).

    All four fields are required. An entry nobody can trace back to a
    veterinarian-authored source must not be importable, let alone approvable
    (BR-04).
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=1_000)
    access_date: date

    @field_validator("title", "publisher", "url", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KBEntryFile(BaseModel):
    """`knowledge_base/entries/<slug>.yaml` — one COMPLAINT entry.

    `kind` and `urgency_category` are absent on purpose and rejected by
    `extra="forbid"`: this subphase imports clinical entries only, and the five
    `URGENCY_ACTIONS` sets arrive with 8.2b (ADR-18).

    `complaint_code` is checked for *shape* here and for *existence* by the
    importer, which is the only side with a database.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=120, pattern=SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=300)
    complaint_code: str = Field(min_length=1, max_length=64)
    species: list[Species] = Field(min_length=1)
    content: str = Field(min_length=1, max_length=CONTENT_MAX_LENGTH)
    source: SourceBlock
    red_flag_codes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("slug", "title", "complaint_code", "content", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        """Trimmed before the length and pattern checks, so blanks fail."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def _bounded_words(cls, value: str) -> str:
        return require_word_count(value)

    @field_validator("species")
    @classmethod
    def _unique_species(cls, value: list[Species]) -> list[Species]:
        return list(dict.fromkeys(value))

    @field_validator("red_flag_codes")
    @classmethod
    def _unique_codes(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(code.strip() for code in value))


class RedFlagRuleFile(BaseModel):
    """One rule in `knowledge_base/red_flags.yaml` (FR-12, FR-23, NFR-08).

    The phrases are *not* here. They live in `red_flag_phrases.yaml`, keyed by
    `phrases_ref`, and are maintained by hand (M1): the categories belong in the
    database so the safety floor has one source of truth, and duplicating the
    phrase lists into rows would give it two.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100, pattern=RULE_CODE_PATTERN)
    label: str = Field(min_length=1, max_length=300)
    min_category: VTLCategory
    species: list[Species] = Field(min_length=1)
    phrases_ref: str | None = Field(default=None, max_length=100)
    # True unless the file says otherwise: see the module docstring.
    is_placeholder: bool = True

    @field_validator("code", "label", "phrases_ref", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("species")
    @classmethod
    def _unique_species(cls, value: list[Species]) -> list[Species]:
        return list(dict.fromkeys(value))


class RedFlagRulesFile(BaseModel):
    """The whole `red_flags.yaml` document."""

    model_config = ConfigDict(extra="forbid")

    rules: list[RedFlagRuleFile] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def _unique_rule_codes(cls, value: list[RedFlagRuleFile]) -> list[RedFlagRuleFile]:
        """Two rules with one code would make the upsert order decide the winner."""
        seen: set[str] = set()
        for rule in value:
            if rule.code in seen:
                raise ValueError(f"the rule code {rule.code} appears more than once in this file")
            seen.add(rule.code)
        return value


# --- Parsing --------------------------------------------------------------

# Pydantic's name for a key the model does not declare. Given its own wording
# because the registered message for the *declared* field of that name would be
# actively misleading — "kind" would answer "Choose the entry kind".
_EXTRA_FORBIDDEN = "extra_forbidden"


def _load_mapping(path: Path) -> tuple[dict | None, FileError | None]:
    """The YAML document as a mapping, or the error to report instead."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        return None, FileError(path, None, f"could not be read ({error.strerror}).")
    except yaml.YAMLError as error:
        # A parse error carries a line and column; the message is the useful
        # part and `str(error)` already includes both.
        return None, FileError(path, None, f"is not valid YAML: {error}")
    if document is None:
        return None, FileError(path, None, "is empty.")
    if not isinstance(document, dict):
        return None, FileError(path, None, "must be a mapping of field names to values.")
    return document, None


def _errors_from(path: Path, error: ValidationError) -> list[FileError]:
    """One `FileError` per problem, with the plain wording where there is one."""
    reported = []
    for detail in error.errors():
        field = field_from_location(detail["loc"])
        if detail["type"] == _EXTRA_FORBIDDEN:
            message = "is not a field of this file format. Remove it."
        else:
            message = plain_message(field, detail["type"]) or detail["msg"]
        reported.append(FileError(path, field, message))
    return reported


def parse_entry_file(path: Path) -> tuple[KBEntryFile | None, list[FileError]]:
    """Parse one entry file. Either the entry, or every problem with it.

    The `slug` has to equal the filename: the filename is what a curator reads
    in a directory listing and what a reviewer names in `APPROVALS.md`, and a
    file whose two names disagree would be upserted under the one nobody looked
    at.
    """
    document, failure = _load_mapping(path)
    if failure is not None:
        return None, [failure]

    try:
        entry = KBEntryFile.model_validate(document)
    except ValidationError as error:
        return None, _errors_from(path, error)

    if entry.slug != path.stem:
        return None, [
            FileError(
                path,
                "slug",
                f"is {entry.slug!r} but the file is named {path.stem!r}. "
                f"Rename the file or change the slug so the two match.",
            )
        ]
    return entry, []


def parse_rules_file(path: Path) -> tuple[list[RedFlagRuleFile], list[FileError]]:
    """Parse the rules file. Either every rule, or every problem with it."""
    document, failure = _load_mapping(path)
    if failure is not None:
        return [], [failure]

    try:
        parsed = RedFlagRulesFile.model_validate(document)
    except ValidationError as error:
        return [], _errors_from(path, error)
    return parsed.rules, []
