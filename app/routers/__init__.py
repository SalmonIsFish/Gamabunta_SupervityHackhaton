# app/routers/__init__.py
"""
API Routers - Modular endpoint organization.

Note: File endpoints are defined in main.py to maintain proper path ordering.
"""

from .admin import router as admin_router
from .ai_manager import router as ai_manager_router
from .audit import router as audit_router
from .auth import router as auth_router
from .examples import router as examples_router
from .health import router as health_router
from .insights import router as insights_router
from .items import router as items_router
from .policies import router as policies_router
from .workbench import router as workbench_router

__all__ = [
    "health_router",
    "auth_router",
    "admin_router",
    "audit_router",
    "items_router",
    "examples_router",
    "workbench_router",
    "policies_router",
    "insights_router",
    "ai_manager_router",
]
