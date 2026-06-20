from typing import List, Optional, Dict, Any
from datetime import datetime
from io import StringIO
import csv
from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_active_user
from app.models import User, APIKeyStatus
from app.schemas import (
    UsageEventCreate, UsageEventResponse, UsageEventBatchResponse,
    QuotaCheckResponse
)
from app.services.usage_service import UsageService

router = APIRouter(prefix="/usage", tags=["用量上报"])

MAX_EXPORT_LIMIT = 10000
DEFAULT_EXPORT_LIMIT = 5000


@router.post("/report", response_model=UsageEventResponse, status_code=status.HTTP_201_CREATED)
async def report_usage(
    event_data: UsageEventCreate,
    db: Session = Depends(get_db)
):
    event, status_code = UsageService.process_usage_event(db, event_data)

    if status_code == "duplicate":
        return event
    elif status_code == "invalid_api_key":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or disabled API Key"
        )
    elif status_code == "invalid_project":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or inactive project"
        )
    elif status_code == "invalid_tenant":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant"
        )
    elif status_code == "quota_exceeded":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Quota exceeded"
        )
    elif status_code == "success":
        return event
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unknown error processing usage event"
        )


@router.post("/batch", response_model=UsageEventBatchResponse)
async def batch_report_usage(
    events: List[UsageEventCreate],
    db: Session = Depends(get_db)
):
    success_count = 0
    duplicate_count = 0
    rejected_count = 0
    processed_events = []

    for event_data in events:
        event, status_code = UsageService.process_usage_event(db, event_data)

        if status_code == "success":
            success_count += 1
            processed_events.append(event)
        elif status_code == "duplicate":
            duplicate_count += 1
            processed_events.append(event)
        else:
            rejected_count += 1

    return UsageEventBatchResponse(
        success_count=success_count,
        duplicate_count=duplicate_count,
        rejected_count=rejected_count,
        processed_events=processed_events
    )


@router.get("/check-quota", response_model=QuotaCheckResponse)
async def check_quota(
    tenant_id: int,
    project_id: int,
    resource_type: str,
    amount: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.tenant_id and not current_user.is_admin:
        if current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

    return UsageService.check_quota(
        db, tenant_id, project_id, resource_type, amount
    )


@router.get("/current", response_model=List[Dict[str, Any]])
async def get_current_usage(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
    resource_type: Optional[str] = None,
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

    return UsageService.get_current_usage(
        db, tenant_id, project_id, resource_type
    )


@router.get("/events", response_model=Dict[str, Any])
async def get_event_history(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
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

    events, total = UsageService.get_event_history(
        db, tenant_id, project_id, resource_type,
        start_time, end_time, limit, offset
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": events
    }


@router.get("/export")
async def export_usage_events(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = DEFAULT_EXPORT_LIMIT,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if not current_user.is_admin:
        if tenant_id is not None and tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        if current_user.tenant_id:
            tenant_id = current_user.tenant_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required"
            )
    elif not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id is required"
        )

    if limit <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be positive"
        )

    if limit > MAX_EXPORT_LIMIT:
        limit = MAX_EXPORT_LIMIT

    events = UsageService.export_events(
        db, tenant_id, project_id, resource_type,
        start_time, end_time, limit
    )

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "event_id", "project_id", "api_key_prefix", "resource_type",
        "amount", "request_time", "unit_price", "idempotency_key"
    ])

    for event in events:
        writer.writerow([
            event["event_id"],
            event["project_id"],
            event["api_key_prefix"],
            event["resource_type"],
            event["amount"],
            event["request_time"].isoformat() if event["request_time"] else "",
            event["unit_price"],
            event["idempotency_key"]
        ])

    buffer.seek(0)

    filename = f"usage_events_tenant_{tenant_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Total-Count": str(len(events))
        }
    )
