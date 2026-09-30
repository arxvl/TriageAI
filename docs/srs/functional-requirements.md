# Functional Requirements (FR)

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Source:** SRS v1.1, Section 4 (System Features). The IDs and the text in the Description column are authoritative: do not renumber, reword, or delete them.
**Sibling files:** [non-functional](non-functional-requirements.md) · [interface](interface-requirements.md) · [business rules](business-rules.md) · [database](database-requirements.md) · [security](security-requirements.md)

## How to read this file

- **Requirement** is a short handle for discussion. **Description** is the normative SRS text and is what must be implemented.
- **Priority** is derived from the SRS keyword: `SHALL` = Must, `SHOULD` = Should, `MAY` = May.
- **PD8 scope** is the delivery priority for the MVP prototype due 2026-10-29, taken from the PD8 roadmap backlog. It is *not* the same as Priority: a `Must` requirement can be scheduled as `Should` for the prototype.
- **Acceptance criteria** is the check that proves the requirement is met, and the basis for the test that traces to this ID (NFR-25).
- **Related** cross-references other requirements, ADRs in `docs/adr/`, and wireframes (W-xx) in `docs/prototype/TriageAI_Prototype.html`.
- New requirements get a new ID at the end of the category. Never reuse or renumber an ID.

**Coverage:** FR-01 to FR-70, 70 requirements, no gaps and no duplicates.


## 4.1 Case Intake and Symptom Capture

Screen W-03. Implemented by `app/api/v1/cases.py`, `app/services/case_service.py`, `frontend/src/pages/CaseIntake`. Input language is fixed by [ADR-16](../adr/ADR-16-english-only-input.md).

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-01** | Case Intake Form fields | The system SHALL provide a Case Intake Form that captures the species (Dog or Cat; required), the owner’s symptom description (required; 20 to 2,000 characters), and the following optional fields: pet name, age, sex and neuter status, breed, body weight in kilograms, and intake channel (walk-in, phone, or online message). | Must | Must | Submitting the form with species + a 20–2,000 character description creates a case; optional fields persist exactly as entered. | FR-04, IR-01, W-03 |
| **FR-02** | Dog and cat only | The system SHALL restrict the species to Dog and Cat. For any other species, the system SHALL NOT invoke the AI pipeline and SHALL inform the user that the case must be triaged manually according to clinic procedure. | Must | Must | Selecting "Other species" disables submission, shows the manual-triage message, and no pipeline job is created. | BR-06, NFR-13, W-03 |
| **FR-03** | Unique case identifier | The system SHALL assign each case a unique case identifier and record its creation timestamp and the creating user. | Must | Must | Each case receives a unique case number (C-0001 format) with creation timestamp in UTC and the creating user. | DR-01, DR-03 |
| **FR-04** | Field-level validation | The system SHALL validate required fields and length limits before submission and display field-level error messages without clearing the entered data. | Must | Must | An invalid weight shows an inline message; previously entered values are still present after the error. | FR-01, IR-05 |
| **FR-05** | Verbatim, immutable description | The system SHALL store the owner’s description verbatim and SHALL NOT allow the original text to be altered after submission. | Must | Must | An UPDATE on owner_descriptions is rejected by the database, not only by the application. | DR-04, ADR-12 |
| **FR-06** | Automatic pipeline start | The system SHALL automatically start the triage pipeline (Features 4.2 and 4.3) upon successful submission and display the processing status to the user. | Must | Must | POST /cases returns 202, a PIPELINE_RUN job exists, and the UI shows the processing state. | NFR-01, IR-22, ADR-08 |
| **FR-07** | Optional owner reference | The system SHOULD allow an optional owner reference (e.g., name or contact number) that is stored only in the local database and excluded from all AI processing. | Should | Should | Owner name and contact are stored in owner_references and appear in no API response, export, or prompt. | DR-04, IR-20, SR-08 |
| **FR-08** | Pet-owner self-service intake | The system MAY provide a self-service web intake form for pet owners in a future release. | May | Later | Out of scope for PD8 and the final presentation; recorded as future work. | IR-21 |

## 4.2 Clinical Entity Extraction

