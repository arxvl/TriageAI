"""Composing the per-case audit timeline (FR-42, FR-45, FR-46, W-07).

The timeline's spine is `audit_log`, because that is the only record the database
will not let anyone change (FR-43, ADR-12) — a timeline assembled from the
domain tables alone could be made to look different by a later write, which
would defeat the point of showing it.

But the log deliberately does not hold everything the screen prints. Audit
payloads carry identifiers, categories, statuses and counts and never clinical
free text, so a reviewer's reason — which W-07 shows in quotes beside the
decision — has to come from `staff_decisions`. And storing an extraction writes
no audit entry at all: the pipeline audits the start of its run and the
recommendation it ends with, so "Extraction v1 stored" is derived from
`extraction_results`. That is what P06 §6.1 means by building the timeline from
`audit_log` *and the related tables*.

Pure composition: rows in, schema objects out. No session, no I/O.

The wording here is English, like every other string the API returns. The stable
`action` code travels with each item so a translated interface can substitute its
own label later without the server having to produce one (NFR-27).
"""

import uuid
from datetime import datetime

from sqlalchemy import Row

from app.models import DecisionType, UserRole
from app.repositories.review_repository import TimingMarks
from app.schemas.review import AuditTimeline, AuditTimelineItem
from app.services.audit_service import AuditAction

# An extraction has a row but no audit entry of its own, so its timeline items
# carry a marker rather than an `AuditAction` value. Prefixed the same way so a
# client can treat `action` as one namespace.
EXTRACTION_STORED = "EXTRACTION_STORED"

# What each event is called on screen. An action with no entry here still
# appears, labelled with its own code — a new audit action must never make a
# case's history unreadable just because this table was not updated.
LABELS: dict[str, str] = {
    AuditAction.CASE_CREATED: "Case created",
    AuditAction.PIPELINE_STARTED: "AI processing started",
    AuditAction.RED_FLAG_ALERT: "Red-flag pre-screen",
    EXTRACTION_STORED: "Extraction stored",
    AuditAction.RECOMMENDATION_CREATED: "Recommendation created",
    AuditAction.PIPELINE_FAILED: "AI processing failed",
    AuditAction.PIPELINE_RETRY: "AI processing retried",
    AuditAction.ACTIONS_SUGGESTED: "Suggested actions ready",
    AuditAction.ACTIONS_FAILED: "Suggested actions unavailable",
    AuditAction.DECISION_RECORDED: "Decision recorded",
    AuditAction.ACTIONS_FINALIZED: "Action list finalized",
    AuditAction.NOTE_ADDED: "Note added",
    AuditAction.CASE_CLOSED: "Case closed",
}

# How a decision reads in the timeline's label.
DECISION_LABELS: dict[DecisionType, str] = {
    DecisionType.CONFIRM: "Decision: confirmed",
    DecisionType.ADJUST: "Decision: adjusted",
    DecisionType.MANUAL: "Decision: manually triaged",
}


def build_timeline(
    *,
    entries: list[Row],
    extractions: list[Row],
    decisions: list[Row],
    reference_counts: dict[uuid.UUID, int],
    marks: TimingMarks,
) -> AuditTimeline:
    """Merge the audit entries and the derived items into one ordered timeline.

    Ordered by timestamp, with audit entries winning a tie. An audit entry is
    written in the same transaction as the row it describes, so the two can share
    a timestamp; the log is the authoritative record, so it reads first.
    """
    items = [_from_audit(entry, decisions, reference_counts) for entry in entries]
    items += [_from_extraction(row) for row in extractions]
    items.sort(key=lambda item: (item.ts, item.action != EXTRACTION_STORED))

    return AuditTimeline(
        items=items,
        submission_to_recommendation_s=_seconds(marks.submitted_at, marks.first_recommendation_at),
        recommendation_to_decision_s=_seconds(
            marks.first_recommendation_at, marks.first_decision_at
        ),
    )


def _from_audit(
    entry: Row, decisions: list[Row], reference_counts: dict[uuid.UUID, int]
) -> AuditTimelineItem:
    """One audit entry as a timeline item."""
    action = str(entry.action)
    after = entry.after or {}

    label = LABELS.get(action, action)
    details = _details(action, after, entry.before or {}, decisions, reference_counts)

    if action == AuditAction.DECISION_RECORDED:
        decision = _decision_for(after, decisions)
        if decision is not None:
            label = DECISION_LABELS.get(DecisionType(decision.type), label)

    return AuditTimelineItem(
        ts=entry.ts,
        actor_name=entry.actor_name,
        actor_role=None if entry.role is None else UserRole(entry.role),
        action=action,
        label=label,
        details=details,
    )


def _from_extraction(row: Row) -> AuditTimelineItem:
    """One stored extraction as a timeline item.

    No actor: the extraction is the pipeline's own output. A *corrected*
    extraction is a reviewer's work, but correction is P07 and will write its own
    audit entry; until then `is_corrected` only ever says so about a row this
    version of the system did not create.
    """
    parts = [f"Prompt {row.prompt_version}"]
    if row.is_corrected:
        parts.append("corrected by a reviewer")
    return AuditTimelineItem(
        ts=row.created_at,
        actor_name=None,
        actor_role=None,
        action=EXTRACTION_STORED,
        label=f"Extraction v{row.version} stored",
        details=" · ".join(parts),
    )


