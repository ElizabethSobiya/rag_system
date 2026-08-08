"""Version 1 API route aggregation."""

from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.history import router as history_router
from app.api.v1.query import router as query_router

router = APIRouter()
router.include_router(documents_router)
router.include_router(history_router)
router.include_router(query_router)
