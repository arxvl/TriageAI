# Interface Requirements (IR-XX)

## User Interfaces

TriageAI provides a browser-based graphical user interface. This section defines the logical characteristics of the interface; the detailed wireframes and prototype screens will be documented in PD7. The following standards apply to every screen:

| **Requirement Number** | **Description** |
|---|---|
| **IR-01** | The user interface SHALL be a responsive web application that is fully usable at 1280 × 720 pixels on desktop computers and at a minimum width of 768 pixels on tablets. |
| **IR-02** | Every screen after login SHALL display a persistent header containing the system name, the logged-in user’s name and role, navigation to the Triage Queue, a Help link, and a Logout button. |
| **IR-03** | VTL categories SHALL be displayed consistently as color-coded badges (Red, Orange, Yellow, Green, Blue) that always include the category name and target waiting time as text, so that meaning is never conveyed by color alone. |
| **IR-04** | AI-generated content SHALL be visually distinguished from staff-entered content and labeled “AI Recommendation – requires staff confirmation” until a Veterinary Reviewer confirms or adjusts it. |
| **IR-05** | Error messages SHALL be written in plain language, state what went wrong and how to correct it, and appear next to the related field; technical codes and stack traces SHALL NOT be shown to users. |
| **IR-06** | Every recommendation SHALL be accompanied by a visible notice that TriageAI is a decision-support tool and does not provide a diagnosis. |
| **IR-07** | All interactive elements SHALL be operable by keyboard and SHALL conform to WCAG 2.1 Level AA [8]. |
| **IR-08** | The system SHALL request confirmation before irreversible actions, such as finalizing a triage decision or retiring a knowledge base entry. |

The major screens of the system are summarized below.

| **Screen** | **Purpose and Key Elements** | **Primary Users** |
|---|---|---|
| **Login** | Username or email and password fields, Log In button, and error feedback for failed attempts. | All users |
| **Case Intake Form** | Species selector (Dog/Cat), optional signalment (pet name, age, sex and neuter status, breed, weight), intake channel, a free-text area for the owner’s description with a character counter, an optional owner reference field, and a Submit button with a processing indicator. | Intake Staff, Veterinary Reviewers |
| **Triage Queue** | List of open cases sorted by urgency and arrival time showing arrival time, elapsed waiting time, species, primary complaint, recommended and confirmed category, status, and red-flag icons; filters by species, category, status, and date. | Intake Staff, Veterinary Reviewers |
| **Case Review (Triage Review Dashboard)** | Three panels: (1) the original description with extracted phrases highlighted; (2) the extracted clinical information in editable fields, including missing-information prompts; (3) the recommendation panel with VTL badge, target waiting time, rationale, confidence indicator, and retrieved references (source, section, excerpt, link). Actions: Confirm, Adjust Category (with required reason), Mark for Manual Triage, Add Note, Close Case. | Veterinary Reviewers (Intake Staff: view only) |
| **Case History and Audit View** | Search by case ID, date range, species, complaint, category, and status; a chronological audit timeline for each case. | All users (by role) |
| **Knowledge Base Management** | List of entries by status (Draft, Pending Review, Active, Retired), entry editor with source citation fields, approval and rejection actions, and version history. | Administrator, Veterinary Domain Reviewer |
| **User Management** | Create, edit, and deactivate accounts; assign roles and knowledge base approval permission. | Administrator |
| **Evaluation Console** | Import labeled vignettes, start evaluation runs, and view and export metric reports. | Administrator |

## Hardware Interfaces

TriageAI has no dedicated hardware interfaces. It does not connect to medical devices, patient monitors, scanners, or other clinic hardware, which are outside the scope of this project (Section 1.4). Users interact with the system only through the standard input and output devices of their client computers or tablets (keyboard, mouse or touchpad, touchscreen, and display) by way of the web browser.

| **Requirement Number** | **Description** |
|---|---|
| **IR-09** | The system SHALL NOT require any specialized hardware on the client side beyond a device capable of running a supported web browser. |
| **IR-10** | The server SHALL run on commodity hardware with a minimum of 2 virtual CPUs, 4 GB of RAM, and 20 GB of storage when a hosted LLM API is used. If a locally served model is selected (TBD-1), a GPU with sufficient memory for the chosen model SHALL be provided. |

