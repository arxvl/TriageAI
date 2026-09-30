import subprocess
import sys

import app.models  # noqa: F401  (import side effect registers tables on Base.metadata)
from app.db.base import Base

EXPECTED_TABLES = {
    "users",
    "cases",
    "signalments",
    "owner_descriptions",
    "owner_references",
    "extraction_results",
    "extraction_complaints",
    "recommendations",
    "retrieved_references",
    "red_flag_alerts",
    "staff_decisions",
    "clinical_notes",
    "audit_log",
    "jobs",
    "presenting_complaints",
    "kb_entries",
    "red_flag_rules",
    "kb_chunks",
    "kb_versions",
    "kb_version_entries",
    "evaluation_sets",
    "vignettes",
    "evaluation_runs",
    "evaluation_results",
}


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_audit_log_id_is_bigserial_style() -> None:
    from sqlalchemy import BigInteger

    column = Base.metadata.tables["audit_log"].columns["id"]
    assert isinstance(column.type, BigInteger)
    assert column.primary_key


def test_presenting_complaints_pk_is_code() -> None:
    table = Base.metadata.tables["presenting_complaints"]
    assert [c.name for c in table.primary_key.columns] == ["code"]


def test_extraction_results_has_case_xor_vignette_check() -> None:
    from app.models.ai_output import ExtractionResult

    names = {c.name for c in ExtractionResult.__table_args__ if hasattr(c, "name")}
    assert "ck_extraction_results_case_xor_vignette" in names


def test_recommendations_has_case_xor_vignette_check() -> None:
    from app.models.ai_output import Recommendation

    names = {c.name for c in Recommendation.__table_args__ if hasattr(c, "name")}
    assert "ck_recommendations_case_xor_vignette" in names


def test_users_has_can_approve_kb_check() -> None:
    from app.models.user import User

    names = {c.name for c in User.__table_args__ if hasattr(c, "name")}
    assert "ck_users_can_approve_kb_requires_reviewer" in names


def test_staff_decisions_has_reason_code_check() -> None:
    from app.models.decision import StaffDecision

    names = {c.name for c in StaffDecision.__table_args__ if hasattr(c, "name")}
    assert "ck_staff_decisions_reason_code_required_for_adjust" in names


def test_models_import_star_works_as_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "from app.models import *"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
