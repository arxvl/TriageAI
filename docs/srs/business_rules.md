# Business Rules (BR-XX)

The following operating principles govern the use of TriageAI. They are not functional requirements themselves, but they are enforced through the functional and security requirements above.

| **Rule Number** | **Description** |
|---|---|
| **BR-01** | AI recommendations are advisory. The final urgency category is always decided by an authorized Veterinary Reviewer. |
| **BR-02** | Only Veterinary Reviewers may confirm, adjust, manually triage, or close a case. Intake Staff may create and view cases and must immediately notify a Veterinary Reviewer of any red-flag alert. |
| **BR-03** | When the staff decision differs from the AI recommendation, the staff decision prevails and a reason must be recorded. |
| **BR-04** | Only licensed veterinarians holding the knowledge base approval permission may approve knowledge base entries and red-flag rules. |
| **BR-05** | Only Administrators may manage user accounts, draft knowledge base entries, run evaluations, and export data. |
| **BR-06** | Cases involving species other than dogs and cats, or unsupported presenting complaints, are triaged manually according to clinic procedure. |
| **BR-07** | Finalized case records and audit entries are not deleted during the evaluation period; corrections are made only as recorded amendments. |
| **BR-08** | Exported data must be de-identified and used solely for the academic evaluation of this project. |
| **BR-09** | During the evaluation period, the system is used alongside, and not in place of, the clinic’s standard triage procedure for real patients. |

The permissions of each role are summarized in the following matrix:

| **Function** | **Intake Staff** | **Veterinary Reviewer** | **Administrator** |
|---|---|---|---|
| **Create a case and submit a description** | Yes | Yes | No |
| **View the Triage Queue, recommendations, and red-flag alerts** | Yes | Yes | View only |
| **Edit extracted information and regenerate a recommendation** | No | Yes | No |
| **Confirm, adjust, manually triage, or close a case** | No | Yes | No |
| **View case history and audit timeline** | Yes | Yes | Yes |
| **Create, edit, and submit knowledge base drafts** | No | No | Yes |
| **Approve or reject knowledge base entries and red-flag rules** | No | Yes (with approval permission) | No |
| **Manage user accounts and roles** | No | No | Yes |
| **Import vignettes, run evaluations, and export data** | No | No | Yes |
