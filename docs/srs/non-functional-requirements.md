# Non-Functional Requirements (NFR)

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Source:** SRS v1.1. IDs and the text in the Description column are authoritative: do not renumber, reword, or delete them. Priority follows the SRS keyword (`SHALL` = Must, `SHOULD` = Should, `MAY` = May).
**Sibling files:** [functional](functional-requirements.md) · [non-functional](non-functional-requirements.md) · [interface](interface-requirements.md) · [business rules](business-rules.md) · [database](database-requirements.md) · [security](security-requirements.md)

**Coverage:** NFR-01 to NFR-28, 28 requirements, no gaps.

NFR-07 to NFR-15 are the clinical safety requirements. They constrain every feature and may not be relaxed for performance, cost or schedule; a change needs a new ADR and veterinary review.

## Performance (5.1)

Measured with `scripts/latency_report.py` and the evaluation harness. Latency budgets assume the async pipeline of [ADR-08](../adr/ADR-08-async-jobs-polling.md).

| ID | Requirement | Description | Priority | Verification / acceptance criteria | Related |
|---|---|---|---|---|---|
| **NFR-01** | End-to-end latency | The end-to-end time from case submission to the display of the recommendation SHALL be no more than 10 seconds at p50 and no more than 20 seconds at p95, with up to 10 concurrent users. | Must | Measure p50/p95 over 20 submissions with all stages real; both thresholds met. | FR-06, FR-68, NFR-06 |
| **NFR-02** | Retrieval latency | The retrieval step SHALL complete within 1 second at p95 for a knowledge base of up to 5,000 indexed passages. | Must | Retrieval stage_ms p95 below 1,000 ms with the indexed KB in place. | FR-19, ADR-04, ADR-07 |
| **NFR-03** | Screen load time | The Triage Queue and Case Review screens SHALL load within 2 seconds at p95, excluding AI processing time. | Must | W-02 and W-04 render within 2 s p95 with mocked or cached AI data. | IR-01, IR-22 |
| **NFR-04** | Decision write latency | Confirm, adjust, and close actions SHALL be saved and reflected in the Triage Queue within 2 seconds at p95. | Must | A confirm or adjust is visible in the queue within 2 s p95. | FR-32, FR-33, FR-38 |
| **NFR-05** | Red-flag alert latency | Red-flag alerts from the deterministic pre-screen (FR-12) SHALL appear within 2 seconds of submission, independently of LLM response time. | Must | The W-02 banner appears within 2 s of submission with the LLM forced to time out. | FR-12, ADR-08 |
| **NFR-06** | Concurrency and volume | The system SHALL support at least 10 concurrent authenticated users and at least 200 new cases per day without exceeding the limits in NFR-01 to NFR-04. | Must | 10 concurrent users and 200 cases/day keep NFR-01 to NFR-04 within limits. | NFR-01, ADR-13 |

## Safety and clinical risk (5.2)

These are the requirements that must never be traded away for speed or convenience. Enforced by [ADR-09](../adr/ADR-09-deterministic-safety-validator.md) and [ADR-15](../adr/ADR-15-review-ui-and-vtl-presentation.md).