Pipeline stages 1–3: de-identify, red-flag pre-screen, extraction. Stage selection follows [ADR-17](../adr/ADR-17-mock-first-stage-registry.md); de-identification follows [ADR-10](../adr/ADR-10-deidentification-fail-closed.md). Real stages are built manually in guides M1 and M3.

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-09** | LLM entity extraction | The system SHALL extract structured clinical information from the owner’s description using a transformer-based language model and populate the fields of the extraction schema defined in Section 4.2.1. | Must | Must | A valid case produces an ExtractionResult matching the schema in SRS 4.2.1. | FR-15, IR-13, ADR-05 |
| **FR-10** | Complaint mapping | The system SHALL map each identified complaint to the fixed list of supported presenting complaints; complaints that cannot be mapped SHALL be labeled “Other/Unsupported”. | Must | Must | A complaint outside the fixed list is stored as OTHER, never as free text. | FR-19, NFR-13 |
| **FR-11** | Negation handling | The system SHALL detect negated findings (e.g., “no blood in the vomit”) and SHALL NOT treat them as present. | Must | Must | "no blood in the vomit" appears in negated_findings and not in associated_signs. | FR-09 |
| **FR-12** | Red-flag detection | The system SHALL identify red-flag indicators from the veterinarian-validated red-flag list (e.g., not breathing, unresponsive, ongoing seizure, uncontrolled bleeding, male cat unable to urinate, suspected toxin ingestion, pale or bluish gums) using both a deterministic keyword and phrase pre-screen executed immediately upon submission and the LLM extraction. | Must | Must | The deterministic pre-screen writes alert rows before any LLM call; LLM-detected red flags are added afterwards. | FR-23, NFR-05, NFR-08, ADR-09 |
| **FR-13** | Evidence spans | The system SHALL record the text span that supports each extracted value so that the evidence can be highlighted on the Case Review screen. | Must | Must | Each extracted value carries a span that is an exact substring of the de-identified text; non-matching spans are discarded. | FR-31, IR-04, ADR-10 |
| **FR-14** | Missing information list | The system SHALL list clinically important information that is missing from the description (e.g., unknown duration) so that staff can ask the owner follow-up questions. | Must | Must | The extraction lists clinically relevant gaps, shown in W-04 as "Ask the owner". | FR-31 |
| **FR-15** | Schema validation and retry | The system SHALL validate the model output against the extraction schema; if validation fails after one retry, the system SHALL set the case to “Manual Triage Required”. | Must | Must | Two consecutive invalid outputs set the case to MANUAL_TRIAGE_REQUIRED; the retry is recorded. | NFR-09, IR-19, ADR-06 |
| **FR-16** | Reviewer correction of extraction | The system SHALL allow Veterinary Reviewers to correct extracted values and SHALL retain both the original AI extraction and the corrected values. | Must | Should | A correction stores a new extraction version with is_corrected; the original version remains readable. | FR-27, FR-48, ADR-14 |
| **FR-17** | No diagnosis in extraction | The system SHALL NOT infer or display diagnoses during extraction; extraction SHALL be limited to findings reported in the description. | Must | Must | No extracted field contains a diagnosis; prompt and schema permit only reported findings. | FR-28, BR-01 |
| **FR-18** | English-only input | The system SHALL accept symptom descriptions in English only. The Case Intake Form SHALL instruct staff to enter the description in English and to translate any Filipino or Bikol terms reported by the owner, keeping the owner’s exact wording in quotation marks where the meaning is uncertain. Automatic processing of non-English descriptions is out of scope (Section 1.4). | Must | Must | The intake form shows the English-entry instruction; no language detection or translation component exists. | NFR-27, ADR-16 |

## 4.3 Retrieval and Urgency Prioritization

