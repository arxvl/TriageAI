# Database Requirements (DR)

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Source:** SRS v1.1. IDs and the text in the Description column are authoritative: do not renumber, reword, or delete them. Priority follows the SRS keyword (`SHALL` = Must, `SHOULD` = Should, `MAY` = May).
**Sibling files:** [functional](functional-requirements.md) · [non-functional](non-functional-requirements.md) · [interface](interface-requirements.md) · [business rules](business-rules.md) · [database](database-requirements.md) · [security](security-requirements.md)

**Coverage:** DR-01 to DR-08, 8 requirements, no gaps.

The physical schema follows [ADR-04](../adr/ADR-04-postgres-pgvector.md) (one PostgreSQL 16 instance with pgvector) and [ADR-12](../adr/ADR-12-append-only-audit.md) (immutability enforced in the database). All schema changes go through Alembic migrations; no manual schema edits.

| ID | Requirement | Description | Priority | Implementation constraint | Acceptance criteria | Related |
|---|---|---|---|---|---|---|
| **DR-01** | Relational database with referential integrity | The system SHALL use a relational database with enforced referential integrity. The core entities are User, Role, Case, Signalment, OwnerDescription, ExtractionResult, TriageRecommendation, RetrievedReference, StaffDecision, AuditLog, KnowledgeBaseEntry, KnowledgeBaseVersion, KnowledgeBaseChunk, EvaluationSet, EvaluationRun, and EvaluationResult. The detailed class and domain model will be defined in PD6. | Must | PostgreSQL 16 with foreign keys and check constraints; the domain model is PD6. | Migrations create all listed entities; constraint violations are rejected by the database. | ADR-04, FR-41 |
| **DR-02** | Case cardinality | Each Case SHALL have exactly one original description, zero or more extraction results and recommendations (one per generated version), and at most one final staff decision plus any recorded amendments. | Must | One description per case; extraction and recommendation rows are versioned; one effective decision plus amendments. | A second decision without amends_id is rejected; version numbers increase per case. | FR-16, FR-27, FR-48 |
| **DR-03** | UTC storage, PST display | All timestamps SHALL be stored in UTC and displayed in Philippine Standard Time. | Must | All timestamps stored in UTC; the front end renders Asia/Manila. | No stored timestamp carries a local offset; the UI shows PST consistently. | IR-17, FR-42 |
| **DR-04** | Separated owner identifiers | Owner personal identifiers SHALL be stored separately from the clinical text, with access limited to authorized roles. | Must | Owner name and contact live in `owner_references`, isolated from clinical text and AI processing. | No pipeline or export query selects from owner_references; it appears in no API response. | FR-07, IR-20, ADR-10 |
| **DR-05** | Immutable published KB versions | A published knowledge base version SHALL be immutable, and every recommendation SHALL reference the version it used. | Must | A published version and its entry list cannot change; every recommendation stores its version. | An UPDATE on kb_version_entries is rejected by the trigger; recommendations carry kb_version_id. | FR-54, ADR-14, ADR-12 |
| **DR-06** | Separated evaluation data | Evaluation data SHALL be stored separately from clinical case data. | Must | Vignettes, runs and results are stored apart from clinical case tables. | Evaluation rows use vignette_id; a row carrying both case_id and vignette_id is rejected. | FR-65, BR-08 |
| **DR-07** | Backup retention | Daily database backups SHALL be retained for at least 7 days during the evaluation period. | Must | Daily encrypted dumps retained for at least 7 days during evaluation. | The backup container produces a dump per day and prunes beyond 7; a restore has been tested once. | SR-15, ADR-13 |
| **DR-08** | Capacity | The database design SHALL accommodate at least 10,000 cases and 5,000 knowledge base chunks without changes to the schema. | Must | Schema supports at least 10,000 cases and 5,000 KB chunks unchanged. | Index plan and HNSW parameters hold at that size without schema change. | NFR-02, NFR-06, ADR-04 |

## Notes

- **The `embedding` column and the HNSW index are not part of the initial migration.** They are added in a later migration once the embedding model and its dimension are fixed (guide M4), because the column type depends on that choice ([ADR-07](../adr/ADR-07-local-embedding-model.md)).
- **DR-05 is enforced by a trigger,** not only by service code: `kb_version_entries` rejects UPDATE. The same mechanism protects `audit_log` and `owner_descriptions`.
- **Knowledge-base chunks are never deleted** even when an entry is retired, because stored references point at them. Retirement removes the entry from newer published versions instead.
- **DR-08 capacity** is comfortably within pgvector's HNSW range at the stated parameters; revisit `hnsw.ef_search` if the KB grows beyond a few thousand chunks.
