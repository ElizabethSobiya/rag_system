"""Query history endpoints."""
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.document import SearchHistory
from app.schemas.query import SearchHistoryList, SearchHistoryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/", response_model=SearchHistoryList)
async def list_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    count_result = await db.execute(select(func.count(SearchHistory.id)))
    total = count_result.scalar_one()

    stmt = (
        select(SearchHistory)
        .order_by(SearchHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return SearchHistoryList(
        items=[SearchHistoryResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.delete("/{entry_id}", status_code=204)
async def delete_history_entry(
    request: Request,
    entry_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = delete(SearchHistory).where(SearchHistory.id == entry_id)
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="History entry not found.")
    logger.info(
        "History entry deleted: id=%s ip=%s",
        entry_id,
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown"),
    )


@router.delete("/", status_code=204)
async def clear_history(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    count_result = await db.execute(select(func.count(SearchHistory.id)))
    total = count_result.scalar_one()
    await db.execute(delete(SearchHistory))
    await db.commit()
    logger.warning(
        "All history cleared: entries=%d ip=%s",
        total,
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown"),
    )
