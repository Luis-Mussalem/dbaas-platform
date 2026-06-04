from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_superuser
from src.models.user import User
from src.schemas.company import CompanyCreate, CompanyRead
from src.services.company import create_company, list_companies

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get("", response_model=list[CompanyRead])
def get_companies(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser),
):
    return list_companies(db)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def post_company(
    data: CompanyCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser),
):
    return create_company(db, data.name)
