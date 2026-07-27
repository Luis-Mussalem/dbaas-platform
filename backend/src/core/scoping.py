"""
Multi-tenant scoping: restricts queries to the user's company.

Centralizes the per-company authorization rule in a single place, reused both
by dependencies (FastAPI layer) and by services. Backend analogy:
it's a "tenant filter" — equivalent to consistently applying
`WHERE company_id = :user_company` across the whole API, with a bypass for the superuser.

Single rule:
- superuser  → sees all companies (no filter);
- regular user → only their own company_id.
"""
import uuid
from typing import Optional

from fastapi import HTTPException

from src.models.database_instance import DatabaseInstance
from src.models.user import User, UserRole


def visible_company_id(user: User) -> Optional[uuid.UUID]:
    """
    company_id the user can see, or None for "no restriction" (all).

    - regular user → their own company;
    - superuser → the chosen active company (Stage B, via the X-Company-Id header);
      None = none chosen = sees all.
    """
    if user.is_superuser:
        return getattr(user, "active_company_id", None)
    return user.company_id


def scope_instance_query(query, user: User):
    """
    Applies the company filter to a query whose FROM is DatabaseInstance.

    Superuser with no active company: query unchanged (sees all). Otherwise,
    filters by company_id. SQLAlchemy translates `== None` into `IS NULL`, so a
    regular user with no company (edge case) only sees orphan instances.
    """
    company_id = visible_company_id(user)
    if user.is_superuser and company_id is None:
        return query
    return query.filter(DatabaseInstance.company_id == company_id)


def is_company_admin(user: User) -> bool:
    """Returns True if the user is a superuser or the admin of a company."""
    return user.is_superuser or getattr(user, "role", None) == UserRole.ADMIN


def assert_can_manage_target(acting_user: User, target_user: User) -> None:
    """
    Validates whether acting_user can manage target_user.

    Raises HTTPException 404 if:
    - target is a superuser (invisible to a company admin)
    - target belongs to another company (a company admin only manages their own company)

    Rule: a superuser can manage anyone; a company admin only manages
    users of their own company who are not superusers.
    """
    if acting_user.is_superuser:
        return
    if target_user.is_superuser or target_user.company_id != acting_user.company_id:
        raise HTTPException(status_code=404, detail="User not found")
