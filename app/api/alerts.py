from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_active_user
from app.models import User, AlertRule, AlertRecord, AlertSeverity
from app.schemas import (
    AlertRuleCreate, AlertRuleUpdate, AlertRuleResponse,
    AlertRecordResponse
)

router = APIRouter(prefix="/alerts", tags=["告警"])


@router.post("/rules", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    rule_data: AlertRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != rule_data.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot create alert rule for other tenants"
            )

    existing_rule = db.query(AlertRule).filter(
        AlertRule.tenant_id == rule_data.tenant_id,
        AlertRule.name == rule_data.name
    ).first()

    if existing_rule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alert rule with this name already exists"
        )

    db_rule = AlertRule(**rule_data.model_dump())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.get("/rules", response_model=List[AlertRuleResponse])
async def get_alert_rules(
    tenant_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    severity: Optional[AlertSeverity] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(AlertRule)

    if current_user.tenant_id and not current_user.is_admin:
        query = query.filter(AlertRule.tenant_id == current_user.tenant_id)
    elif tenant_id:
        query = query.filter(AlertRule.tenant_id == tenant_id)

    if is_active is not None:
        query = query.filter(AlertRule.is_active == is_active)

    if severity:
        query = query.filter(AlertRule.severity == severity)

    return query.offset(skip).limit(limit).all()


@router.get("/rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert rule not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != rule.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return rule


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: int,
    rule_data: AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert rule not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != rule.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    update_data = rule_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)

    db.commit()
    db.refresh(rule)
    return rule


@router.get("/records", response_model=List[AlertRecordResponse])
async def get_alert_records(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
    severity: Optional[AlertSeverity] = None,
    is_acknowledged: Optional[bool] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(AlertRecord)

    if current_user.tenant_id and not current_user.is_admin:
        query = query.filter(AlertRecord.tenant_id == current_user.tenant_id)
    elif tenant_id:
        query = query.filter(AlertRecord.tenant_id == tenant_id)

    if project_id:
        query = query.filter(AlertRecord.project_id == project_id)

    if severity:
        query = query.filter(AlertRecord.severity == severity)

    if is_acknowledged is not None:
        query = query.filter(AlertRecord.is_acknowledged == is_acknowledged)

    if start_time:
        query = query.filter(AlertRecord.created_at >= start_time)

    if end_time:
        query = query.filter(AlertRecord.created_at <= end_time)

    return query.order_by(AlertRecord.created_at.desc())\
        .offset(skip).limit(limit).all()


@router.get("/records/{record_id}", response_model=AlertRecordResponse)
async def get_alert_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    record = db.query(AlertRecord).filter(AlertRecord.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert record not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != record.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return record


@router.post("/records/{record_id}/acknowledge", response_model=AlertRecordResponse)
async def acknowledge_alert(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    record = db.query(AlertRecord).filter(
        AlertRecord.id == record_id,
        AlertRecord.is_acknowledged == False
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert record not found or already acknowledged"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != record.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    record.is_acknowledged = True
    record.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return record
