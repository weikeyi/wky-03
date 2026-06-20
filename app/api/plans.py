from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_active_user
from app.models import Plan, PlanQuota, PlanAssignment, Tenant, Project, User
from app.schemas import (
    PlanCreate, PlanUpdate, PlanResponse, PlanQuotaCreate,
    PlanQuotaResponse, PlanAssignmentCreate, PlanAssignmentResponse
)

router = APIRouter(prefix="/plans", tags=["套餐"])


@router.post("", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    plan_data: PlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != plan_data.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot create plan for other tenants"
            )

    tenant = db.query(Tenant).filter(Tenant.id == plan_data.tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )

    plan = Plan(
        name=plan_data.name,
        description=plan_data.description,
        tenant_id=plan_data.tenant_id,
        billing_period=plan_data.billing_period,
        over_limit_action=plan_data.over_limit_action,
        is_active=plan_data.is_active
    )

    for quota_data in plan_data.quotas:
        quota = PlanQuota(**quota_data.model_dump())
        plan.quotas.append(quota)

    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("", response_model=List[PlanResponse])
async def get_plans(
    tenant_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(Plan)

    if current_user.tenant_id and not current_user.is_admin:
        query = query.filter(Plan.tenant_id == current_user.tenant_id)
    elif tenant_id:
        query = query.filter(Plan.tenant_id == tenant_id)

    if is_active is not None:
        query = query.filter(Plan.is_active == is_active)

    return query.offset(skip).limit(limit).all()


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != plan.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return plan


@router.put("/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: int,
    plan_data: PlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != plan.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    update_data = plan_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)

    db.commit()
    db.refresh(plan)
    return plan


@router.post("/{plan_id}/quotas", response_model=PlanQuotaResponse, status_code=status.HTTP_201_CREATED)
async def add_plan_quota(
    plan_id: int,
    quota_data: PlanQuotaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != plan.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    existing_quota = db.query(PlanQuota).filter(
        PlanQuota.plan_id == plan_id,
        PlanQuota.resource_type == quota_data.resource_type
    ).first()

    if existing_quota:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quota for resource type {quota_data.resource_type} already exists"
        )

    quota = PlanQuota(plan_id=plan_id, **quota_data.model_dump())
    db.add(quota)
    db.commit()
    db.refresh(quota)
    return quota


@router.post("/assignments", response_model=PlanAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def assign_plan(
    assignment_data: PlanAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    plan = db.query(Plan).filter(Plan.id == assignment_data.plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    project = db.query(Project).filter(Project.id == assignment_data.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != plan.tenant_id or current_user.tenant_id != project.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    db.query(PlanAssignment).filter(
        PlanAssignment.project_id == assignment_data.project_id,
        PlanAssignment.is_active == True
    ).update({"is_active": False, "effective_to": assignment_data.effective_from})

    assignment = PlanAssignment(
        plan_id=assignment_data.plan_id,
        project_id=assignment_data.project_id,
        effective_from=assignment_data.effective_from,
        effective_to=assignment_data.effective_to,
        is_active=True
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return PlanAssignmentResponse(
        id=assignment.id,
        plan_id=assignment.plan_id,
        project_id=assignment.project_id,
        plan_name=plan.name,
        effective_from=assignment.effective_from,
        effective_to=assignment.effective_to,
        is_active=assignment.is_active
    )


@router.get("/{plan_id}/assignments", response_model=List[PlanAssignmentResponse])
async def get_plan_assignments(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != plan.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    assignments = db.query(PlanAssignment).filter(
        PlanAssignment.plan_id == plan_id
    ).all()

    return [
        PlanAssignmentResponse(
            id=a.id,
            plan_id=a.plan_id,
            project_id=a.project_id,
            plan_name=plan.name,
            effective_from=a.effective_from,
            effective_to=a.effective_to,
            is_active=a.is_active
        )
        for a in assignments
    ]
