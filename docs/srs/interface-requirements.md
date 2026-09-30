# Interface Requirements (IR)

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Source:** SRS v1.1. IDs and the text in the Description column are authoritative: do not renumber, reword, or delete them. Priority follows the SRS keyword (`SHALL` = Must, `SHOULD` = Should, `MAY` = May).
**Sibling files:** [functional](functional-requirements.md) · [non-functional](non-functional-requirements.md) · [interface](interface-requirements.md) · [business rules](business-rules.md) · [database](database-requirements.md) · [security](security-requirements.md)

**Coverage:** IR-01 to IR-22, 22 requirements, no gaps.

The visual reference for all UI requirements is `docs/prototype/TriageAI_Prototype.html`; wireframe IDs (W-01 to W-11) are cited in the Related column.

## User interfaces (3.1)

The normative visual reference is `docs/prototype/TriageAI_Prototype.html` (W-01 to W-11). Presentation decisions are recorded in [ADR-15](../adr/ADR-15-review-ui-and-vtl-presentation.md).

| ID | Requirement | Description | Priority | Acceptance criteria | Related |
|---|---|---|---|---|---|
| **IR-01** | Responsive web UI | The user interface SHALL be a responsive web application that is fully usable at 1280 × 720 pixels on desktop computers and at a minimum width of 768 pixels on tablets. | Must | Usable at 1280×720; at 768 px the queue table becomes cards (W-11). | NFR-03, ADR-02 |
| **IR-02** | Persistent header | Every screen after login SHALL display a persistent header containing the system name, the logged-in user’s name and role, navigation to the Triage Queue, a Help link, and a Logout button. | Must | Header shows system name, user name and role, navigation, Help and Logout on every screen after login. | FR-59, W-02 |
| **IR-03** | VTL badge presentation | VTL categories SHALL be displayed consistently as color-coded badges (Red, Orange, Yellow, Green, Blue) that always include the category name and target waiting time as text, so that meaning is never conveyed by color alone. | Must | Every badge renders colour + category name + target time; a colour-only badge fails the component test. | FR-20, NFR-21, ADR-15 |
| **IR-04** | AI content labelling | AI-generated content SHALL be visually distinguished from staff-entered content and labeled “AI Recommendation – requires staff confirmation” until a Veterinary Reviewer confirms or adjusts it. | Must | The "AI Recommendation – requires staff confirmation" chip is present until a decision exists. | FR-36, NFR-07 |
| **IR-05** | Plain-language errors | Error messages SHALL be written in plain language, state what went wrong and how to correct it, and appear next to the related field; technical codes and stack traces SHALL NOT be shown to users. | Must | Errors state cause and fix next to the field; no stack trace or raw code reaches the UI. | FR-04, SR-09 |
| **IR-06** | Decision-support notice | Every recommendation SHALL be accompanied by a visible notice that TriageAI is a decision-support tool and does not provide a diagnosis. | Must | The disclaimer is visible on W-04 and W-06 whenever a recommendation is shown. | NFR-10, BR-09 |
| **IR-07** | Keyboard and WCAG 2.1 AA | All interactive elements SHALL be operable by keyboard and SHALL conform to WCAG 2.1 Level AA [8]. | Must | All actions reachable by keyboard; dialogs trap focus; axe-core passes on the core screens. | NFR-21 |
| **IR-08** | Confirmation before irreversible actions | The system SHALL request confirmation before irreversible actions, such as finalizing a triage decision or retiring a knowledge base entry. | Must | Confirm, close and retire show a confirmation dialog before committing. | FR-38, FR-51 |

## Hardware interfaces (3.2)

Deployment sizing follows [ADR-13](../adr/ADR-13-docker-compose-single-vm.md).

| ID | Requirement | Description | Priority | Acceptance criteria | Related |
|---|---|---|---|---|---|
| **IR-09** | No special client hardware | The system SHALL NOT require any specialized hardware on the client side beyond a device capable of running a supported web browser. | Must | The SPA runs in a current browser with no plugin or local install. | IR-01, ADR-02 |
| **IR-10** | Server hardware baseline | The server SHALL run on commodity hardware with a minimum of 2 virtual CPUs, 4 GB of RAM, and 20 GB of storage when a hosted LLM API is used. If a locally served model is selected (TBD-1), a GPU with sufficient memory for the chosen model SHALL be provided. | Must | The evaluation VM meets the stated minimum; a GPU is required only for a locally served LLM. | ADR-06, ADR-13 |

## Software interfaces (3.3)

Internal ports and contracts follow [ADR-06](../adr/ADR-06-llm-provider-adapter.md), [ADR-07](../adr/ADR-07-local-embedding-model.md) and [ADR-17](../adr/ADR-17-mock-first-stage-registry.md).

