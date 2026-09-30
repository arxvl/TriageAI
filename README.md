# TriageAI

TriageAI is a transformer-based NLP system that helps veterinary clinic staff
prioritize incoming dog and cat cases. Intake staff enter the owner's free-text
description of a pet's symptoms; an AI pipeline extracts clinical details and
recommends one of five Veterinary Triage List (VTL) urgency categories with a
rationale and cited knowledge-base passages; a veterinary reviewer confirms or
adjusts the recommendation before it is finalized. The system provides
decision support only — it never diagnoses, never recommends treatment, and
never finalizes a category without a human decision.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- API: http://localhost:8000/api/v1
- API docs: http://localhost:8000/docs

## Disclaimer
The system provides decision support only. It never diagnoses, never recommends treatment, and
never finalizes a category without a human decision.
