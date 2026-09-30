"""Seed the development database with fictitious reference data.

Everything here is invented for development (CLAUDE.md §9): no real person,
pet, clinic or clinical source appears in this file.

The script is idempotent. Each row is looked up by its natural key and
inserted only when missing; an existing row is never overwritten, so a local
edit survives a re-run. To pick up a change made to the tables below, use
`--reset` (development only), which empties the database and re-seeds it.

    python -m scripts.seed
    python -m scripts.seed --reset
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import AppEnv, Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    KBVersion,
    PresentingComplaint,
    RedFlagRule,
    Species,
    User,
    UserRole,
    VTLCategory,
)

# A deliberately weak, publicly documented development credential. Every seeded
# account carries must_change_password=True, so it cannot survive first login.
SEED_PASSWORD = "ChangeMe!2026"  # noqa: S105


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: UserRole
    can_approve_kb: bool = False


# KB approval is a separate capability from the role, and only a Veterinary
# Reviewer may hold it (CLAUDE.md §6, ck_users_can_approve_kb_requires_reviewer).
USERS: tuple[SeedUser, ...] = (
    SeedUser("admin@triageai.local", "A. Dela Cruz", UserRole.ADMINISTRATOR),
    SeedUser("intake@triageai.local", "J. Cruz", UserRole.INTAKE_STAFF),
    SeedUser("reviewer@triageai.local", "Dr. M. Santos", UserRole.VETERINARY_REVIEWER),
    SeedUser(
        "approver@triageai.local",
        "Dr. A. Rivera",
        UserRole.VETERINARY_REVIEWER,
        can_approve_kb=True,
    ),
)

# The 20 supported presenting complaints (SRS §4.2.1), plus OTHER for anything
# the extractor cannot map (FR-10). Codes are stable: they are foreign keys
# from kb_entries and are stored in extraction results.
COMPLAINTS: tuple[tuple[str, str], ...] = (
    ("RESPIRATORY_DISTRESS", "Difficulty breathing"),
    ("COLLAPSE", "Collapse or sudden weakness"),
    ("SEIZURES", "Seizures"),
    ("TRAUMA", "Trauma or injury"),
    ("BLEEDING", "Bleeding"),
    ("VOMITING", "Vomiting"),
    ("DIARRHEA", "Diarrhea"),
    ("TOXIN_INGESTION", "Suspected toxin ingestion"),
    ("FOREIGN_BODY", "Suspected foreign body"),
    ("URINARY_OBSTRUCTION", "Straining to urinate or unable to urinate"),
    ("ABDOMINAL_DISTENSION", "Abdominal distension or bloating"),
    ("DYSTOCIA", "Difficult birth"),
    ("HEAT_STRESS", "Heat stress"),
    ("LETHARGY", "Lethargy"),
    ("INAPPETENCE", "Loss of appetite"),
    ("COUGH_SNEEZE", "Coughing or sneezing"),
    ("LAMENESS", "Lameness or limping"),
    ("EYE", "Eye problem"),
    ("SKIN_ITCH", "Skin problem or itching"),
    ("EAR", "Ear problem"),
)

OTHER_COMPLAINT = ("OTHER", "Other or unsupported complaint")
OTHER_SORT_ORDER = 999


@dataclass(frozen=True)
class SeedRedFlagRule:
    code: str
    label: str
    min_category: VTLCategory
    species: tuple[Species, ...]


# Placeholder — replaced by vet-approved rules in P08/M5.
#
# These exist so the FR-23 safety floor has rules to apply while the pipeline
# runs on mocks. Every row carries is_placeholder=True and has no approver:
# nothing here has been reviewed by a veterinarian, and P08 will not treat an
# unapproved rule as clinical content.
BOTH_SPECIES = (Species.DOG, Species.CAT)

RED_FLAG_RULES: tuple[SeedRedFlagRule, ...] = (
    SeedRedFlagRule("NOT_BREATHING", "Not breathing", VTLCategory.RED, BOTH_SPECIES),
    SeedRedFlagRule("UNRESPONSIVE", "Unresponsive", VTLCategory.RED, BOTH_SPECIES),
    SeedRedFlagRule("ACTIVE_SEIZURE", "Seizure in progress", VTLCategory.RED, BOTH_SPECIES),
    SeedRedFlagRule(
        "UNCONTROLLED_BLEEDING", "Bleeding that will not stop", VTLCategory.RED, BOTH_SPECIES
    ),
    SeedRedFlagRule("PALE_OR_BLUE_GUMS", "Pale or bluish gums", VTLCategory.RED, BOTH_SPECIES),
    SeedRedFlagRule(
        "MALE_CAT_NO_URINE",
        "Male cat straining with no urine passed",
        VTLCategory.ORANGE,
        (Species.CAT,),
    ),
    SeedRedFlagRule(
        "TOXIN_INGESTION", "Suspected toxin ingestion", VTLCategory.ORANGE, BOTH_SPECIES
    ),
)

SEED_KB_VERSION_NO = 0
SEED_KB_VERSION_NOTE = "Seed – no entries"

# Not part of Base.metadata, so a reset has to restart it by name.
CASE_NO_SEQUENCE = "case_no_seq"


@dataclass
class SeedReport:
    """How many rows each step created, and how many were already there."""

    created: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def record(self, table: str, *, created: int, skipped: int) -> None:
        self.created[table] = created
        self.skipped[table] = skipped

    @property
    def total_created(self) -> int:
        return sum(self.created.values())

    def lines(self) -> list[str]:
        return [
            f"  {table:<22} created {self.created[table]:>3}  existing {self.skipped[table]:>3}"
            for table in self.created
        ]


def _get_or_create(
    session: Session,
    model: type,
    *,
    lookup: dict[str, object],
    build: Callable[[], object],
) -> bool:
    """Insert a row when no row matches `lookup`. True when one was created."""
    existing = session.query(model).filter_by(**lookup).one_or_none()
    if existing is not None:
        return False
    session.add(build())
    session.flush()
    return True


def seed_users(session: Session, report: SeedReport) -> None:
    created = 0
    for seed_user in USERS:
        if _get_or_create(
            session,
            User,
            lookup={"email": seed_user.email},
            build=lambda u=seed_user: User(
                full_name=u.full_name,
                email=u.email,
                password_hash=hash_password(SEED_PASSWORD),
                role=u.role,
                can_approve_kb=u.can_approve_kb,
                is_active=True,
                must_change_password=True,
                failed_login_count=0,
            ),
        ):
            created += 1
    report.record("users", created=created, skipped=len(USERS) - created)


def seed_presenting_complaints(session: Session, report: SeedReport) -> None:
    rows = [(code, name, order) for order, (code, name) in enumerate(COMPLAINTS, start=1)] + [
        (OTHER_COMPLAINT[0], OTHER_COMPLAINT[1], OTHER_SORT_ORDER)
    ]

    created = 0
    for code, name, sort_order in rows:
        if _get_or_create(
            session,
            PresentingComplaint,
            lookup={"code": code},
            build=lambda c=code, n=name, s=sort_order: PresentingComplaint(
                code=c, name=n, sort_order=s
            ),
        ):
            created += 1
    report.record("presenting_complaints", created=created, skipped=len(rows) - created)


def seed_red_flag_rules(session: Session, report: SeedReport) -> None:
    created = 0
    for rule in RED_FLAG_RULES:
        if _get_or_create(
            session,
            RedFlagRule,
            lookup={"code": rule.code},
            build=lambda r=rule: RedFlagRule(
                code=r.code,
                label=r.label,
                min_category=r.min_category,
                species=list(r.species),
                entry_id=None,
                is_placeholder=True,
                approved_by=None,
                approved_at=None,
            ),
        ):
            created += 1
    report.record("red_flag_rules", created=created, skipped=len(RED_FLAG_RULES) - created)


def seed_kb_version(session: Session, report: SeedReport) -> None:
    """Create the empty KB version 0.

    It has no entries and no publisher: it exists so a recommendation produced
    while the mocks run has a kb_version_id to point at. The first real version
    is published through the P08 approval workflow.
    """
    created = int(
        _get_or_create(
            session,
            KBVersion,
            lookup={"version_no": SEED_KB_VERSION_NO},
            build=lambda: KBVersion(
                version_no=SEED_KB_VERSION_NO,
                published_at=None,
                published_by=None,
                note=SEED_KB_VERSION_NOTE,
            ),
        )
    )
    report.record("kb_versions", created=created, skipped=1 - created)


def seed(session: Session) -> SeedReport:
    """Insert the seed rows that are missing. Flushes; never commits.

    The caller owns the transaction, which is what lets the tests run this
    inside a session that is rolled back afterwards.
    """
    report = SeedReport()
    seed_users(session, report)
    seed_presenting_complaints(session, report)
    seed_red_flag_rules(session, report)
    seed_kb_version(session, report)
    return report


def reset(settings: Settings) -> None:
    """Empty every application table, for development only.

    Two things make this safe to keep in the repository:

    1. It refuses to run unless APP_ENV is `dev`.
    2. It connects as the database owner (MIGRATION_DATABASE_URL). It has to:
       the application role has no TRUNCATE privilege on anything, and no
       DELETE at all on audit_log (migration 0002).

    TRUNCATE does not fire the `prevent_modify()` trigger, so this does erase
    the append-only audit log (FR-43, ADR-12). That is the point of the two
    guards above — a reset is a developer wiping a scratch database, never an
    operation the running application can perform.

    `alembic_version` is untouched: it is not part of Base.metadata, so it is
    excluded by construction rather than by a name check.
    """
    if settings.app_env is not AppEnv.DEV:
        raise RuntimeError(
            f"--reset is a development-only operation and APP_ENV is "
            f"'{settings.app_env.value}'. It truncates every table, including "
            f"the append-only audit log."
        )

    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    engine = create_engine(settings.migration_database_url)
    try:
        with engine.begin() as connection:
            # One statement, so the foreign keys between these tables do not
            # dictate an order. S608: table names come from the model metadata.
            connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))  # noqa: S608
            # A standalone sequence, not owned by a column, so RESTART IDENTITY
            # above does not reach it.
            connection.execute(text(f"ALTER SEQUENCE {CASE_NO_SEQUENCE} RESTART WITH 1"))
    finally:
        engine.dispose()


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed",
        description="Seed the database with fictitious development data.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="development only: empty every table first, then re-seed",
    )
    args = parser.parse_args(argv)
    settings = settings or get_settings()

    if args.reset:
        try:
            reset(settings)
        except RuntimeError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print("Reset: all application tables truncated.")

    with SessionLocal() as session:
        report = seed(session)
        session.commit()

    print("Seeded:")
    for line in report.lines():
        print(line)
    if report.total_created == 0:
        print("Nothing to do — the database was already seeded.")
    else:
        print(f"\nSign in with any seeded account using the password {SEED_PASSWORD!r};")
        print("each one must change it on first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