Pipeline stages 4–6: retrieve, generate, validate. See [ADR-05](../adr/ADR-05-rag-not-finetuning.md), [ADR-07](../adr/ADR-07-local-embedding-model.md) and [ADR-09](../adr/ADR-09-deterministic-safety-validator.md). Real stages are built manually in guides M4–M6.

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-19** | Top-k semantic retrieval | The system SHALL retrieve the top-k most relevant passages from the active knowledge base version using semantic similarity search, where k is configurable (default 5; final value TBD-7). | Must | Must | Retrieval returns at most k passages (default 5) from the active KB version, filtered by species. | FR-54, NFR-02, NFR-17, ADR-04, ADR-07 |
| **FR-20** | Exactly one VTL category | The system SHALL generate exactly one urgency category per case from the set {Red, Orange, Yellow, Green, Blue}. | Must | Must | Every stored recommendation has exactly one category from {RED, ORANGE, YELLOW, GREEN, BLUE}. | BR-01, IR-03 |
| **FR-21** | Plain-language rationale | The system SHALL provide a concise, plain-language rationale that refers to the extracted findings and the retrieved passages. | Must | Must | Each recommendation has a rationale of at most 80 words referring to reported findings, with no treatment advice. | FR-28, NFR-18 |
| **FR-22** | Citation validation | The system SHALL cite at least one retrieved passage for each recommendation and SHALL verify that every cited passage was actually retrieved for that case; recommendations without a valid citation SHALL be labeled low confidence. | Must | Must | Cited ranks not present in the retrieved set are removed; if none remain, confidence is LOW with reason NO_VALID_CITATION. | NFR-12, NFR-18, ADR-09 |
| **FR-23** | Red-flag safety floor | The system SHALL apply deterministic red-flag safety rules after generation: when a red flag is detected, the recommended category SHALL NOT be lower than the minimum category assigned to that red flag in the clinical rubric, and the application of the rule SHALL be recorded. | Must | Must | A red flag with a higher minimum category raises the stored category and records the rule code; the category is never lowered. | FR-12, NFR-08, ADR-09 |
| **FR-24** | Confidence indicator | The system SHALL display a confidence indicator (High, Medium, or Low) derived from the model output and retrieval similarity scores, and SHALL flag recommendations below the confidence threshold (TBD-8). | Must | Must | Confidence (HIGH/MEDIUM/LOW) is displayed with plain-language reasons; a low retrieval score caps it at MEDIUM. | FR-22, FR-31 |
| **FR-25** | Tie-break toward urgency | When the evidence supports two adjacent categories equally, the system SHALL recommend the more urgent category in order to minimize under-triage. | Must | Must | The generation prompt instructs the more urgent choice on a tie; the validator may raise but never lower. | FR-23, NFR-16, ADR-09 |
| **FR-26** | Provenance of recommendations | The system SHALL record, for each recommendation, the model identifier, prompt version, generation parameters, knowledge base version, retrieved passage IDs, and similarity scores. | Must | Must | Each recommendation stores model_id, prompt_version, parameters, kb_version_id, retrieved passage IDs and scores. | NFR-23, DR-05, ADR-14 |
| **FR-27** | Regenerate after correction | The system SHALL allow a Veterinary Reviewer to regenerate the recommendation after correcting extracted information, and SHALL retain every generated version. | Must | Should | Regeneration creates a new recommendation version; earlier versions remain viewable and read-only. | FR-16, FR-48, ADR-14 |
| **FR-28** | No diagnosis or treatment | The system SHALL NOT produce a diagnosis, prognosis, or treatment recommendation. | Must | Must | No stored or displayed output contains a diagnosis, prognosis, or treatment recommendation. | BR-01, IR-06, NFR-10 |

## 4.4 Triage Review Dashboard