| ID | Requirement | Description | Priority | Verification / acceptance criteria | Related |
|---|---|---|---|---|---|
| **NFR-07** | Human-in-the-loop | No urgency category SHALL be treated as final until a Veterinary Reviewer has confirmed or adjusted it; unconfirmed recommendations SHALL always be displayed as pending (Human-in-the-Loop). | Must | No status becomes CONFIRMED/ADJUSTED without a StaffDecision row; unconfirmed output is always labelled pending. | FR-36, BR-01, IR-04 |
| **NFR-08** | Safety floor always active | The red-flag safety floor (FR-23) SHALL be active at all times. Changes to red-flag rules SHALL require approval by the Veterinary Domain Reviewer and SHALL be recorded in the audit trail. | Must | The floor cannot be disabled by configuration; rule changes require KB approval and produce audit entries. | FR-23, BR-04, ADR-09 |
| **NFR-09** | Graceful AI degradation | If any AI component is unavailable, times out, or returns an error, the system SHALL still allow cases to be created and triaged manually, SHALL display the message “AI unavailable – triage manually using the VTL” together with the VTL reference, and SHALL NOT silently drop any case. | Must | Each forced failure mode ends in MANUAL_TRIAGE_REQUIRED with the W-06 banner; no case is lost or stuck in PROCESSING. | FR-15, IR-19, ADR-08 |
| **NFR-10** | Visible disclaimer | Every recommendation SHALL display a disclaimer stating that it is decision support only and does not replace the clinical judgment of veterinary staff. | Must | The decision-support disclaimer is present on every screen that shows a recommendation. | IR-06, BR-09 |
| **NFR-11** | No silent category change | The system SHALL NOT automatically change a category that has been confirmed or adjusted by staff. | Must | After a decision, no background process changes the final category; regeneration creates a new version only. | FR-27, FR-48, ADR-14 |
| **NFR-12** | Grounded output only | Rationales and references SHALL be grounded only in retrieved knowledge base passages; recommendations whose citations do not match the retrieved passages SHALL be flagged (FR-22) to reduce the risk of fabricated (“hallucinated”) content. | Must | Citations are validated against the retrieved set; unmatched citations flag the recommendation. | FR-22, ADR-09 |
| **NFR-13** | Out-of-scope handling | Out-of-scope inputs (species other than dogs and cats, unsupported complaints, or non-clinical text) SHALL be flagged for manual triage rather than forced into a category. | Must | Other species, OTHER complaints and non-clinical text route to manual triage rather than a forced category. | FR-02, FR-10, BR-06 |
| **NFR-14** | Under-triage review | Evaluation reports SHALL list every under-triaged vignette, and these cases SHALL be reviewed by the Veterinary Domain Reviewer before any usability session with veterinary staff. | Must | Every evaluation report lists under-triaged vignettes, reviewed and signed off before any usability session. | FR-66, BR-04, M7 |
| **NFR-15** | Parallel operation with clinic procedure | When the system is used with real patients during the evaluation period, it SHALL be operated alongside, and not in place of, the clinic’s standard triage procedure. | Must | Evaluation protocol states that clinic triage runs unchanged alongside the system. | BR-09 |

## Quality attributes (5.3)

Targets NFR-16 and NFR-17 are reported in PD8 as early results on a 20–30 vignette set and in the final presentation on the full 50–100 set.