| ID | Requirement | Description | Priority | Acceptance criteria | Related |
|---|---|---|---|---|---|
| **IR-11** | OpenAPI 3 REST API | The Backend API SHALL expose RESTful endpoints documented in an OpenAPI 3 specification. | Must | `/openapi.json` is complete and generates the typed front-end client. | ADR-03, ADR-02 |
| **IR-12** | LLM provider interface | Access to the LLM SHALL be encapsulated behind an internal model-provider interface so that the model or provider can be replaced by changing only the provider adapter and configuration. | Must | Switching provider changes only the adapter class and `.env`; no pipeline code changes. | NFR-24, ADR-06, ADR-17 |
| **IR-13** | Structured JSON extraction | The Clinical Entity Extraction Service SHALL request structured JSON output from the LLM and validate it against the defined extraction schema before it is stored or passed to the next component. | Must | Model output is validated against the extraction schema before storage or use. | FR-09, FR-15 |
| **IR-14** | Retrieval-only grounding | The Prioritization Engine SHALL supply the LLM only with passages retrieved from the active version of the curated knowledge base. | Must | The generation prompt contains only passages retrieved from the active KB version. | FR-19, FR-54, ADR-05 |
| **IR-15** | Versioned internal schemas | Data shared between components (case identifier, extraction result, recommendation, and audit event) SHALL follow a common, versioned JSON schema. | Must | Shared payloads use the Pydantic contracts in `app/pipeline/types.py`; changes are versioned. | FR-26, ADR-17 |

## Communications interfaces (3.4)

Transport, secrets and outbound-call behaviour. IR-20 is the privacy boundary described in [ADR-10](../adr/ADR-10-deidentification-fail-closed.md).

| ID | Requirement | Description | Priority | Acceptance criteria | Related |
|---|---|---|---|---|---|
| **IR-16** | TLS for client traffic | All communication between the web client and the Backend API SHALL use HTTPS with TLS 1.2 or higher; plain HTTP requests SHALL be redirected to HTTPS. | Must | HTTP is redirected to HTTPS; TLS 1.2+ only at the proxy. | SR-06, ADR-13 |
| **IR-17** | JSON, UTF-8, ISO 8601 | API messages SHALL use JSON encoded in UTF-8, and timestamps SHALL use ISO 8601 format with time zone information; times are displayed in Philippine Standard Time (UTC+08:00). | Must | API payloads are UTF-8 JSON; timestamps are ISO 8601 UTC, displayed in PST. | DR-03 |
| **IR-18** | Server-side AI calls and secrets | Calls to external LLM and embedding services SHALL be made only from the server over HTTPS. API keys SHALL be stored as server-side environment variables or secrets and SHALL NOT be sent to the browser or committed to the source repository. | Must | No API key reaches the browser or the repository; all outbound AI calls originate on the server. | SR-11, ADR-06 |
| **IR-19** | Timeouts and retries | Outbound AI service requests SHALL use a timeout (initial value: 30 seconds) and at most two retries with exponential backoff. If the request still fails, the case SHALL be set to “Manual Triage Required” and the user notified. | Must | Outbound AI calls use the configured timeout and bounded retries; exhaustion routes to manual triage. | FR-15, NFR-09, ADR-08 |
| **IR-20** | De-identification before transmission | Before any text is transmitted to an external service, the system SHALL remove owner names, contact numbers, e-mail addresses, and street addresses from the text. | Must | Owner name, contact numbers, e-mail and addresses are removed before any external call; failure stops the call. | FR-07, SR-08, ADR-10 |
| **IR-21** | No e-mail or SMS in the MVP | The MVP SHALL NOT send e-mail or SMS messages. E-mail notifications (e.g., for password reset) MAY be added in a later release. | Must | No outbound mail or SMS integration exists in the PD8 build. | FR-08, FR-63 |
| **IR-22** | Queue auto-refresh | The Triage Queue SHOULD refresh automatically, by polling at intervals of no more than 15 seconds or through a WebSocket connection, so that new cases and alerts appear without a manual page reload. | Should | The queue updates within 15 s without a manual reload; polling pauses on a hidden tab. | FR-29, ADR-08 |

## Notes

- **IR-19** allows up to two retries. The pipeline implementation uses one retry for schema failures plus the provider-level retry budget; the total must stay inside the job timeout (`2 × timeout_s + 10`). Do not raise retries without re-checking NFR-01.
- **IR-20 is a hard boundary, not a filter step.** If de-identification fails, the pipeline stops before the external call ([ADR-10](../adr/ADR-10-deidentification-fail-closed.md)).
- **IR-22** is satisfied by 15-second polling; the WebSocket option in the requirement text is permitted but not implemented ([ADR-08](../adr/ADR-08-async-jobs-polling.md)).
- **IR-10** states the SRS minimum (2 vCPU, 4 GB RAM). The deployment target in [ADR-13](../adr/ADR-13-docker-compose-single-vm.md) is 2 vCPU / 8 GB / 40 GB because the local embedding model runs in the backend container; the larger figure governs provisioning.
