from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.cases import router as cases_router
from app.api.v1.eval import router as eval_router
from app.api.v1.exports import router as exports_router
from app.api.v1.health import router as health_router
from app.api.v1.kb import router as kb_router
from app.api.v1.users import router as users_router
from app.core.config import AppEnv, get_settings

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(cases_router)
router.include_router(kb_router)
router.include_router(users_router)
router.include_router(eval_router)
router.include_router(exports_router)

if get_settings().app_env is AppEnv.DEV:
    # Demo routes for the RBAC tests; never mounted outside development.
    from app.api.v1.rbac_test import router as rbac_test_router

    router.include_router(rbac_test_router)