Screens W-02, W-04, W-05, W-06, W-11. Implemented by `app/services/review_service.py` and `frontend/src/pages/{TriageQueue,CaseReview}`. Presentation rules are fixed by [ADR-15](../adr/ADR-15-review-ui-and-vtl-presentation.md).

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-29** | Triage Queue ordering | The system SHALL display a Triage Queue of open cases sorted first by urgency category (the confirmed category if available, otherwise the recommended category) and then by arrival time, showing each case’s elapsed waiting time against its target waiting time. | Must | Must | Order is RED, no-category, ORANGE, YELLOW, GREEN, BLUE; oldest first within a rank; a confirmed category wins over the recommended one. | FR-36, IR-22, W-02 |
| **FR-30** | Overdue indication | The system SHALL visually alert users when a case’s elapsed waiting time exceeds the target waiting time of its category. | Must | Must | A case past its target waiting time is visually marked and labelled "overdue" in text. | IR-03, W-02 |
| **FR-31** | Case Review content | The Case Review screen SHALL display the original description, the extracted information with highlighted evidence, the recommended category with its target waiting time, the rationale, the confidence indicator, and the retrieved references (source title, section, excerpt, and link). | Must | Must | W-04 shows description, highlighted evidence, category with target time, rationale, confidence and references with links. | FR-13, FR-24, IR-04, ADR-15 |
| **FR-32** | Confirm recommendation | The system SHALL allow a Veterinary Reviewer to confirm the recommended category. | Must | Must | Confirm stores a CONFIRM decision, sets status CONFIRMED and updates the queue within 2 s. | NFR-04, BR-02 |
| **FR-33** | Adjust with reason | The system SHALL allow a Veterinary Reviewer to adjust the recommendation to any of the five categories and SHALL require a reason selected from a predefined list, with optional free text. | Must | Must | Adjust requires a different category and a reason code; a request without one is rejected with 422. | BR-03, W-05 |
| **FR-34** | Manual triage | The system SHALL allow a Veterinary Reviewer to mark a case as “Manual triage – AI not applicable” and assign the category manually. | Must | Must | A reviewer can set a category manually with a required note, from MANUAL_TRIAGE_REQUIRED or AWAITING_REVIEW. | NFR-09, W-06 |
| **FR-35** | Decisions restricted to reviewers | The system SHALL restrict the confirm, adjust, manual triage, and close actions to users with the Veterinary Reviewer role. | Must | Must | Intake Staff and Administrators receive 403 on decision, manual triage and close endpoints. | SR-05, BR-02, ADR-11 |
| **FR-36** | AI versus confirmed indication | The system SHALL clearly indicate whether the displayed category is an AI recommendation pending review or a staff-confirmed decision. | Must | Must | The "requires staff confirmation" label is present until a decision exists and absent afterwards. | IR-04, NFR-07 |
| **FR-37** | Clinical notes | The system SHALL allow Veterinary Reviewers to add clinical notes to a case. | Must | Should | A reviewer can attach a note; the note appears in the audit timeline. | FR-41, FR-45 |
| **FR-38** | Close case | The system SHALL allow a Veterinary Reviewer to close a case (e.g., “Seen by veterinarian”), removing it from the active queue. | Must | Must | Close is allowed only after a decision, sets closed_at, and removes the case from the open queue. | FR-29, IR-08 |
| **FR-39** | Queue filters | The system SHOULD allow the queue to be filtered by species, category, status, and date. | Should | Should | The queue can be filtered by species, category, status and date, with filters reflected in the request. | FR-44, W-02 |
| **FR-40** | Printable case summary | The system MAY allow a one-page triage summary of a case to be printed through the browser. | May | Later | If implemented, a one-page browser print view of a case exists. | FR-31 |

## 4.5 Case Records and Audit Trail

Screen W-07. Implemented by `app/services/audit_service.py`. Immutability is enforced in the database ([ADR-12](../adr/ADR-12-append-only-audit.md)).

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-41** | Log every case and decision | The system SHALL log every triage case, including the AI recommendation, the staff’s final decision, and the timestamp of each action. | Must | Must | Case creation, AI output and every staff decision produce audit entries with timestamps. | FR-42, SR-12, ADR-12 |
| **FR-42** | Audit entry content | Each audit entry SHALL include the timestamp, the user ID and role, the action type, the affected record, and the previous and new values where applicable. | Must | Must | Each entry records timestamp, user ID, role, action, affected record, and before/after values where applicable. | FR-41, DR-03 |
| **FR-43** | Append-only audit | Audit entries SHALL be append-only; no user, including Administrators, SHALL be able to modify or delete them through the application. | Must | Must | UPDATE and DELETE on audit_log are rejected at the database level for the application role. | SR-12, DR-01, ADR-12 |
| **FR-44** | Case history search | The system SHALL provide a case history search by case ID, date range, species, presenting complaint, category, and status. | Must | Should | History can be searched by case ID, date range, species, complaint, category and status. | FR-39, W-07 |
| **FR-45** | Audit timeline per case | The system SHALL display a chronological audit timeline for each case. | Must | Must | W-07 shows a chronological timeline with actor, role, action and time for each event. | FR-42, ADR-12 |
| **FR-46** | Timing metrics per case | The system SHALL compute and display, for each case, the time from submission to recommendation and from recommendation to the staff decision. | Must | Should | Submission-to-recommendation and recommendation-to-decision intervals are computed and displayed. | NFR-01, FR-45 |
| **FR-47** | De-identified export | The system SHALL allow Administrators to export de-identified case and audit data in CSV format for evaluation. | Must | Later | The CSV export contains no free text, owner reference or reviewer name; each export writes a DATA_EXPORTED audit entry. | BR-08, SR-12, DR-06 |
| **FR-48** | Amendments, not edits | The system SHALL NOT allow a finalized decision to be edited; corrections SHALL be recorded as amendments that reference the original decision. | Must | Must | A second decision is stored as a new row referencing the original via amends_id; the original is unchanged. | BR-07, FR-43, ADR-12 |