| ID | Requirement | Description | Priority | Verification / acceptance criteria | Related |
|---|---|---|---|---|---|
| **NFR-16** | Classification targets | **Correctness:** On the labeled test set, the system SHALL achieve a macro-F1 of at least 0.70 across the five VTL categories, a recall of at least 0.90 for the combined Red and Orange categories, and an under-triage rate of no more than 10%. | Must | On the held-out test split: macro-F1 ≥ 0.70, Red+Orange recall ≥ 0.90, under-triage ≤ 10%. | FR-66, NFR-14 |
| **NFR-17** | Retrieval targets | **Retrieval relevance:** The retriever SHALL achieve a Recall@5 of at least 0.80 and an MRR of at least 0.70 on the relevance-labeled test set. | Must | On the relevance-labelled set: Recall@5 ≥ 0.80 and MRR ≥ 0.70. | FR-67, FR-19, ADR-07 |
| **NFR-18** | Transparency | **Transparency:** 100% of displayed recommendations SHALL include a rationale and at least one validated reference to the knowledge base. | Must | Every displayed recommendation has a rationale and at least one validated reference. | FR-21, FR-22 |
| **NFR-19** | Usability (SUS) | **Usability:** The mean System Usability Scale score from evaluation participants SHALL be at least 68, the commonly used benchmark for average usability [9]. | Must | Mean SUS from evaluation participants is at least 68. | FR-70, NFR-20 |
| **NFR-20** | Learnability | **Learnability:** After an orientation of no more than 15 minutes, a new Veterinary Reviewer SHALL be able to open, review, and confirm or adjust a case without assistance within 3 minutes in at least 90% of trials. | Must | After ≤ 15 minutes of orientation, a reviewer completes a case in under 3 minutes in ≥ 90% of trials. | NFR-19, ADR-15 |
| **NFR-21** | Accessibility | **Accessibility:** The user interface SHALL conform to WCAG 2.1 Level AA [8], including a text contrast ratio of at least 4.5:1 and full keyboard operability. | Must | axe-core reports no serious or critical violations on W-01 to W-05; contrast ≥ 4.5:1; full keyboard operation. | IR-03, IR-07 |
| **NFR-22** | Reliability and availability | **Reliability and availability:** The system SHALL be available at least 95% of the time during scheduled evaluation sessions, and no confirmed decision SHALL be lost. | Must | ≥ 95% availability during scheduled sessions; no confirmed decision is lost after a restart. | NFR-09, ADR-08, ADR-13 |
| **NFR-23** | Reproducibility | **Reproducibility:** Re-running the same vignette set with the same recorded configuration (model, prompt version, parameters, and knowledge base version) SHALL produce the same category for at least 95% of the vignettes. | Must | Re-running the same vignette set on the same frozen configuration gives the same category for ≥ 95% of vignettes. | FR-26, FR-65, ADR-14 |
| **NFR-24** | Maintainability | **Maintainability:** The extraction, retrieval, generation, safety-rule, and persistence functions SHALL be implemented as separate modules, and the LLM provider SHALL be replaceable by changing only its adapter and configuration (IR-12). | Must | Pipeline stages and the LLM provider are separate modules replaceable via configuration only. | IR-12, ADR-01, ADR-17 |
| **NFR-25** | Testability | **Testability:** Automated unit tests SHALL cover at least 60% of the backend core modules, and every SHALL requirement SHALL be traceable to at least one test case by PD8. | Must | Backend core coverage ≥ 60% enforced in CI; every SHALL requirement traces to at least one test by PD8. | docs/traceability.md |
| **NFR-26** | Portability | **Portability:** The system SHALL be deployable on any Linux host that supports Docker by following the README, using a single Docker Compose command. | Must | A clean clone plus `cp .env.example .env` plus one Docker Compose command brings the system up on any Docker-capable Linux host. | ADR-13, IR-09 |
| **NFR-27** | Localization | **Localization:** The user interface, the supported input, and the documentation SHALL be in English. All interface text SHALL be stored in resource files so that a Filipino translation can be added in a later release without code changes. | Must | UI, input and documentation are English; interface strings live in resource files. | FR-18, ADR-16 |
| **NFR-28** | Cost efficiency | **Sustainability and cost efficiency:** The system SHALL avoid redundant LLM calls by storing results and re-processing a case only when its input is edited, and SHALL record AI service usage so that it can be kept within the project budget (PD4). | Must | Results are stored and reused; a case is re-processed only when its input changes, and AI usage is recorded. | FR-27, ADR-06 |

## Notes

- **NFR-16, NFR-17, NFR-19, NFR-20 and NFR-23 are measured, not asserted.** Report the measured value with the sample size, even when a target is missed; a missed target with an honest error analysis is a valid result (see guide M7).
- **NFR-25** requires a traceability table by PD8. Generate it from `@pytest.mark.req("FR-xx")` markers into `docs/traceability.md`.
- **NFR-27** now states English-only input and UI; see [ADR-16](../adr/ADR-16-english-only-input.md).
- **NFR-05 and NFR-01 interact:** the red-flag pre-screen must not wait for the LLM. This is why red-flag alerts are committed before extraction ([ADR-08](../adr/ADR-08-async-jobs-polling.md)).
