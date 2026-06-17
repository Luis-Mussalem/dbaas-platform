"""
Scoping multi-tenant: restringe consultas à empresa do usuário.

Centraliza a regra de autorização por empresa num único lugar, reusado tanto
pelas dependencies (camada FastAPI) quanto pelos services. Analogia backend:
é um "tenant filter" — equivalente a aplicar `WHERE company_id = :user_company`
de forma consistente em toda a API, com bypass para o superuser.

Regra única:
- superuser  → enxerga todas as empresas (sem filtro);
- usuário comum → apenas a própria company_id.
"""
import uuid
from typing import Optional

from fastapi import HTTPException

from src.models.database_instance import DatabaseInstance
from src.models.user import User, UserRole


def visible_company_id(user: User) -> Optional[uuid.UUID]:
    """
    company_id que o usuário pode enxergar, ou None para "sem restrição" (todas).

    - usuário comum → a própria empresa;
    - superuser → a empresa-ativa escolhida (Stage B, via header X-Company-Id);
      None = nenhuma escolhida = vê todas.
    """
    if user.is_superuser:
        return getattr(user, "active_company_id", None)
    return user.company_id


def scope_instance_query(query, user: User):
    """
    Aplica o filtro de empresa a uma query cujo FROM é DatabaseInstance.

    Superuser sem empresa-ativa: query inalterada (vê todas). Caso contrário,
    filtra por company_id. SQLAlchemy traduz `== None` em `IS NULL`, então um
    usuário comum sem empresa (borda) só enxerga instâncias órfãs.
    """
    company_id = visible_company_id(user)
    if user.is_superuser and company_id is None:
        return query
    return query.filter(DatabaseInstance.company_id == company_id)


def is_company_admin(user: User) -> bool:
    """Retorna True se o usuário é superuser ou admin de uma empresa."""
    return user.is_superuser or getattr(user, "role", None) == UserRole.ADMIN


def assert_can_manage_target(acting_user: User, target_user: User) -> None:
    """
    Valida se acting_user pode gerenciar target_user.

    Raises HTTPException 404 se:
    - target é superuser (infovisível a company admin)
    - target pertence a outra empresa (company admin só gerencia sua própria empresa)

    Regra: superuser pode gerenciar qualquer um; company admin só gerencia
    usuários da própria empresa que não são superuser.
    """
    if acting_user.is_superuser:
        return
    if target_user.is_superuser or target_user.company_id != acting_user.company_id:
        raise HTTPException(status_code=404, detail="User not found")
