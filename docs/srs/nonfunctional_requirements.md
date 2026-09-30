## Nonfunctional Requirements (NFR-XX)

## Performance Requirements

Triage is time-sensitive: a recommendation that arrives too late provides little value at the front desk and may delay care. The following requirements ensure that TriageAI does not slow down the intake process. Latency is reported as p50 (median) and p95 (95th percentile) values computed from the server-side timestamps recorded for each case (FR-46, FR-68). The initial targets will be validated through benchmarking of the prototype (TBD-9).

| **Requirement Number** | **Description** | 
| ----- | ----- | 
| **NFR-01** | The end-to-end time from case submission to the display of the recommendation SHALL be no more than 10 seconds at p50 and no more than 20 seconds at p95, with up to 10 concurrent users. | 
| **NFR-02** | The retrieval step SHALL complete within 1 second at p95 for a knowledge base of up to 5,000 indexed passages. | 
| **NFR-03** | The Triage Queue and Case Review screens SHALL load within 2 seconds at p95, excluding AI processing time. | 
| **NFR-04** | Confirm, adjust, and close actions SHALL be saved and reflected in the Triage Queue within 2 seconds at p95. | 
| **NFR-05** | Red-flag alerts from the deterministic pre-screen (FR-12) SHALL appear within 2 seconds of submission, independently of LLM response time. | 
| **NFR-06** | The system SHALL support at least 10 concurrent authenticated users and at least 200 new cases per day without exceeding the limits in NFR-01 to NFR-04. | 

## Safety Requirements

An incorrect urgency recommendation can cause harm. Under-triage (a category lower than the patient needs) may delay care for a critically ill animal and could contribute to its deterioration or death, while over-triage reduces the efficiency of the clinic. The following safeguards reduce these risks:

| **Requirement Number** | **Description** | 
| ----- | ----- | 
| **NFR-07** | No urgency category SHALL be treated as final until a Veterinary Reviewer has confirmed or adjusted it; unconfirmed recommendations SHALL always be displayed as pending (Human-in-the-Loop). | 
| **NFR-08** | The red-flag safety floor (FR-23) SHALL be active at all times. Changes to red-flag rules SHALL require approval by the Veterinary Domain Reviewer and SHALL be recorded in the audit trail. | 
| **NFR-09** | If any AI component is unavailable, times out, or returns an error, the system SHALL still allow cases to be created and triaged manually, SHALL display the message “AI unavailable – triage manually using the VTL” together with the VTL reference, and SHALL NOT silently drop any case. | 
| **NFR-10** | Every recommendation SHALL display a disclaimer stating that it is decision support only and does not replace the clinical judgment of veterinary staff. | 
| **NFR-11** | The system SHALL NOT automatically change a category that has been confirmed or adjusted by staff. | 
| **NFR-12** | Rationales and references SHALL be grounded only in retrieved knowledge base passages; recommendations whose citations do not match the retrieved passages SHALL be flagged (FR-22) to reduce the risk of fabricated (“hallucinated”) content. | 
| **NFR-13** | Out-of-scope inputs (species other than dogs and cats, unsupported complaints, or non-clinical text) SHALL be flagged for manual triage rather than forced into a category. | 
| **NFR-14** | Evaluation reports SHALL list every under-triaged vignette, and these cases SHALL be reviewed by the Veterinary Domain Reviewer before any usability session with veterinary staff. | 
| **NFR-15** | When the system is used with real patients during the evaluation period, it SHALL be operated alongside, and not in place of, the clinic’s standard triage procedure. | 

## Software Quality Attributes

Where quality attributes conflict, the following order of precedence applies: safety and correctness, then transparency, then usability, then performance, then maintainability. The target values for correctness and retrieval relevance are preliminary and will be confirmed with the course instructor and the veterinary domain reviewer (TBD-10).

| **Requirement Number** | **Description** | 
| ----- | ----- | 
| **NFR-16** | Correctness: On the labeled test set, the system SHALL achieve a macro-F1 of at least 0.70 across the five VTL categories, a recall of at least 0.90 for the combined Red and Orange categories, and an under-triage rate of no more than 10%. | 
| **NFR-17** | Retrieval relevance: The retriever SHALL achieve a Recall@5 of at least 0.80 and an MRR of at least 0.70 on the relevance-labeled test set. | 
| **NFR-18** | Transparency: 100% of displayed recommendations SHALL include a rationale and at least one validated reference to the knowledge base. | 
| **NFR-19** | Usability: The mean System Usability Scale score from evaluation participants SHALL be at least 68, the commonly used benchmark for average usability [9]. | 
| **NFR-20** | Learnability: After an orientation of no more than 15 minutes, a new Veterinary Reviewer SHALL be able to open, review, and confirm or adjust a case without assistance within 3 minutes in at least 90% of trials. | 
| **NFR-21** | Accessibility: The user interface SHALL conform to WCAG 2.1 Level AA [8], including a text contrast ratio of at least 4.5:1 and full keyboard operability. | 
| **NFR-22** | Reliability and availability: The system SHALL be available at least 95% of the time during scheduled evaluation sessions, and no confirmed decision SHALL be lost. | 
| **NFR-23** | Reproducibility: Re-running the same vignette set with the same recorded configuration (model, prompt version, parameters, and knowledge base version) SHALL produce the same category for at least 95% of the vignettes. | 
| **NFR-24** | Maintainability: The extraction, retrieval, generation, safety-rule, and persistence functions SHALL be implemented as separate modules, and the LLM provider SHALL be replaceable by changing only its adapter and configuration (IR-12). | 
| **NFR-25** | Testability: Automated unit tests SHALL cover at least 60% of the backend core modules, and every SHALL requirement SHALL be traceable to at least one test case by PD8. | 
| **NFR-26** | Portability: The system SHALL be deployable on any Linux host that supports Docker by following the README, using a single Docker Compose command. | 
| **NFR-27** | Localization: The user interface, the supported input, and the documentation SHALL be in English. All interface text SHALL be stored in resource files so that a Filipino translation can be added in a later release without code changes. | 
| **NFR-28** | Sustainability and cost efficiency: The system SHALL avoid redundant LLM calls by storing results and re-processing a case only when its input is edited, and SHALL record AI service usage so that it can be kept within the project budget (PD4). | 
