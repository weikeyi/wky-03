from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_active_user
from app.models import User, BillingPeriod
from app.schemas import BillPreviewResponse, BillingCycleResponse
from app.services.billing_service import BillingService
from app.services.billing_cycle_service import BillingCycleService

router = APIRouter(prefix="/billing", tags=["账单"])


@router.get("/preview", response_model=BillPreviewResponse)
async def get_bill_preview(
    tenant_id: Optional[int] = None,
    period: BillingPeriod = BillingPeriod.MONTHLY,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.tenant_id and not current_user.is_admin:
        tenant_id = current_user.tenant_id
    elif not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id is required"
        )

    return BillingService.get_bill_preview(db, tenant_id, period, project_id)


@router.get("/cycles", response_model=List[BillingCycleResponse])
async def get_billing_cycles(
    tenant_id: Optional[int] = None,
    period: Optional[BillingPeriod] = None,
    include_closed: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.tenant_id and not current_user.is_admin:
        tenant_id = current_user.tenant_id
    elif not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id is required"
        )

    return BillingCycleService.get_cycles(db, tenant_id, period, include_closed, limit)


@router.get("/cycles/{cycle_id}", response_model=BillingCycleResponse)
async def get_billing_cycle(
    cycle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    cycle = BillingCycleService.get_cycle_by_id(db, cycle_id)
    if not cycle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing cycle not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != cycle.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return cycle


@router.post("/cycles/{cycle_id}/close", response_model=BillingCycleResponse)
async def close_billing_cycle(
    cycle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    cycle = BillingCycleService.get_cycle_by_id(db, cycle_id)
    if not cycle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing cycle not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != cycle.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    closed_cycle = BillingCycleService.close_cycle(db, cycle_id)
    if not closed_cycle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Billing cycle already closed"
        )

    db.commit()
    return closed_cycle


@router.get("/history", response_model=List[Dict[str, Any]])
async def get_billing_history(
    tenant_id: Optional[int] = None,
    period: Optional[BillingPeriod] = None,
    limit: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.tenant_id and not current_user.is_admin:
        tenant_id = current_user.tenant_id
    elif not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id is required"
        )

    return BillingService.get_billing_history(db, tenant_id, period, limit)
