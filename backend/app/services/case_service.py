"""Case intake and the Triage Queue (FR-01..FR-07, FR-29, FR-30, FR-36, FR-39).

The service owns the rules a caller must not be able to skip: the dog-and-cat
restriction, the single transaction that keeps a case and its description
together, the audit entry, and the waiting-time arithmetic the queue is judged
on. It raises `AppError` subclasses and knows nothing about HTTP (CLAUDE.md §7).

`now` is injectable so the waiting-time and overdue tests can place a case at an
exact age instead of sleeping. One `now` is used for every row in a response and
for `generated_at`, so a queue is a consistent snapshot rather than a set of rows
measured a few milliseconds apart.

Submitting a case **enqueues** the triage pipeline in the same transaction as the
case itself, and the case stays in `SUBMITTED` until a worker claims it (FR-06,
ADR-08). One transaction, not two: a commit between the case and its job would
leave a window in which a crash produces a case no worker will ever pick up.

Reading a case also assembles its **suggested actions** (FR-71..FR-79, ADR-18).
Two rules there are the service's and must not be reachable around: the baseline
set is read from the knowledge base for the case's current category rather than
from the stored rows, so it is always present; and unfinalized AI-suggested
actions are returned to Veterinary Reviewers only (FR-79).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import CaseNotFound, InvalidCaseTransition, SpeciesOutOfScope
from app.core.vtl import TARGET_MINUTES, is_overdue, target_minutes
from app.jobs.queue import STAGE_KEY, JobQueue, JobStage
from app.models import (
    ActionSource,
    ActionsStatus,
    AdjustReason,
    CaseStatus,
    ConfidenceLevel,
    DecisionDirection,
    DecisionType,
    IntakeChannel,
    JobStatus,
    JobType,
    Sex,
    Species,
    User,
    UserRole,
    VTLCategory,
)
from app.pipeline.action_validator import baseline_actions
from app.pipeline.messages import (
    actions_failure_message,
    failure_message,
    regeneration_failure_message,
)
from app.repositories.case_repository import (
    CaseRepository,
    OwnerReferenceValues,
    SignalmentValues,
)
from app.repositories.review_repository import ReviewRepository
from app.schemas.case import (
    CaseActionsOut,
    CaseCreate,
    CaseCreated,
    CaseDetail,
    CaseListResponse,
    CaseQueueCounts,
    CaseQueueFilters,
    CaseQueueItem,
    CaseStatusOut,
    QueueCategoryFilter,
    QueueRedFlagAlert,
    SpeciesInput,
    SuggestedActionOut,
)
from app.schemas.review import (
    AlertOut,
    CaseHeaderOut,
    ConfigurationOut,
    DecisionOut,
    DescriptionOut,
    ExtractedComplaintOut,
    ExtractionOut,
    FailureOut,
    NoteOut,
    PermissionsOut,
    RecommendationOut,
    RecommendationVersionDetail,
    RecommendationVersionOut,
    ReferenceOut,
    RetryAccepted,
    SafetyFloorRuleOut,
)
from app.services.audit_service import CASE_ENTITY, AuditAction, AuditService
from app.services.case_transitions import (
    ACTIONS_REGENERATION_BLOCKED_STATUSES,
    DECIDED_STATUSES,
)
from app.services.evidence_spans import locate

Clock = Callable[[], datetime]

# Intake channel is optional on the form (FR-01) but not null in the table. A
# case entered on the intake screen is someone standing at the counter unless
# they say otherwise.
DEFAULT_INTAKE_CHANNEL = IntakeChannel.WALK_IN


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CaseService:
    def __init__(
        self,
        session: Session,
        *,
        now: Clock | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._cases = CaseRepository(session)
        self._reviews = ReviewRepository(session)
        self._jobs = JobQueue(session)
        self._audit = AuditService(session)
        self._now = now or _utc_now
        self._display_timezone = ZoneInfo((settings or get_settings()).tz_display)

    # --- Intake -----------------------------------------------------------

    def create_case(self, payload: CaseCreate, user: User) -> CaseCreated:
        """Create a case in `SUBMITTED` and return its number (FR-01, FR-03).

        Dogs and cats only (FR-02, BR-06). The check comes first, so an
        out-of-scope case leaves nothing behind at all — no row, no case number,
        no audit entry. Those cases are triaged on paper by clinic procedure, and
        a half-created record of one would be worse than none.

        The case, its signalment, its description and its owner reference are one
        transaction. A case without its description would be unrecoverable:
        `owner_descriptions.text` cannot be inserted later by an update (FR-05).
        """
        if payload.species is SpeciesInput.OTHER:
            raise SpeciesOutOfScope()

        species = Species(payload.species.value)
        intake_channel = payload.intake_channel or DEFAULT_INTAKE_CHANNEL
        arrived_at = self._now()

        new_case = self._cases.insert_case(
            case_no=self._cases.next_case_no(),
            species=species,
            intake_channel=intake_channel,
            status=CaseStatus.SUBMITTED,
            created_by=user.id,
            arrived_at=arrived_at,
            description=payload.description,
            signalment=SignalmentValues(
                pet_name=payload.pet_name,
                age_value=payload.age_value,
                age_unit=payload.age_unit,
                # Not null in the table; "not stated" is itself a finding.
                sex=payload.sex or Sex.UNKNOWN,
                neutered=payload.neutered,
                breed=payload.breed,
                weight_kg=payload.weight_kg,
            ),
            owner_reference=(
                OwnerReferenceValues(
                    owner_name=payload.owner_name,
                    contact_number=payload.contact_number,
                )
                if payload.has_owner_reference
                else None
            ),
        )

        # Read before the commit expires the instance, and so the response
        # reports what was actually written.
        created = CaseCreated(id=new_case.id, case_no=new_case.case_no, status=new_case.status)

        # Identifiers, codes and a character count only. The description itself,
        # the owner name and the contact number never reach the audit log, which
        # cannot be corrected afterwards (FR-43, CLAUDE.md §9).
        self._audit.record(
            action=AuditAction.CASE_CREATED,
            entity_type=CASE_ENTITY,
            entity_id=str(created.id),
            user_id=user.id,
            role=user.role,
            after={
                "case_no": created.case_no,
                "species": species.value,
                "intake_channel": intake_channel.value,
                "status": created.status.value,
                "description_char_count": len(payload.description),
                "has_owner_reference": payload.has_owner_reference,
            },
        )

        # The pipeline job, in this same transaction (FR-06, ADR-08). An
        # out-of-scope species returned above, so no job is ever created for a
        # case the AI must not process (FR-02).
        self._jobs.enqueue(JobType.PIPELINE_RUN, case_id=created.id)

        self._session.commit()
        return created

    # --- Retry (P07 §7.1) --------------------------------------------------

    def retry_pipeline(self, case_id: uuid.UUID, user: User) -> RetryAccepted:
        """Queue the pipeline again for a case it gave up on (UC-08, NFR-09).

        Allowed only for a case in `MANUAL_TRIAGE_REQUIRED` that no reviewer has
        decided. The status check is the real guard; the decision check is
        belt-and-braces for a case whose row and decision disagree.

        The case goes back to `SUBMITTED` in the same transaction as the new job,
        so it cannot be decided by hand while the retry is queued — the run would
        write `AWAITING_REVIEW` over that decision — and a second press of Retry
        finds the status already moved and answers 409. Nothing is deleted: the
        earlier `PIPELINE_FAILED` entry stays in the log (ADR-12) and the run
        versions its outputs as it always does (ADR-14).
        """
        current = self._reviews.status_of(case_id)
        if current is None:
            raise CaseNotFound()
        if current is not CaseStatus.MANUAL_TRIAGE_REQUIRED:
            raise InvalidCaseTransition("Only a case waiting for manual triage can be retried.")
        if self._reviews.latest_decision(case_id) is not None:
            raise InvalidCaseTransition(
                "This case already has a decision, so it cannot be retried."
            )

        previous = self._reviews.latest_audit_entry(case_id, AuditAction.PIPELINE_FAILED)
        previous_reason = (previous.after or {}).get("reason") if previous is not None else None

        if not self._reviews.reopen_for_retry(case_id):
            # Somebody else moved the case between the read above and the update.
            self._session.rollback()
            raise InvalidCaseTransition("Only a case waiting for manual triage can be retried.")

        self._jobs.enqueue(JobType.PIPELINE_RUN, case_id=case_id)
        self._audit.record(
            action=AuditAction.PIPELINE_RETRY,
            entity_type=CASE_ENTITY,
            entity_id=str(case_id),
            user_id=user.id,
            role=user.role,
            before={"status": CaseStatus.MANUAL_TRIAGE_REQUIRED.value, "reason": previous_reason},
            after={"status": CaseStatus.SUBMITTED.value},
        )
        accepted = self._reviews.header_row(case_id)
        self._session.commit()
        if accepted is None:  # pragma: no cover - the row was read a moment ago
            raise CaseNotFound()
        return RetryAccepted(id=case_id, case_no=accepted.case_no, status=CaseStatus.SUBMITTED)

    # --- Triage Queue -----------------------------------------------------

    def list_queue(self, filters: CaseQueueFilters) -> CaseListResponse:
        """Open cases in FR-29 order, with the W-02 counters (FR-39).

        Waiting times are computed here rather than in SQL so that every row in
        one response is measured against the same instant, and so a test can
        place a case at an exact age.
        """
        now = self._now()
        created_from, created_to = self._utc_bounds(filters.date_from, filters.date_to)
        # MANUAL is a status, not a VTL category, so the two go to separate
        # arguments and only one of them is ever set.
        manual_only = filters.category is QueueCategoryFilter.MANUAL
        category = None if manual_only else _as_category(filters.category)

        rows = self._cases.queue_rows(
            species=filters.species,
            category=category,
            manual_only=manual_only,
            status=filters.status,
            created_from=created_from,
            created_to=created_to,
            search=filters.q,
            limit=filters.limit,
            offset=filters.offset,
        )

        return CaseListResponse(
            items=[self._to_queue_item(row, now) for row in rows],
            counts=self._queue_counts(),
            # Unfiltered, like the counters: an alert is about a patient who needs
            # someone now, and a filter the user happens to have on must not hide
            # it (FR-12, NFR-05).
            red_flag_alerts=[
                QueueRedFlagAlert(
                    case_id=row.case_id,
                    case_no=row.case_no,
                    species=Species(row.species),
                    pet_name=row.pet_name,
                    rule_code=row.rule_code,
                    rule_label=row.rule_label,
                    min_category=VTLCategory(row.min_category),
                    created_at=row.created_at,
                )
                for row in self._cases.unacknowledged_alerts()
            ],
            generated_at=now,
        )

    def get_status(self, case_id: uuid.UUID) -> CaseStatusOut:
        """What a case looks like right now, for the polling clients (IR-22)."""
        row = self._cases.status_row(case_id)
        if row is None:
            raise CaseNotFound()
        recommendation = self._cases.latest_recommendation_actions(case_id)
        return CaseStatusOut(
            status=CaseStatus(row.status),
            category=_as_category(row.category),
            has_red_flag=row.has_red_flag,
            pipeline_stage=self._pipeline_stage(case_id),
            # Polled alongside the case status, not derived from it: the category
            # is final while the actions are still being suggested (ADR-18 §3).
            actions_status=(
                None if recommendation is None else ActionsStatus(recommendation.actions_status)
            ),
            updated_at=row.updated_at,
        )

    # --- Suggested actions (FR-71..FR-79, ADR-18) --------------------------

    def get_detail(self, case_id: uuid.UUID, user: User) -> CaseDetail:
        """Everything the Case Review screen shows, role-filtered (FR-31, W-04).

        `user` is taken rather than read from a request because two of the rules
        here are business rules, not presentation details, and have to hold
        however this is called (SR-05):

        * a caller who is not a Veterinary Reviewer does not receive
          unfinalized model-suggested actions (FR-79);
        * opening the case **as a reviewer** acknowledges its red-flag alerts,
          which is what clears the W-02 banner (FR-12).

        That second one makes this read have a side effect, which is unusual
        enough to be worth stating: the acknowledgement records that a reviewer
        has seen the alert, and the only moment the system can observe that is
        when they open the case. A read by intake staff or an administrator
        acknowledges nothing — neither of them is the person the alert is
        escalating to (BR-02).
        """
        row = self._cases.detail_row(case_id)
        if row is None:
            raise CaseNotFound()

        header_row = self._reviews.header_row(case_id)
        if header_row is None:
            raise CaseNotFound()

        now = self._now()
        status = CaseStatus(row.status)
        self._acknowledge_alerts(case_id, user, now)

        extraction = self._reviews.latest_extraction(case_id)
        recommendation = self._reviews.latest_recommendation(case_id)
        references = [] if recommendation is None else self._reviews.references(recommendation.id)
        actions = self._actions(case_id, row, user)

        return CaseDetail(
            id=row.id,
            case_no=row.case_no,
            status=status,
            species=Species(row.species),
            category=_as_category(row.category),
            recommended_category=_as_category(row.recommended_category),
            confirmed_category=_as_category(row.confirmed_category),
            has_red_flag=row.has_red_flag,
            created_at=row.created_at,
            actions=actions,
            header=self._header(header_row, _as_category(row.category), now),
            description=self._description(case_id, extraction),
            extraction=None if extraction is None else self._extraction(extraction),
            recommendation=(
                None if recommendation is None else self._recommendation(recommendation)
            ),
            references=[
                ReferenceOut(
                    rank=reference.rank,
                    entry_title=reference.entry_title,
                    source_title=reference.source_title,
                    source_url=reference.source_url,
                    passage_text=reference.passage_text,
                    score=None if reference.score is None else float(reference.score),
                    is_cited=reference.is_cited,
                )
                for reference in references
            ],
            configuration=(None if recommendation is None else self._configuration(recommendation)),
            alerts=[
                AlertOut(
                    rule_code=alert.rule_code,
                    rule_label=alert.rule_label,
                    min_category=VTLCategory(alert.min_category),
                    created_at=alert.created_at,
                    acknowledged_at=alert.acknowledged_at,
                )
                for alert in self._reviews.alerts(case_id)
            ],
            decision=self._decision(case_id, status),
            notes=[
                NoteOut(
                    id=note.id,
                    text=note.text,
                    author_name=note.author_name,
                    created_at=note.created_at,
                )
                for note in self._reviews.notes(case_id)
            ],
            permissions=self._permissions(status, user, actions_status=actions.status),
            failure=self._failure(case_id, status),
            recommendation_versions=self._recommendation_versions(case_id),
            regeneration_failure=self._regeneration_failure(
                case_id, status, extraction, recommendation
            ),
        )

    def get_recommendation_version(
        self, case_id: uuid.UUID, version: int
    ) -> RecommendationVersionDetail:
        """One stored recommendation version, read-only (FR-27, ADR-14).

        What the switcher shows for an older version. Every role that can open
        the case can read it: a version is the record of what was shown, and the
        suggested actions that are visible to reviewers only (FR-79) are not part
        of it.
        """
        if self._reviews.status_of(case_id) is None:
            raise CaseNotFound()
        row = self._reviews.recommendation_by_version(case_id, version)
        if row is None:
            raise CaseNotFound("That recommendation version could not be found.")
        latest = self._reviews.latest_recommendation(case_id)
        return RecommendationVersionDetail(
            recommendation=self._recommendation(row),
            references=[
                ReferenceOut(
                    rank=reference.rank,
                    entry_title=reference.entry_title,
                    source_title=reference.source_title,
                    source_url=reference.source_url,
                    passage_text=reference.passage_text,
                    score=None if reference.score is None else float(reference.score),
                    is_cited=reference.is_cited,
                )
                for reference in self._reviews.references(row.id)
            ],
            configuration=self._configuration(row),
            extraction_version=row.extraction_version,
            is_current=latest is not None and latest.id == row.id,
        )

    # --- The review screen (FR-31, P06 §6.1) ------------------------------

    def _acknowledge_alerts(self, case_id: uuid.UUID, user: User, now: datetime) -> None:
        """Record that a reviewer has seen this case's red-flag alerts (FR-12).

        Committed on its own, before the rest of the response is assembled: the
        acknowledgement is a fact whether or not the read that triggered it
        succeeds, and the alerts the response then reports carry the timestamp
        that was just written rather than disagreeing with it.
        """
        if user.role is not UserRole.VETERINARY_REVIEWER:
            return
        if self._reviews.acknowledge_alerts(case_id, now):
            self._session.commit()

    def _header(self, row: Row, category: VTLCategory | None, now: datetime) -> CaseHeaderOut:
        """The W-04 header, with the waiting time measured against `now`.

        Measured here against the same instant as everything else in this
        response, for the same reason the queue does it: a header that says
        "waiting 6 min of 15 min" and a badge derived from a different clock
        read would be able to disagree.
        """
        waiting_minutes = _minutes_between(row.created_at, now)
        return CaseHeaderOut(
            case_no=row.case_no,
            species=Species(row.species),
            pet_name=row.pet_name,
            age_value=float(row.age_value) if row.age_value is not None else None,
            age_unit=row.age_unit,
            sex=Sex(row.sex) if row.sex is not None else Sex.UNKNOWN,
            neutered=row.neutered,
            breed=row.breed,
            weight_kg=float(row.weight_kg) if row.weight_kg is not None else None,
            intake_channel=IntakeChannel(row.intake_channel),
            created_at=row.created_at,
            created_by_name=row.created_by_name,
            closed_at=row.closed_at,
            waiting_minutes=waiting_minutes,
            target_minutes=target_minutes(category),
            is_overdue=is_overdue(category, waiting_minutes),
        )

    def _description(self, case_id: uuid.UUID, extraction: Row | None) -> DescriptionOut:
        """Panel 1: the verbatim description and the text the pipeline read.

        A case always has a description — it cannot be created without one
        (FR-05) — but it may not have an extraction yet, and an extraction
        written before migration 0004 has no stored de-identified text. Either
        way `deidentified_text` is None and the screen shows the original with
        no highlights.
        """
        text = self._reviews.description(case_id) or ""
        deidentified = None if extraction is None else extraction.input_text
        return DescriptionOut(
            text=text,
            deidentified_text=deidentified,
            differs=deidentified is not None and deidentified != text,
        )

    def _extraction(self, row: Row) -> ExtractionOut:
        """Panel 2: the extracted information, with located evidence spans.

        `entities` is the whole `ExtractionOutput` contract object as stored, so
        the fields are read out of it by name. A missing or mistyped key reads as
        absent rather than raising: this response is how a reviewer sees a case
        at all, and one malformed value must not take the screen down.
        """
        entities = row.entities if isinstance(row.entities, dict) else {}
        complaints = self._reviews.extraction_complaints(row.id)

        return ExtractionOut(
            id=row.id,
            version=row.version,
            is_corrected=row.is_corrected,
            corrected_by_name=row.corrected_by_name,
            species=_as_species(entities.get("species")),
            presenting_complaints=[
                ExtractedComplaintOut(
                    code=complaint.code,
                    name=complaint.name,
                    is_primary=complaint.is_primary,
                )
                for complaint in complaints
            ],
            onset_duration=_as_text(entities.get("onset_duration")),
            frequency_severity=_as_text(entities.get("frequency_severity")),
            associated_signs=_as_text_list(entities.get("associated_signs")),
            negated_findings=_as_text_list(entities.get("negated_findings")),
            exposure_history=_as_text(entities.get("exposure_history")),
            relevant_history=_as_text(entities.get("relevant_history")),
            red_flags=_as_text_list(row.red_flags),
            missing_information=_as_text_list(row.missing_information),
            evidence_spans=locate(entities.get("evidence_spans"), row.input_text),
            created_at=row.created_at,
        )

    def _recommendation(self, row: Row) -> RecommendationOut:
        """Panel 3: the recommendation after the safety validator (ADR-09).

        The safety-floor rules are resolved to the clinic's own labels, because
        W-04 names the rule in words and `MALE_CAT_NO_URINE` is not a sentence
        (IR-03). A code whose rule row has since been removed keeps the code and
        reports a null label rather than disappearing from the notice.
        """
        category = VTLCategory(row.category)
        codes = _as_text_list(row.safety_floor_rule_codes)
        labels = self._reviews.rule_labels(codes)
        return RecommendationOut(
            id=row.id,
            version=row.version,
            category=category,
            target_minutes=TARGET_MINUTES[category],
            rationale=row.rationale,
            confidence=ConfidenceLevel(row.confidence),
            safety_floor_applied=row.safety_floor_applied,
            safety_floor_rules=[
                SafetyFloorRuleOut(code=code, label=labels.get(code)) for code in codes
            ],
            low_confidence_reasons=_as_text_list(row.low_confidence_reasons),
            created_at=row.created_at,
        )

    def _configuration(self, row: Row) -> ConfigurationOut:
        """The provenance footnote: what produced this recommendation (FR-26)."""
        return ConfigurationOut(
            model_id=row.model_id,
            prompt_version=row.prompt_version,
            kb_version_no=row.kb_version_no,
            generated_at=row.created_at,
            latency_ms=row.latency_ms,
        )

    def _decision(self, case_id: uuid.UUID, status: CaseStatus) -> DecisionOut | None:
        """The latest decision on this case, if a reviewer has made one."""
        row = self._reviews.latest_decision(case_id)
        if row is None:
            return None
        category = VTLCategory(row.final_category)
        return DecisionOut(
            id=row.id,
            type=DecisionType(row.type),
            final_category=category,
            target_minutes=TARGET_MINUTES[category],
            reason_code=None if row.reason_code is None else AdjustReason(row.reason_code),
            reason_text=row.reason_text,
            direction=DecisionDirection(row.direction),
            decided_by_name=row.decided_by_name,
            decided_at=row.decided_at,
            amends_id=row.amends_id,
            status=status,
        )

    def _permissions(
        self, status: CaseStatus, user: User, *, actions_status: ActionsStatus | None
    ) -> PermissionsOut:
        """What this caller may do with this case (BR-02, SR-05).

        A description of the server's rules so the screen can hide controls
        rather than offer buttons that answer 403 or 409 — never the enforcement
        itself, which is `require_role` and `ReviewService`.

        `can_decide` stays true on a case that is already decided, because a
        reviewer may still record an amendment (FR-48). It goes false only when
        the case is closed.
        """
        is_reviewer = user.role is UserRole.VETERINARY_REVIEWER
        return PermissionsOut(
            can_decide=is_reviewer and status is not CaseStatus.CLOSED,
            # P07 §7.2: a correction is refused once a decision exists, and while
            # a regeneration is running the case is `PROCESSING`. `correct_extraction`
            # enforces the same rule.
            can_regenerate=is_reviewer and status is CaseStatus.AWAITING_REVIEW,
            # W-06's Retry (P07 §7.1): only a reviewer, only while the case is
            # waiting on a failed run. `retry_pipeline` enforces the same rule.
            can_retry=is_reviewer and status is CaseStatus.MANUAL_TRIAGE_REQUIRED,
            # P07 §7.2b: there must be a recommendation (`actions_status` is None
            # without one), the case must have settled on a category, and no
            # actions job may be running. `regenerate_actions` enforces the same.
            can_regenerate_actions=(
                is_reviewer
                and status not in ACTIONS_REGENERATION_BLOCKED_STATUSES
                and actions_status is not None
                and actions_status is not ActionsStatus.PENDING
            ),
            can_close=is_reviewer and status in DECIDED_STATUSES,
        )

    def _failure(self, case_id: uuid.UUID, status: CaseStatus) -> FailureOut | None:
        """Why this case is waiting to be triaged by hand, for W-06 (NFR-09).

        Only for `MANUAL_TRIAGE_REQUIRED`, which is the one status that means
        "the pipeline gave up and nobody has decided yet". A `PIPELINE_FAILED`
        entry is never removed — the log is append-only (ADR-12) — so a case that
        failed, was retried in P07 and succeeded still has one, and reporting it
        would put "AI unavailable" on a screen showing a perfectly good
        recommendation.

        Read from the audit entry rather than from `jobs.last_error`, which
        stores the reason and the time as one interpolated string
        (`JobQueue.fail`). The audit payload has them as separate values, so
        nothing here has to parse prose. `failed_at` falls back to the entry's own
        timestamp: the two are written in the same breath, and a missing or
        unreadable payload value must not cost the reviewer the whole banner.
        """
        if status is not CaseStatus.MANUAL_TRIAGE_REQUIRED:
            return None

        entry = self._reviews.latest_audit_entry(case_id, AuditAction.PIPELINE_FAILED)
        if entry is None:
            return None

        payload = entry.after or {}
        reason = payload.get("reason")
        if not isinstance(reason, str) or reason == "":
            return None

        failed_at = _parse_iso(payload.get("failed_at")) or entry.ts
        attempts = payload.get("attempts")
        return FailureOut(
            reason_code=reason,
            message=failure_message(
                reason,
                attempts=attempts if isinstance(attempts, int) else None,
                failed_at=failed_at,
                tz=str(self._display_timezone),
            ),
            failed_at=failed_at,
        )

    def _recommendation_versions(self, case_id: uuid.UUID) -> list[RecommendationVersionOut]:
        """Every recommendation version, oldest first, the newest marked current (FR-27)."""
        rows = self._reviews.recommendation_versions(case_id)
        return [
            RecommendationVersionOut(
                version=row.version,
                category=VTLCategory(row.category),
                created_at=row.created_at,
                is_current=index == len(rows) - 1,
            )
            for index, row in enumerate(rows)
        ]

    def _regeneration_failure(
        self,
        case_id: uuid.UUID,
        status: CaseStatus,
        extraction: Row | None,
        recommendation: Row | None,
    ) -> FailureOut | None:
        """Why the last regeneration failed, while it is still the latest thing (P07 §7.2).

        Only for a case awaiting review whose newest extraction has no
        recommendation made from it, and whose newest `REGENERATE_FAILED` entry
        is about that extraction. Matching on the extraction rather than on
        timestamps is what lets a failure stop showing once a retry succeeds (the
        newest extraction then has its recommendation), while the entry itself
        stays in the append-only log (ADR-12).
        """
        if status is not CaseStatus.AWAITING_REVIEW or extraction is None or recommendation is None:
            return None
        if extraction.id == recommendation.extraction_id:
            return None
        entry = self._reviews.latest_audit_entry(case_id, AuditAction.REGENERATE_FAILED)
        if entry is None:
            return None

        payload = entry.after or {}
        if payload.get("extraction_id") != str(extraction.id):
            return None
        reason = payload.get("reason")
        if not isinstance(reason, str) or reason == "":
            return None
        failed_at = _parse_iso(payload.get("failed_at")) or entry.ts
        attempts = payload.get("attempts")
        return FailureOut(
            reason_code=reason,
            message=regeneration_failure_message(
                reason,
                attempts=attempts if isinstance(attempts, int) else None,
                failed_at=failed_at,
                tz=str(self._display_timezone),
            ),
            failed_at=failed_at,
        )

    def _actions(self, case_id: uuid.UUID, row: Row, user: User) -> CaseActionsOut:
        """Assemble the two action layers for one case.

        The baseline set is looked up live, for the case's *current* category,
        and never read from the stored rows — see `CaseActionsOut`. That is what
        makes it survive a failed actions job (FR-77) and follow a reviewer who
        changes the category (ADR-18 §6). The stored `BASELINE` rows remain the
        record of what was first suggested, which is what P06 finalizes against.
        """
        recommendation = self._cases.latest_recommendation_actions(case_id)
        category = _as_category(row.category)
        suggestions = (
            [] if recommendation is None else self._cases.action_suggestions(recommendation.id)
        )

        # What the tailored actions were generated for: the stored value when
        # there are rows, otherwise the category of the recommendation they will
        # be generated for.
        generated_for = next(
            (_as_category(suggestion.generated_for_category) for suggestion in suggestions),
            None if recommendation is None else _as_category(recommendation.category),
        )
        confirmed = _as_category(row.confirmed_category)
        # FR-78: a decision on another category leaves the tailored list
        # describing an urgency the case no longer has. Every row of a set is
        # generated for the same category, so the flag is one value per response.
        is_outdated = (
            confirmed is not None and generated_for is not None and confirmed is not generated_for
        )

        return CaseActionsOut(
            status=(
                None if recommendation is None else ActionsStatus(recommendation.actions_status)
            ),
            generated_for_category=generated_for,
            baseline=self._baseline(category, recommendation),
            # FR-79. No `final_actions` row exists before P06, so every stored
            # suggestion is unfinalized and a non-reviewer sees none of them.
            tailored=(
                [
                    SuggestedActionOut(
                        text=suggestion.text,
                        cited_ranks=_cited_ranks(suggestion.cited_chunk_ids),
                        source=ActionSource(suggestion.source),
                        is_outdated=is_outdated,
                    )
                    for suggestion in suggestions
                    if ActionSource(suggestion.source) is not ActionSource.BASELINE
                ]
                if user.role is UserRole.VETERINARY_REVIEWER
                else []
            ),
            rejected_count=(0 if recommendation is None else recommendation.actions_rejected_count),
            is_outdated=is_outdated,
            failure_message=self._actions_failure_message(recommendation),
        )

    @staticmethod
    def _actions_failure_message(recommendation: Row | None) -> str | None:
        """The plain-language line for a failed actions job, or None (FR-77).

        The reason code is stored on the recommendation and the sentence is made
        here, as for a failed pipeline run (`failure_message`), so every screen
        says the same thing. Only a `FAILED` status has one: a job that is
        pending or finished has nothing to apologise for.
        """
        if recommendation is None or ActionsStatus(recommendation.actions_status) is not (
            ActionsStatus.FAILED
        ):
            return None
        code = recommendation.actions_error
        return actions_failure_message(code if isinstance(code, str) else "")

    def _baseline(self, category: VTLCategory | None, recommendation: Row | None) -> list[str]:
        """The baseline actions for one category (FR-71, FR-72).

        Pinned to the knowledge-base version the recommendation used, so
        reopening an old case shows the set as it was then (FR-54, ADR-14). A
        case with no recommendation — one a reviewer triaged by hand — is read
        against the newest version instead, because it still has a category and
        so still has baseline actions.
        """
        if category is None:
            return []
        kb_version_id = None if recommendation is None else recommendation.kb_version_id
        if kb_version_id is None:
            kb_version_id = self._cases.latest_kb_version_id()
        if kb_version_id is None:
            return []
        return baseline_actions(self._session, category, kb_version_id)

    def _pipeline_stage(self, case_id: uuid.UUID) -> JobStage | None:
        """How far the case's newest pipeline run has got (IR-22, P05 §5.4).

        Three of the eight values are derived from the job's status rather than
        read from its payload: a job that has not started cannot have recorded a
        stage, and one that has finished should report its outcome rather than the
        last stage it happened to be in. A `RUNNING` job with no marker yet reads
        `queued`, which is true — it has been claimed and has not reported
        progress.
        """
        row = self._cases.latest_pipeline_job(case_id)
        if row is None:
            return None

        status = JobStatus(row.status)
        if status is JobStatus.DONE:
            return JobStage.DONE
        if status is JobStatus.FAILED:
            return JobStage.FAILED
        if status is JobStatus.QUEUED:
            return JobStage.QUEUED

        recorded = (row.payload or {}).get(STAGE_KEY)
        try:
            return JobStage(recorded)
        except ValueError:
            return JobStage.QUEUED

    # --- Internals --------------------------------------------------------

    def _to_queue_item(self, row: Row, now: datetime) -> CaseQueueItem:
        category = _as_category(row.category)
        waiting_minutes = _minutes_between(row.created_at, now)
        return CaseQueueItem(
            id=row.id,
            case_no=row.case_no,
            status=CaseStatus(row.status),
            created_at=row.created_at,
            species=Species(row.species),
            pet_name=row.pet_name,
            age_value=float(row.age_value) if row.age_value is not None else None,
            age_unit=row.age_unit,
            breed=row.breed,
            primary_complaint_code=row.primary_complaint_code,
            primary_complaint_name=row.primary_complaint_name,
            category=category,
            recommended_category=_as_category(row.recommended_category),
            confirmed_category=_as_category(row.confirmed_category),
            decision_type=row.decision_type,
            waiting_minutes=waiting_minutes,
            target_minutes=target_minutes(category),
            is_overdue=is_overdue(category, waiting_minutes),
            has_red_flag=row.has_red_flag,
        )

    def _queue_counts(self) -> CaseQueueCounts:
        """Fold the grouped counts into the seven numbers W-02 shows.

        A case with no category is counted in `total` and, when it is there for a
        reviewer to triage by hand, in `manual_count` — but in none of the five
        category tiles, because it has no category to be counted under.
        """
        by_category = dict.fromkeys(VTLCategory, 0)
        manual_count = 0
        awaiting_review_count = 0
        total = 0

        for row in self._cases.queue_counts():
            count = row.case_count
            total += count
            category = _as_category(row.category)
            if category is not None:
                by_category[category] += count
            status = CaseStatus(row.status)
            if status is CaseStatus.MANUAL_TRIAGE_REQUIRED:
                manual_count += count
            elif status is CaseStatus.AWAITING_REVIEW:
                awaiting_review_count += count

        return CaseQueueCounts(
            by_category=by_category,
            manual_count=manual_count,
            awaiting_review_count=awaiting_review_count,
            total=total,
        )

    def _utc_bounds(
        self, date_from: date | None, date_to: date | None
    ) -> tuple[datetime | None, datetime | None]:
        """Turn the clinic's calendar dates into the UTC instants to compare.

        The filter bar says "Today", and the clinic's today starts at midnight in
        Asia/Manila, not at midnight UTC — which is 8 a.m. locally and would cut
        the morning's cases off the list. Timestamps are stored in UTC (DR-03),
        so the conversion happens here.

        `date_to` is inclusive, so the upper bound is midnight on the day after;
        the repository compares it with `<`.
        """
        start = None
        end = None
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=self._display_timezone)
        if date_to is not None:
            end = datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=self._display_timezone
            )
        return start, end


def _as_category(value: object) -> VTLCategory | None:
    """Normalise a category into a `VTLCategory`, or None.

    Two callers need this. `coalesce` over two enum columns can hand back the raw
    label rather than the enum member, and `TARGET_MINUTES` is keyed by the
    member. The queue's category filter is a separate enum that shares the five
    VTL labels, so the same conversion turns one into the other.
    """
    if value is None:
        return None
    return VTLCategory(value)


def _as_species(value: object) -> Species | None:
    """Normalise a species out of the stored extraction JSON, or None.

    `entities` is JSONB written by a pipeline stage. A value that is not one of
    the two supported species reads as absent rather than raising: the case row
    carries the authoritative species, and the review screen shows that.
    """
    if value is None:
        return None
    try:
        return Species(value)
    except ValueError:
        return None


def _as_text(value: object) -> str | None:
    """A stored optional string, or None for anything that is not one."""
    return value if isinstance(value, str) else None


def _parse_iso(value: object) -> datetime | None:
    """An ISO-8601 instant from a JSONB payload, or None if it is not one.

    Defensive like `_as_text_list`: the value was written into an append-only log
    by a previous version of the code and can never be corrected there, so an
    unreadable one falls back rather than raising.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_text_list(value: object) -> list[str]:
    """A stored list of strings, dropping anything that is not one.

    Defensive for the same reason as `_as_species`: these lists come out of
    JSONB columns a stage wrote, and one unexpected element must not make the
    case unreadable.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _cited_ranks(cited_chunk_ids: object) -> list[int]:
    """The passage ranks one stored suggestion cites.

    `action_suggestions.cited_chunk_ids` holds `{"rank", "chunk_id"}` objects —
    see `PipelineRepository.cited_chunk_ids` for why — and the review screen
    needs the rank, which is what identifies the reference row it displays. A
    row written with anything else is read as citing nothing rather than
    raising: a malformed citation must not make a case unreadable.
    """
    if not isinstance(cited_chunk_ids, list):
        return []
    return [
        item["rank"]
        for item in cited_chunk_ids
        if isinstance(item, dict) and isinstance(item.get("rank"), int)
    ]


def _minutes_between(started_at: datetime, now: datetime) -> int:
    """Whole minutes waited, never negative.

    A case cannot have waited a negative time; a clock adjustment between the
    insert and the read should show 0, not -1.
    """
    return max(0, int((now - started_at).total_seconds() // 60))
