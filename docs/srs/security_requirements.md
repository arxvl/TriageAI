# Security Requirements

TriageAI handles personal information of pet owners and clinical information about their animals. The following requirements protect this data and control access to the system, in accordance with the Data Privacy Act of 2012 [7]:

| **Requirement Number** | **Description** |
|---|---|
| **SR-01** | All functions SHALL require an authenticated session (FR-57). |
| **SR-02** | Passwords SHALL be at least 12 characters long and SHALL be stored only as salted hashes using Argon2id or bcrypt; passwords SHALL NOT be stored or logged in plain text. |
| **SR-03** | An account SHALL be locked for 15 minutes after 5 consecutive failed login attempts. |
| **SR-04** | Sessions SHALL expire after 30 minutes of inactivity; session tokens SHALL be transmitted only in secure, HttpOnly cookies or authorization headers over HTTPS. |
| **SR-05** | Role-based access control SHALL be enforced on the server for every API endpoint, not only in the user interface. |
| **SR-06** | All network traffic SHALL be encrypted in transit using TLS 1.2 or higher (IR-16). |
| **SR-07** | The database and its backups SHOULD be encrypted at rest where the hosting environment supports it. |
| **SR-08** | Only the minimum necessary, de-identified text SHALL be sent to external AI services (IR-20). |
| **SR-09** | All inputs SHALL be validated on the server; database access SHALL use parameterized queries or the ORM to prevent SQL injection; output SHALL be encoded to prevent cross-site scripting; and state-changing requests SHALL be protected against cross-site request forgery. |
| **SR-10** | Owner-provided text SHALL be treated strictly as data in prompts: it SHALL be clearly delimited from system instructions, SHALL NOT be able to override them, and model outputs SHALL be schema-validated. The LLM SHALL have no direct access to the database (prompt-injection mitigation). |
| **SR-11** | Secrets such as API keys and database credentials SHALL be stored in environment variables or a secret store and SHALL NOT be committed to the source repository. |
| **SR-12** | Security events (successful and failed logins, lockouts, role changes, and data exports) SHALL be recorded in the audit trail. |
| **SR-13** | The system and project SHALL comply with the Data Privacy Act of 2012 by collecting only necessary personal information, providing a privacy notice, obtaining informed consent from usability participants, and using the data only for the purposes of this project. |
| **SR-14** | Case data collected during the evaluation SHALL be deleted or irreversibly anonymized within the retention period after the project ends (TBD-11). |
| **SR-15** | The database SHALL be backed up automatically at least once a day during the evaluation period, and the restore procedure SHALL be tested at least once. |
| **SR-16** | Third-party dependencies SHALL be checked for known vulnerabilities (e.g., npm audit, pip-audit) before each release. |