def _details(
    action: str,
    after: dict,
    before: dict,
    decisions: list[Row],
    reference_counts: dict[uuid.UUID, int],
) -> str | None:
    """The short sentence beside one event, or None when the label says it all."""
    if action == AuditAction.CASE_CREATED:
        return _joined(
            _channel(after.get("intake_channel")),
            _species(after.get("species")),
        )

    if action == AuditAction.RED_FLAG_ALERT:
        rule = after.get("rule_code")
        minimum = after.get("min_category")
        if rule is None:
            return None
        return _joined(str(rule), None if minimum is None else f"at least {minimum}")

    if action == AuditAction.RECOMMENDATION_CREATED:
        return _recommendation_details(after, reference_counts)

    if action == AuditAction.PIPELINE_FAILED:
        reason = after.get("reason")
        return None if reason is None else f"Reason: {reason}"

    if action == AuditAction.DECISION_RECORDED:
        return _decision_details(after, before, decisions)

    if action == AuditAction.ACTIONS_FINALIZED:
        return _actions_finalized_details(after)

    if action in (AuditAction.ACTIONS_SUGGESTED, AuditAction.ACTIONS_FAILED):
        return _actions_details(after)

    if action == AuditAction.NOTE_ADDED:
        return "Recorded with the decision" if after.get("with_decision") else None

    if action == AuditAction.PIPELINE_STARTED:
        model = after.get("model_id")
        return None if model is None else f"Model {model}"

    return None


def _recommendation_details(after: dict, reference_counts: dict[uuid.UUID, int]) -> str | None:
    """ "ORANGE · Confidence Medium · 2 references · safety floor applied"."""
    parts: list[str] = []
    category = after.get("category")
    if category is not None:
        parts.append(str(category))
    confidence = after.get("confidence")
    if confidence is not None:
        parts.append(f"Confidence {str(confidence).title()}")

    count = _reference_count(after, reference_counts)
    if count is not None:
        parts.append(f"{count} reference{'' if count == 1 else 's'}")

    if after.get("safety_floor_applied"):
        rules = after.get("safety_floor_rule_codes") or []
        applied = "safety floor applied"
        if isinstance(rules, list) and rules:
            applied = f"{applied} ({', '.join(str(rule) for rule in rules)})"
        parts.append(applied)

    return " · ".join(parts) or None


def _reference_count(after: dict, reference_counts: dict[uuid.UUID, int]) -> int | None:
    """How many passages this recommendation retrieved.

    The audit payload records how many the model *cited*, not how many were
    retrieved, so the count comes from `retrieved_references` — the number W-07
    prints is the size of the reference list the reviewer can open.
    """
    recommendation_id = _as_uuid(after.get("recommendation_id"))
    if recommendation_id is None:
        return None
    return reference_counts.get(recommendation_id)


def _decision_details(after: dict, before: dict, decisions: list[Row]) -> str | None:
    """ "Orange → Red (up-triage) · reason: …", with the reviewer's own words.

    The reason text is read from the decision row, never from the audit payload:
    it is clinical free text and the log does not hold it (ADR-12).
    """
    parts: list[str] = []

    was = before.get("category")
    now = after.get("category")
    if was is not None and now is not None and was != now:
        parts.append(f"{str(was).title()} → {str(now).title()}")
    elif now is not None:
        parts.append(str(now).title())

    movement = _movement(after.get("direction"))
    if movement is not None:
        parts.append(movement)

    decision = _decision_for(after, decisions)
    if decision is not None:
        if decision.amends_id is not None:
            parts.append("amends an earlier decision")
        if decision.reason_code is not None:
            parts.append(f"reason: {decision.reason_code}")
        if decision.reason_text:
            parts.append(f"“{decision.reason_text}”")

    return " · ".join(parts) or None


def _actions_finalized_details(after: dict) -> str | None:
    """ "5 actions · 4 kept, 1 removed" — counts only, never an action's text."""
    total = after.get("total")
    counts = after.get("counts_by_status")
    parts: list[str] = []
    if isinstance(total, int):
        parts.append(f"{total} action{'' if total == 1 else 's'}")
    if isinstance(counts, dict) and counts:
        breakdown = ", ".join(
            f"{value} {str(key).lower()}" for key, value in sorted(counts.items())
        )
        parts.append(breakdown)
    return " · ".join(parts) or None


def _actions_details(after: dict) -> str | None:
    """The suggested-actions job's own tally, as the pipeline recorded it."""
    parts: list[str] = []
    baseline = after.get("baseline_count")
    tailored = after.get("tailored_count")
    rejected = after.get("rejected_count")
    if isinstance(baseline, int):
        parts.append(f"{baseline} baseline")
    if isinstance(tailored, int):
        parts.append(f"{tailored} AI-suggested")
    if isinstance(rejected, int) and rejected:
        parts.append(f"{rejected} withheld by the safety check")
    reason = after.get("reason")
    if reason is not None:
        parts.append(f"Reason: {reason}")
    return " · ".join(parts) or None


def _decision_for(after: dict, decisions: list[Row]) -> Row | None:
    """The decision row an audit entry is about, by the id it recorded."""
    decision_id = _as_uuid(after.get("decision_id"))
    if decision_id is None:
        return None
    return next((row for row in decisions if row.id == decision_id), None)


def _movement(direction: object) -> str | None:
    """ "up-triage" / "down-triage", or nothing when the category did not move."""
    if direction == "UP":
        return "up-triage"
    if direction == "DOWN":
        return "down-triage"
    return None


def _channel(value: object) -> str | None:
    if value is None:
        return None
    return f"channel: {str(value).replace('_', '-').lower()}"


def _species(value: object) -> str | None:
    return None if value is None else str(value).title()


def _joined(*parts: str | None) -> str | None:
    present = [part for part in parts if part]
    return " · ".join(present) or None


def _as_uuid(value: object) -> uuid.UUID | None:
    """Parse an identifier out of a JSONB payload, or None if it is not one."""
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    """The interval between two instants in seconds, or None if either is absent.

    Never negative: a clock adjustment between two writes should report 0 rather
    than a negative duration that would read as the decision preceding the
    recommendation.
    """
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())
