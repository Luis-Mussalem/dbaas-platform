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
    summary="Executar um SELECT read-only contra o banco da instância",
)
async def run_query(
    instance_id: uuid.UUID,
    body: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResult:
    """
    Console SQL: executa um único SELECT no banco gerenciado e devolve as linhas.

    Segurança em camadas (defesa em profundidade):
    - ``get_instance_if_running`` aplica o scoping multi-tenant (404 entre
      empresas) e exige status RUNNING (409).
    - O guard SELECT-only rejeita ``;``, DML e DDL com 422.
    - A conexão herda ``statement_timeout=30s`` de ``get_connection``.
    """
    # get_instance_if_running já garante scoping (404) e status RUNNING (409).
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
        # Guard SELECT-only rejeitou a query (`;`, DML, DDL, não-SELECT, tamanho).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except psycopg.Error as exc:
        # SQL sintaticamente válido para o guard, mas rejeitado pelo Postgres
        # (tabela inexistente, erro de sintaxe SQL, permissão negada, timeout).
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
