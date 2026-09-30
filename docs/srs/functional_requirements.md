# Functional Requirements (FR-XX)

## Case Intake and Symptom Submission

This feature allows Intake Staff and Veterinary Reviewers to create a triage case by recording the species, optional signalment, and the owner’s free-text description of the pet’s condition. It is the entry point of every triage workflow.

| **Requirement Number** | **Description** |
|---|---|
| **FR-01** | The system SHALL provide a Case Intake Form that captures the species (Dog or Cat; required), the owner’s symptom description (required; 20 to 2,000 characters), and the following optional fields: pet name, age, sex and neuter status, breed, body weight in kilograms, and intake channel (walk-in, phone, or online message). |
| **FR-02** | The system SHALL restrict the species to Dog and Cat. For any other species, the system SHALL NOT invoke the AI pipeline and SHALL inform the user that the case must be triaged manually according to clinic procedure. |
| **FR-03** | The system SHALL assign each case a unique case identifier and record its creation timestamp and the creating user. |
| **FR-04** | The system SHALL validate required fields and length limits before submission and display field-level error messages without clearing the entered data. |
| **FR-05** | The system SHALL store the owner’s description verbatim and SHALL NOT allow the original text to be altered after submission. |
| **FR-06** | The system SHALL automatically start the triage pipeline (Features 4.2 and 4.3) upon successful submission and display the processing status to the user. |
| **FR-07** | The system SHOULD allow an optional owner reference (e.g., name or contact number) that is stored only in the local database and excluded from all AI processing. |
| **FR-08** | The system MAY provide a self-service web intake form for pet owners in a future release. |

## Clinical Entity Extraction

This feature uses a transformer-based language model to convert the owner’s unstructured description into structured clinical information that can be retrieved against and reviewed by staff. Extraction is limited to reported findings; it does not infer diagnoses. Each identified complaint is mapped to the fixed list of supported presenting complaints below. This initial list is a candidate list and will be finalized with the veterinary domain reviewer (TBD-4).

| **Requirement Number** | **Description** |
|---|---|
| **FR-09** | The system SHALL extract structured clinical information from the owner’s description using a transformer-based language model and populate the fields of the extraction schema defined in Section 4.2.1. |
| **FR-10** | The system SHALL map each identified complaint to the fixed list of supported presenting complaints; complaints that cannot be mapped SHALL be labeled “Other/Unsupported”. |
| **FR-11** | The system SHALL detect negated findings (e.g., “no blood in the vomit”) and SHALL NOT treat them as present. |
| **FR-12** | The system SHALL identify red-flag indicators from the veterinarian-validated red-flag list (e.g., not breathing, unresponsive, ongoing seizure, uncontrolled bleeding, male cat unable to urinate, suspected toxin ingestion, pale or bluish gums) using both a deterministic keyword and phrase pre-screen executed immediately upon submission and the LLM extraction. |
| **FR-13** | The system SHALL record the text span that supports each extracted value so that the evidence can be highlighted on the Case Review screen. |
| **FR-14** | The system SHALL list clinically important information that is missing from the description (e.g., unknown duration) so that staff can ask the owner follow-up questions. |
| **FR-15** | The system SHALL validate the model output against the extraction schema; if validation fails after one retry, the system SHALL set the case to “Manual Triage Required”. |
| **FR-16** | The system SHALL allow Veterinary Reviewers to correct extracted values and SHALL retain both the original AI extraction and the corrected values. |
| **FR-17** | The system SHALL NOT infer or display diagnoses during extraction; extraction SHALL be limited to findings reported in the description. |
| **FR-18** | The system SHALL accept symptom descriptions in English only. The Case Intake Form SHALL instruct staff to enter the description in English and to translate any Filipino or Bikol terms reported by the owner, keeping the owner’s exact wording in quotation marks where the meaning is uncertain. Automatic processing of non-English descriptions is out of scope (Section 1.4). |

## RAG-Based Standardized Prioritization

This feature retrieves the knowledge base passages most relevant to the extracted clinical information and generates a recommendation of exactly one VTL urgency category, a plain-language rationale, and citations to the retrieved passages. Deterministic red-flag safety rules are applied after generation so that critical presentations are never recommended below a veterinarian-defined minimum category.