## Software Interfaces

The software components with which TriageAI interacts, together with the data exchanged, are listed below. The named technologies are the team’s proposed choices and will be confirmed in the Tools/Technologies/Platforms section of PD4.

| **Component** | **Proposed Software (Version)** | **Purpose and Data Exchanged** |
|---|---|---|
| **Web client** | React 18 (JavaScript/TypeScript) | Renders the user interface; sends intake data and staff decisions to the Backend API and receives case, recommendation, and audit data as JSON. |
| **Backend API** | Python 3.11+, FastAPI | Exposes REST endpoints, validates requests, orchestrates the triage pipeline, and enforces authentication and authorization. |
| **Relational database** | PostgreSQL 15+ via SQLAlchemy ORM | Stores users, roles, cases, extraction results, recommendations, staff decisions, audit records, and knowledge base metadata. |
| **Vector index** | pgvector extension for PostgreSQL | Stores embeddings of knowledge base passages and performs top-k similarity search for retrieval. |
| **Language model** | Transformer-based LLM (TBD-1), via provider REST API or local inference server | Input: de-identified description, instructions, and output schema (extraction); extracted entities and retrieved passages (prioritization). Output: extraction JSON; VTL category, rationale, and cited passage IDs. |
| **Embedding model** | Pretrained sentence-embedding model (TBD-2) | Converts knowledge base passages and retrieval queries into vectors. |
| **Authentication** | JWT library; Argon2id or bcrypt password hashing | Issues and validates session tokens and protects stored passwords. |
| **Operating system and containers** | Ubuntu Server 22.04 LTS or later; Docker and Docker Compose | Hosts and isolates the application services. |
| **Evaluation libraries** | scikit-learn and custom IR metric scripts | Compute classification and retrieval metrics and export reports as CSV or JSON. |

| **Requirement Number** | **Description** |
|---|---|
| **IR-11** | The Backend API SHALL expose RESTful endpoints documented in an OpenAPI 3 specification. |
| **IR-12** | Access to the LLM SHALL be encapsulated behind an internal model-provider interface so that the model or provider can be replaced by changing only the provider adapter and configuration. |
| **IR-13** | The Clinical Entity Extraction Service SHALL request structured JSON output from the LLM and validate it against the defined extraction schema before it is stored or passed to the next component. |
| **IR-14** | The Prioritization Engine SHALL supply the LLM only with passages retrieved from the active version of the curated knowledge base. |
| **IR-15** | Data shared between components (case identifier, extraction result, recommendation, and audit event) SHALL follow a common, versioned JSON schema. |

## Communications Interfaces

TriageAI communicates over standard web protocols. The following requirements apply:

| **Requirement Number** | **Description** |
|---|---|
| **IR-16** | All communication between the web client and the Backend API SHALL use HTTPS with TLS 1.2 or higher; plain HTTP requests SHALL be redirected to HTTPS. |
| **IR-17** | API messages SHALL use JSON encoded in UTF-8, and timestamps SHALL use ISO 8601 format with time zone information; times are displayed in Philippine Standard Time (UTC+08:00). |
| **IR-18** | Calls to external LLM and embedding services SHALL be made only from the server over HTTPS. API keys SHALL be stored as server-side environment variables or secrets and SHALL NOT be sent to the browser or committed to the source repository. |
| **IR-19** | Outbound AI service requests SHALL use a timeout (initial value: 30 seconds) and at most two retries with exponential backoff. If the request still fails, the case SHALL be set to “Manual Triage Required” and the user notified. |
| **IR-20** | Before any text is transmitted to an external service, the system SHALL remove owner names, contact numbers, e-mail addresses, and street addresses from the text. |
| **IR-21** | The MVP SHALL NOT send e-mail or SMS messages. E-mail notifications (e.g., for password reset) MAY be added in a later release. |
| **IR-22** | The Triage Queue SHOULD refresh automatically, by polling at intervals of no more than 15 seconds or through a WebSocket connection, so that new cases and alerts appear without a manual page reload. |
