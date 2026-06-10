from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.firm import Firm
from app.models.job import Job
from app.models.user import User
from app.schemas.api import FirmCreate, FirmOut, FirmUpdate, ScrapeRunOut
from app.services.scraper_service import run_scrape

router = APIRouter()


def _to_out(db: Session, firm: Firm) -> FirmOut:
    total = db.query(Job).filter(Job.firm_id == firm.id, Job.status != "REMOVED").count()
    out = FirmOut.model_validate(firm)
    out.total_jobs = total
    return out


@router.get("", response_model=list[FirmOut])
def list_firms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [_to_out(db, f) for f in db.query(Firm).order_by(Firm.name).all()]


@router.post("", response_model=FirmOut)
def create_firm(
    body: FirmCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    firm = Firm(**body.model_dump())
    db.add(firm)
    db.commit()
    db.refresh(firm)
    return _to_out(db, firm)


@router.get("/{firm_id}", response_model=FirmOut)
def get_firm(
    firm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    firm = db.query(Firm).filter(Firm.id == firm_id).first()
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    return _to_out(db, firm)


@router.patch("/{firm_id}", response_model=FirmOut)
def update_firm(
    firm_id: int,
    body: FirmUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    firm = db.query(Firm).filter(Firm.id == firm_id).first()
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(firm, key, value)
    db.commit()
    db.refresh(firm)
    return _to_out(db, firm)


@router.post("/{firm_id}/run", response_model=ScrapeRunOut)
def run_firm_now(
    firm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    firm = db.query(Firm).filter(Firm.id == firm_id).first()
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    return run_scrape(db, firm=firm)