## 4.6 Knowledge Base Management

Screen W-08. Implemented by `app/services/kb_service.py` and `scripts/import_kb.py`. Versioning follows [ADR-14](../adr/ADR-14-versioning-reproducibility.md); indexing is built manually in guide M5.

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-49** | Knowledge base entry fields | The system SHALL store each knowledge base entry with its presenting complaint, title, content, discriminators and red flags with their minimum VTL category, species applicability, source reference (title, publisher, URL, and access date), status, reviewer, and approval date. | Must | Must | Each entry stores complaint, title, content, red flags with minimum category, species, full source citation, status, reviewer and approval date. | FR-50, DR-05 |
| **FR-50** | Mandatory source citation | The system SHALL require a source citation for every entry and SHALL restrict sources to the open-access references in Section 1.5 or additional sources approved by the Veterinary Domain Reviewer. | Must | Must | An entry cannot be submitted without the title, publisher, URL and access date of its source. | BR-04, FR-49 |
| **FR-51** | Entry workflow | The system SHALL enforce the entry workflow Draft → Pending Review → Active → Retired, and SHALL use only Active entries for retrieval. | Must | Must | Only ACTIVE entries in the published version are retrievable; invalid transitions return 409. | FR-52, FR-54, ADR-14 |
| **FR-52** | Veterinarian approval required | The system SHALL require approval from an account with knowledge base approval permission, held only by licensed veterinarians, before an entry becomes Active. | Must | Should | Approval requires can_approve_kb; any other user receives 403. | BR-04, SR-05, ADR-11 |
| **FR-53** | Index on approval or retirement | The system SHALL chunk and embed an entry and update the vector index when the entry is approved or retired. | Must | Should | Approval runs a KB_INDEX job that chunks and embeds the entry; on failure the entry stays pending and no version is published. | FR-19, ADR-07, ADR-14 |
| **FR-54** | Knowledge base versioning | The system SHALL version the knowledge base and link each recommendation to the knowledge base version used. | Must | Must | Each approval or retirement publishes an immutable version listing all active entries; recommendations store the version used. | DR-05, FR-26, ADR-14 |
| **FR-55** | No automatic KB updates | The system SHALL NOT update the knowledge base automatically from external sources. | Must | Must | No component fetches or writes knowledge-base content from an external source at runtime. | BR-04, ADR-05 |
| **FR-56** | Bulk import of drafts | The system SHOULD allow draft entries to be imported in bulk from a structured CSV or JSON file. | Should | Should | import_kb loads structured entry files as drafts; re-import is idempotent and never overwrites an active entry. | FR-51, ADR-14 |

## 4.7 User and Access Management

