# Business Rules (BR)

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Source:** SRS v1.1. IDs and the text in the Description column are authoritative: do not renumber, reword, or delete them. Priority follows the SRS keyword (`SHALL` = Must, `SHOULD` = Should, `MAY` = May).
**Sibling files:** [functional](functional-requirements.md) · [non-functional](non-functional-requirements.md) · [interface](interface-requirements.md) · [business rules](business-rules.md) · [database](database-requirements.md) · [security](security-requirements.md)

**Coverage:** BR-01 to BR-10, 10 rules, no gaps. BR-10 was added in SRS v1.2.

Business rules constrain who may do what and under which conditions. They are not implemented as features on their own: each one is realised by the functional, security and database requirements listed in the Related column. All are mandatory.

| ID | Rule | Description | Enforcement | Acceptance criteria | Related |
|---|---|---|---|---|---|
| **BR-01** | AI output is advisory | AI recommendations are advisory. The final urgency category is always decided by an authorized Veterinary Reviewer. | Enforced in code | No code path writes a final category without a StaffDecision row. | FR-31, FR-35, NFR-07 |
| **BR-02** | Reviewer-only decisions | Only Veterinary Reviewers may confirm, adjust, manually triage, or close a case. Intake Staff may create and view cases and must immediately notify a Veterinary Reviewer of any red-flag alert. | Enforced in code | Decision endpoints are restricted with require_role; Intake Staff receive 403 and a read-only W-04. | FR-35, SR-05 |
| **BR-03** | Staff decision prevails, with a reason | When the staff decision differs from the AI recommendation, the staff decision prevails and a reason must be recorded. | Enforced in code | An ADJUST without a reason code is rejected; the direction (up/down) is stored. | FR-33, FR-42 |
| **BR-04** | Approval of clinical content | Only licensed veterinarians holding the knowledge base approval permission may approve knowledge base entries and red-flag rules. | Enforced in code + process | Approval requires can_approve_kb (constrained to Veterinary Reviewer); approvals are logged in `knowledge_base/APPROVALS.md`. | FR-52, FR-58, NFR-08 |
| **BR-05** | Administrator-only management functions | Only Administrators may manage user accounts, draft knowledge base entries, run evaluations, and export data. | Enforced in code | User management, KB drafting, evaluation runs and exports require the Administrator role. | FR-60, FR-65, FR-47 |
| **BR-06** | Manual triage for out-of-scope cases | Cases involving species other than dogs and cats, or unsupported presenting complaints, are triaged manually according to clinic procedure. | Enforced in code | Other species and unsupported complaints are never given an AI category. | FR-02, FR-10, NFR-13 |
| **BR-07** | No deletion during evaluation | Finalized case records and audit entries are not deleted during the evaluation period; corrections are made only as recorded amendments. | Enforced in database | Audit rows and finalized decisions cannot be updated or deleted; corrections are amendments. | FR-43, FR-48, DR-05 |
| **BR-08** | De-identified academic use only | Exported data must be de-identified and used solely for the academic evaluation of this project. | Process + code | Exports contain no personal data and each export is audited. | FR-47, SR-13, DR-06 |
| **BR-09** | Parallel to clinic procedure | During the evaluation period, the system is used alongside, and not in place of, the clinic’s standard triage procedure for real patients. | Process | The evaluation protocol and the UI disclaimer both state that clinic triage is unchanged. | NFR-15, IR-06 |

## Suggested actions (added in SRS v1.2)

| ID | Rule | Description | Enforcement | Acceptance criteria | Related |
|---|---|---|---|---|---|
| **BR-10** | Suggested actions are advisory | Suggested actions are advisory only. A Veterinary Reviewer finalizes the action list for a case, and the system never names a medication, dose, or treatment protocol. Baseline action sets require the same approval as other clinical content. | Enforced in code | Finalization requires the reviewer role; the action validator blocks drug, dose and diagnosis patterns; baseline sets live in approved KB entries. | FR-71, FR-74, FR-76, BR-01, BR-04 |

## Notes

- **BR-01 and BR-02 are the clinical core of the system.** Any feature that would let software, or a non-reviewer, finalise an urgency category contradicts them and must not be built.
- **BR-04 keeps a single approval gate on clinical content.** Knowledge-base entries, urgency-action entries and red-flag rules take effect only after approval by an account holding `can_approve_kb`. In a real deployment that account belongs to a licensed veterinarian; **for this academic project the professor has waived external veterinary sign-off**, so the team approves content that is traceable to a published, veterinarian-authored source. Record the source and the team member who verified it in `knowledge_base/APPROVALS.md`. The lack of clinical validation is a stated limitation of the evaluation.
- **BR-10 (suggested actions)** extends BR-01: actions are advisory until a Veterinary Reviewer finalizes them, and the system never names a medication, dose or treatment protocol.
- **BR-07 and BR-08** shape the data model and exports: no deletions during the evaluation period, and no personal data in any exported file.
- The roles named here are defined in FR-58 and enforced per [ADR-11](../adr/ADR-11-cookie-sessions-rbac.md).
