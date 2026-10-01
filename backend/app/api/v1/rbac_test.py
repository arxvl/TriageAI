"""Demo routes that exist only to prove `require_role` works (P03 task 7).

Mounted only when `APP_ENV=dev`, hidden from the OpenAPI schema, and used by
`tests/integration/test_rbac.py` to assert the 401/403 behaviour without having
to depend on a real feature endpoint. Delete nothing here when later phases add
real routes: the RBAC tests stay pinned to these.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.models import User, UserRole

router = APIRouter(prefix="/_rbac-test", tags=["_rbac-test"], include_in_schema=False)


@router.get("/reviewer")
def reviewer_only(
    user: Annotated[User, Depends(require_role(UserRole.VETERINARY_REVIEWER))],
) -> dict[str, str]:
    return {"role": user.role.value}


@router.get("/kb-approver")
def kb_approver_only(
    user: Annotated[User, Depends(require_role(UserRole.VETERINARY_REVIEWER, kb_approver=True))],
) -> dict[str, str]:
    return {"role": user.role.value, "can_approve_kb": str(user.can_approve_kb)}
