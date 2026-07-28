"""
Multi-tenant scoping: restricts queries to the user's company.

Centralizes the per-company authorization rule in a single place, reused both by
dependencies (FastAPI layer) and by services. Backend analogy: it's a "tenant
filter" — equivalent to consistently applying `WHERE company_id = :user_company`
across the whole API, with a bypass for the superuser.

Three cases, and it matters that they are THREE and not two:

- superuser with no active company → sees everything (no filter);
- anyone with a company → filtered to that company;
- regular user with NO company → sees NOTHING.

The third case is why ``CompanyScope`` exists instead of a bare
``Optional[uuid.UUID]``. A plain "None means no filter" collapses "sees
everything" and "belongs to nowhere" into the same value, and every consumer that
read it as "no restriction" would hand a company-less account the entire
platform's dashboard, alerts and audit trail. Encoding the distinction in the type
makes the dangerous reading unspellable: a caller has to go through
``apply_to`` / ``unrestricted``, both of which treat the two cases differently.

A company-less regular account is a half-provisioned one (open registration, or a
company removed with ON DELETE SET NULL). The safe reading of "belongs to no
company" is "entitled to nothing", never "entitled to the unassigned pile".
"""
import uuid
from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa
from fastapi import HTTPException

from src.models.database_instance import DatabaseInstance
from src.models.user import User, UserRole


@dataclass(frozen=True)
class CompanyScope:
    """
    The set of companies a request may read, as an explicit value.

    ``unrestricted`` → the platform superuser with no workspace selected; no filter
    is applied at all. Otherwise ``company_id`` is the single company in scope, and
    ``None`` there means the empty scope: no company, therefore no rows.
    """

    company_id: Optional[uuid.UUID]
    unrestricted: bool

    @property
    def is_empty(self) -> bool:
        """True when the scope selects nothing at all."""
        return not self.unrestricted and self.company_id is None

    def apply_to(self, query, column):
        """
        Filters `query` by `column` (a company_id column) according to this scope.

        `column` is passed in rather than hardcoded because the same scope is
        applied to different tables — DatabaseInstance.company_id when listing
        instances, AuditLog.company_id when reading the audit trail.
        """
        if self.unrestricted:
            return query
        if self.company_id is None:
            return query.filter(sa.false())
        return query.filter(column == self.company_id)


def company_scope(user: User) -> CompanyScope:
    """
    Resolves what `user` is allowed to see.

    - superuser → the workspace picked in the switcher (Stage B, the X-Company-Id
      header, parked on the user by dependencies.get_current_user); none picked =
      unrestricted;
    - regular user → their own company, empty scope when they have none.
    """
    if user.is_superuser:
        active = getattr(user, "active_company_id", None)
        return CompanyScope(company_id=active, unrestricted=active is None)
    return CompanyScope(company_id=user.company_id, unrestricted=False)


def visible_company_id(user: User) -> Optional[uuid.UUID]:
    """
    The single company `user` is scoped to, or None when not scoped to exactly one.

    Thin accessor kept for the places that legitimately need just the id — most
    notably assigning ``company_id`` to a row the user is CREATING (an instance is
    filed under the workspace on screen). Do NOT use it to build read filters:
    None is ambiguous there, which is what ``CompanyScope`` exists to prevent.
    """
    return company_scope(user).company_id


def scope_instance_query(query, user: User):
    """Applies the company filter to a query whose FROM is DatabaseInstance."""
    return company_scope(user).apply_to(query, DatabaseInstance.company_id)


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

    The company-less admin (company_id NULL) is covered by the second condition:
    NULL != NULL is false in Python, so `target.company_id != acting.company_id`
    is False when both are None — hence the explicit guard below, which keeps a
    company-less admin from managing other company-less accounts.
    """
    if acting_user.is_superuser:
        return
    if acting_user.company_id is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.is_superuser or target_user.company_id != acting_user.company_id:
        raise HTTPException(status_code=404, detail="User not found")