| **Requirement Number** | **Description** |
|---|---|
| **FR-19** | The system SHALL retrieve the top-k most relevant passages from the active knowledge base version using semantic similarity search, where k is configurable (default 5; final value TBD-7). |
| **FR-20** | The system SHALL generate exactly one urgency category per case from the set {Red, Orange, Yellow, Green, Blue}. |
| **FR-21** | The system SHALL provide a concise, plain-language rationale that refers to the extracted findings and the retrieved passages. |
| **FR-22** | The system SHALL cite at least one retrieved passage for each recommendation and SHALL verify that every cited passage was actually retrieved for that case; recommendations without a valid citation SHALL be labeled low confidence. |
| **FR-23** | The system SHALL apply deterministic red-flag safety rules after generation: when a red flag is detected, the recommended category SHALL NOT be lower than the minimum category assigned to that red flag in the clinical rubric, and the application of the rule SHALL be recorded. |
| **FR-24** | The system SHALL display a confidence indicator (High, Medium, or Low) derived from the model output and retrieval similarity scores, and SHALL flag recommendations below the confidence threshold (TBD-8). |
| **FR-25** | When the evidence supports two adjacent categories equally, the system SHALL recommend the more urgent category in order to minimize under-triage. |
| **FR-26** | The system SHALL record, for each recommendation, the model identifier, prompt version, generation parameters, knowledge base version, retrieved passage IDs, and similarity scores. |
| **FR-27** | The system SHALL allow a Veterinary Reviewer to regenerate the recommendation after correcting extracted information, and SHALL retain every generated version. |
| **FR-28** | The system SHALL NOT produce a diagnosis, prognosis, or treatment recommendation. |

## Triage Review Dashboard

The Triage Review Dashboard is the Human-in-the-Loop interface through which Veterinary Reviewers examine each AI recommendation and make the final triage decision. It consists of the Triage Queue and the Case Review screen described in Section 3.1.

| **Requirement Number** | **Description** |
|---|---|
| **FR-29** | The system SHALL display a Triage Queue of open cases sorted first by urgency category (the confirmed category if available, otherwise the recommended category) and then by arrival time, showing each case’s elapsed waiting time against its target waiting time. |
| **FR-30** | The system SHALL visually alert users when a case’s elapsed waiting time exceeds the target waiting time of its category. |
| **FR-31** | The Case Review screen SHALL display the original description, the extracted information with highlighted evidence, the recommended category with its target waiting time, the rationale, the confidence indicator, and the retrieved references (source title, section, excerpt, and link). |
| **FR-32** | The system SHALL allow a Veterinary Reviewer to confirm the recommended category. |
| **FR-33** | The system SHALL allow a Veterinary Reviewer to adjust the recommendation to any of the five categories and SHALL require a reason selected from a predefined list, with optional free text. |
| **FR-34** | The system SHALL allow a Veterinary Reviewer to mark a case as “Manual triage – AI not applicable” and assign the category manually. |
| **FR-35** | The system SHALL restrict the confirm, adjust, manual triage, and close actions to users with the Veterinary Reviewer role. |
| **FR-36** | The system SHALL clearly indicate whether the displayed category is an AI recommendation pending review or a staff-confirmed decision. |
| **FR-37** | The system SHALL allow Veterinary Reviewers to add clinical notes to a case. |
| **FR-38** | The system SHALL allow a Veterinary Reviewer to close a case (e.g., “Seen by veterinarian”), removing it from the active queue. |
| **FR-39** | The system SHOULD allow the queue to be filtered by species, category, status, and date. |
| **FR-40** | The system MAY allow a one-page triage summary of a case to be printed through the browser. |

## Case Records and Audit Trail

This feature keeps a complete, tamper-evident history of every triage case, including the AI recommendation, the staff’s final decision, and the timestamps of each action. It supports accountability, review of disagreements between the AI and staff, and the evaluation of the project.

| **Requirement Number** | **Description** |
|---|---|
| **FR-41** | The system SHALL log every triage case, including the AI recommendation, the staff’s final decision, and the timestamp of each action. |
| **FR-42** | Each audit entry SHALL include the timestamp, the user ID and role, the action type, the affected record, and the previous and new values where applicable. |
| **FR-43** | Audit entries SHALL be append-only; no user, including Administrators, SHALL be able to modify or delete them through the application. |
| **FR-44** | The system SHALL provide a case history search by case ID, date range, species, presenting complaint, category, and status. |
| **FR-45** | The system SHALL display a chronological audit timeline for each case. |
| **FR-46** | The system SHALL compute and display, for each case, the time from submission to recommendation and from recommendation to the staff decision. |
| **FR-47** | The system SHALL allow Administrators to export de-identified case and audit data in CSV format for evaluation. |
| **FR-48** | The system SHALL NOT allow a finalized decision to be edited; corrections SHALL be recorded as amendments that reference the original decision. |