Screens W-01, W-09. Implemented by `app/api/v1/auth.py`, `app/core/security.py`, `app/api/deps.py`. See [ADR-11](../adr/ADR-11-cookie-sessions-rbac.md).

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-57** | Authentication required | The system SHALL require authentication with a username or e-mail address and a password before any function can be used. | Must | Must | Every endpoint except /health and /auth/login returns 401 without a valid session. | SR-01, SR-04, ADR-11 |
| **FR-58** | Roles and KB permission | The system SHALL support the roles Intake Staff, Veterinary Reviewer, and Administrator, and a separate knowledge base approval permission that can be granted to Veterinary Reviewer accounts of licensed veterinarians. | Must | Must | The three roles exist; can_approve_kb can be set only on a Veterinary Reviewer account (database constraint). | BR-04, BR-05, FR-59 |
| **FR-59** | Role permission enforcement | The system SHALL enforce the role permissions defined in Section 5.5. | Must | Must | A route-scanning test confirms every endpoint declares require_role; forbidden calls return 403. | SR-05, ADR-11 |
| **FR-60** | User account management | The system SHALL allow Administrators to create, edit, and deactivate user accounts and to assign roles and permissions. | Must | Later | An Administrator can create, edit and deactivate accounts and assign roles; the last active Administrator cannot be removed. | BR-05, W-09 |
| **FR-61** | Forced password change | The system SHALL require users to change a temporary password at first login. | Must | Must | While must_change_password is true, all endpoints except /auth/* return 403 with PASSWORD_CHANGE_REQUIRED. | SR-02, ADR-11 |
| **FR-62** | Logout | The system SHALL allow users to log out, which terminates the session. | Must | Must | Logout clears the session and CSRF cookies and writes an audit entry. | SR-04, SR-12 |
| **FR-63** | Administrator password reset | The system SHOULD allow Administrators to reset a user’s password. | Should | Later | A reset returns a temporary password once and sets must_change_password. | FR-61, SR-02 |

## 4.8 Evaluation and Reporting

Screen W-10. Implemented by `app/eval/`. Metrics are deterministic code; runs against real models follow guide M7.

| ID | Requirement | Description | Priority | PD8 scope | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **FR-64** | Labeled vignette set | The system SHALL import a labeled test set of 50–100 vignettes, each with a reference VTL category assigned by the veterinary reviewer and relevance judgments for retrieval. | Must | Should | 50–100 vignettes are imported with a blind reference category and relevance judgements (20–30 for PD8). | NFR-16, NFR-17, DR-06 |
| **FR-65** | Same configuration for evaluation | The system SHALL process evaluation vignettes with the same model, prompts, parameters, and knowledge base version used for live cases, and SHALL store evaluation results separately from clinical case records. | Must | Should | Evaluation runs the same pipeline and configuration as live cases and stores results with vignette_id, never case_id. | NFR-23, DR-06, ADR-17 |
| **FR-66** | Classification metrics | The system SHALL compute classification metrics: accuracy, per-category precision, recall, and F1-score, macro-F1, the confusion matrix, weighted Cohen’s kappa, and the under-triage and over-triage rates. | Must | Should | The run reports accuracy, per-category P/R/F1, macro-F1, confusion matrix, weighted kappa, and under- and over-triage rates. | NFR-16, NFR-14 |
| **FR-67** | Retrieval metrics | The system SHALL compute retrieval metrics: Precision@k, Recall@k, Mean Reciprocal Rank (MRR), and nDCG@k. | Must | Should | The run reports Precision@k, Recall@k, MRR and nDCG@k against the relevance judgements. | NFR-17, FR-19 |
| **FR-68** | Latency metrics | The system SHALL compute p50 and p95 latency for the end-to-end pipeline and for each stage (extraction, retrieval, and generation). | Must | Should | The run reports p50 and p95 for the whole pipeline and for extraction, retrieval and generation separately. | NFR-01, FR-26 |
| **FR-69** | Metric export | The system SHALL export evaluation metrics and per-vignette outputs in CSV and JSON formats. | Must | Later | Metrics and per-vignette outputs can be exported as CSV and JSON. | FR-47, BR-08 |
| **FR-70** | SUS response form | The system SHOULD provide a form to record System Usability Scale (SUS) responses and compute SUS scores. **Note:** If this form is not implemented, SUS responses will be collected with an external form and scored separately. | Should | Later | If not implemented in the application, SUS responses are collected externally and scored separately. | NFR-19 |

## Notes

- **FR-18** changed in SRS v1.1: best-effort handling of code-switched English–Filipino text was replaced by English-only input. See [ADR-16](../adr/ADR-16-english-only-input.md).
- **FR-19** (`k`, default 5) and **FR-24** (confidence threshold) depend on open items TBD-7 and TBD-8. Use the defaults in `PipelineConfig` until those are closed.
- **FR-23 and FR-25 together** define the safety behaviour: the generation prompt prefers the more urgent category on a tie, and the deterministic validator may raise but never lower it. Neither may be relaxed without a new ADR.
- **FR-12 has two detection paths.** The deterministic pre-screen must run before any model call, so NFR-05 (2-second alert) holds regardless of LLM latency.
- **FR-70** may be satisfied outside the application; if so, record the method in the evaluation protocol rather than marking the requirement unmet.
