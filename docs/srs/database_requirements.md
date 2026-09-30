# Database Requirements (DR-XX)

| **Requirement Number** | **Description** | 
| ----- | ----- | 
| **DR-01** | The system SHALL use a relational database with enforced referential integrity. The core entities are User, Role, Case, Signalment, OwnerDescription, ExtractionResult, TriageRecommendation, RetrievedReference, StaffDecision, AuditLog, KnowledgeBaseEntry, KnowledgeBaseVersion, KnowledgeBaseChunk, EvaluationSet, EvaluationRun, and EvaluationResult. The detailed class and domain model will be defined in PD6. | 
| **DR-02** | Each Case SHALL have exactly one original description, zero or more extraction results and recommendations (one per generated version), and at most one final staff decision plus any recorded amendments. | 
| **DR-03** | All timestamps SHALL be stored in UTC and displayed in Philippine Standard Time. | 
| **DR-04** | Owner personal identifiers SHALL be stored separately from the clinical text, with access limited to authorized roles. | 
| **DR-05** | A published knowledge base version SHALL be immutable, and every recommendation SHALL reference the version it used. | 
| **DR-06** | Evaluation data SHALL be stored separately from clinical case data. | 
| **DR-07** | Daily database backups SHALL be retained for at least 7 days during the evaluation period. | 
| **DR-08** | The database design SHALL accommodate at least 10,000 cases and 5,000 knowledge base chunks without changes to the schema. |