## Curated Veterinary Knowledge Base Management

This feature maintains the fixed, hand-verified knowledge base that the Prioritization Engine retrieves from. Entries are drafted by Administrators from open-access references, approved by a licensed veterinarian before use, and versioned so that every recommendation can be traced to the exact knowledge base content used.

| **Requirement Number** | **Description** |
|---|---|
| **FR-49** | The system SHALL store each knowledge base entry with its presenting complaint, title, content, discriminators and red flags with their minimum VTL category, species applicability, source reference (title, publisher, URL, and access date), status, reviewer, and approval date. |
| **FR-50** | The system SHALL require a source citation for every entry and SHALL restrict sources to the open-access references in Section 1.5 or additional sources approved by the Veterinary Domain Reviewer. |
| **FR-51** | The system SHALL enforce the entry workflow Draft → Pending Review → Active → Retired, and SHALL use only Active entries for retrieval. |
| **FR-52** | The system SHALL require approval from an account with knowledge base approval permission, held only by licensed veterinarians, before an entry becomes Active. |
| **FR-53** | The system SHALL chunk and embed an entry and update the vector index when the entry is approved or retired. |
| **FR-54** | The system SHALL version the knowledge base and link each recommendation to the knowledge base version used. |
| **FR-55** | The system SHALL NOT update the knowledge base automatically from external sources. |
| **FR-56** | The system SHOULD allow draft entries to be imported in bulk from a structured CSV or JSON file. |

## User Authentication and Access Management

This feature implements the authentication and authorization part of the security framework. It ensures that only registered clinic personnel can use the system and that each user can perform only the functions permitted for the user’s role (Section 5.5).

| **Requirement Number** | **Description** |
|---|---|
| **FR-57** | The system SHALL require authentication with a username or e-mail address and a password before any function can be used. |
| **FR-58** | The system SHALL support the roles Intake Staff, Veterinary Reviewer, and Administrator, and a separate knowledge base approval permission that can be granted to Veterinary Reviewer accounts of licensed veterinarians. |
| **FR-59** | The system SHALL enforce the role permissions defined in Section 5.5. |
| **FR-60** | The system SHALL allow Administrators to create, edit, and deactivate user accounts and to assign roles and permissions. |
| **FR-61** | The system SHALL require users to change a temporary password at first login. |
| **FR-62** | The system SHALL allow users to log out, which terminates the session. |
| **FR-63** | The system SHOULD allow Administrators to reset a user’s password. |

## System Evaluation Support

This feature supports the project evaluation described in Section 1.4 by running a labeled set of 50–100 case vignettes through the same pipeline used for live cases and computing classification, retrieval, and latency metrics. Evaluation data are kept separate from clinical case records.

| **Requirement Number** | **Description** |
|---|---|
| **FR-64** | The system SHALL import a labeled test set of 50–100 vignettes, each with a reference VTL category assigned by the veterinary reviewer and relevance judgments for retrieval. |
| **FR-65** | The system SHALL process evaluation vignettes with the same model, prompts, parameters, and knowledge base version used for live cases, and SHALL store evaluation results separately from clinical case records. |
| **FR-66** | The system SHALL compute classification metrics: accuracy, per-category precision, recall, and F1-score, macro-F1, the confusion matrix, weighted Cohen’s kappa, and the under-triage and over-triage rates. |
| **FR-67** | The system SHALL compute retrieval metrics: Precision@k, Recall@k, Mean Reciprocal Rank (MRR), and nDCG@k. |
| **FR-68** | The system SHALL compute p50 and p95 latency for the end-to-end pipeline and for each stage (extraction, retrieval, and generation). |
| **FR-69** | The system SHALL export evaluation metrics and per-vignette outputs in CSV and JSON formats. |
| **FR-70** | The system SHOULD provide a form to record System Usability Scale (SUS) responses and compute SUS scores. Note: If this form is not implemented, SUS responses will be collected with an external form and scored separately. |
