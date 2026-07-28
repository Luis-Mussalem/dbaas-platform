import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from src.models.user import UserRole
from src.schemas.company import CompanyRead

# UserRole is re-exported so `from src.schemas.user import UserRole` keeps working.
# It is NOT redefined here: this module used to declare a second, identical str-enum,
# and the two only interoperated by accident — a str-mixin enum member hashes and
# compares like its value, so `schemas.UserRole.ADMIN == models.UserRole.ADMIN` was
# True and SQLAlchemy's enum lookup happened to accept the wrong class. Any change
# that broke that coincidence (dropping the `str` mixin, renaming a value on one
# side) would have failed at runtime, in the persistence layer, with no type error
# to warn anyone. One definition, in the model, is the source of truth.
__all__ = [
    "PASSWORD_MIN_LENGTH",
    "UserAdminCreate",
    "UserAdminUpdate",
    "UserBase",
    "UserCreate",
    "UserListItem",
    "UserRead",
    "UserRole",
    "UserUpdate",
    "validate_password_strength",
]

PASSWORD_MIN_LENGTH = 12
PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~])"
)


def validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if not PASSWORD_PATTERN.match(password):
        raise ValueError(
            "Password must contain at least one uppercase letter, "
            "one lowercase letter, one digit, and one special character"
        )
    return password


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    is_superuser: bool
    role: UserRole
    company_id: Optional[uuid.UUID] = None
    company: Optional[CompanyRead] = None
    created_at: datetime
    updated_at: datetime


class UserListItem(UserRead):
    # Only the (admin) listing endpoint populates last_activity — hence a
    # dedicated schema, so as not to leak an always-null field in /auth/me, register, etc.
    # Value derived from MAX(timestamp) in audit_logs (a transient attribute on the
    # ORM instance), not a column of the users table.
    last_activity: Optional[datetime] = None


class UserUpdate(BaseModel):
    """
    Self-service update of one's own account (PATCH /users/{id}).

    `current_password` is mandatory whenever `email` or `password` changes. Both
    fields are account-recovery handles: without re-authentication, a stolen access
    token (30 min of validity) could be traded for permanent ownership of the
    account — change the password and the real owner is locked out, change the
    email and the reset flow points at the attacker. Asking for the current
    password means possession of a token is not by itself possession of the
    account. Enforced in services.user.update_user_self.
    """

    email: Optional[EmailStr] = None
    password: Optional[str] = None
    current_password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_password_strength(v)
        return v


class UserAdminCreate(UserBase):
    password: str
    company_id: Optional[uuid.UUID] = None
    is_superuser: bool = False
    role: UserRole = UserRole.MEMBER

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserAdminUpdate(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    company_id: Optional[uuid.UUID] = None
    role: Optional[UserRole] = None