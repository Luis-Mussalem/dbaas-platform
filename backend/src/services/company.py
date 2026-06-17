import uuid

from sqlalchemy.orm import Session

from src.models.company import Company


def list_companies(db: Session) -> list[Company]:
    return db.query(Company).order_by(Company.name).all()


def get_company_by_id(db: Session, company_id: uuid.UUID) -> Company | None:
    return db.query(Company).filter(Company.id == company_id).first()


def create_company(db: Session, name: str) -> Company:
    company = Company(name=name)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company
