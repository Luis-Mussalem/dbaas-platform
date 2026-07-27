import asyncio
import uuid

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.dependencies import (
    get_current_user,
    get_db,
    get_instance_if_running,
)
from src.models.user import User
from src.schemas.query import QueryRequest, QueryResult
from src.services import query as query_service

router = APIRouter(
    prefix="/instances",
    tags=["SQL Console"],
)


@router.post(
    "/{instance_id}/query",
    response_model=QueryResult,
    summary="Run a read-only SELECT against the instance's database",
)
async def run_query(
    instance_id: uuid.UUID,
    body: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResult:
    """
    SQL Console: runs a single SELECT against the managed database and returns the rows.

    Layered security (defense in depth):
    - ``get_instance_if_running`` applies multi-tenant scoping (404 across
      companies) and requires RUNNING status (409).
    - The SELECT-only guard rejects ``;``, DML, and DDL with 422.
    - The connection inherits ``statement_timeout=30s`` from ``get_connection``.
    """
    # get_instance_if_running already ensures scoping (404) and RUNNING status (409).
    instance = get_instance_if_running(instance_id, db, current_user)
    if not instance.connection_uri:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance has no connection URI — provisioning may not be complete",
        )

    try:
        columns, rows, truncated = await asyncio.to_thread(
            query_service.execute_read_only, instance, body.query
        )
    except ValueError as exc:
        # The SELECT-only guard rejected the query (`;`, DML, DDL, non-SELECT, size).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except psycopg.Error as exc:
        # SQL that's syntactically valid for the guard, but rejected by Postgres
        # (table doesn't exist, SQL syntax error, permission denied, timeout).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc).strip(),
        ) from exc

    return QueryResult(
        instance_id=instance_id,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
