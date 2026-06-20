from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.models import (
    TenantStatus, APIKeyStatus, BillingPeriod,
    OverLimitAction, AlertThresholdType, AlertSeverity
)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    tenant_id: Optional[int] = None
    is_admin: bool = False


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    tenant_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TenantBase(BaseModel):
    name: str
    status: TenantStatus = TenantStatus.ACTIVE
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    billing_address: Optional[str] = None


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[TenantStatus] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    billing_address: Optional[str] = None


class TenantResponse(TenantBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class ProjectCreate(ProjectBase):
    tenant_id: int


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(ProjectBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class PlanQuotaBase(BaseModel):
    resource_type: str
    limit: float
    unit_price: float = 0.0
    over_limit_price: float = 0.0


class PlanQuotaCreate(PlanQuotaBase):
    pass


class PlanQuotaResponse(PlanQuotaBase):
    id: int
    plan_id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class PlanBase(BaseModel):
    name: str
    description: Optional[str] = None
    billing_period: BillingPeriod = BillingPeriod.MONTHLY
    over_limit_action: OverLimitAction = OverLimitAction.CHARGE
    is_active: bool = True


class PlanCreate(PlanBase):
    tenant_id: int
    quotas: List[PlanQuotaCreate] = Field(default_factory=list)


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    billing_period: Optional[BillingPeriod] = None
    over_limit_action: Optional[OverLimitAction] = None
    is_active: Optional[bool] = None


class PlanResponse(PlanBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: Optional[datetime]
    quotas: List[PlanQuotaResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PlanAssignmentCreate(BaseModel):
    plan_id: int
    project_id: int
    effective_from: datetime
    effective_to: Optional[datetime] = None


class PlanAssignmentResponse(BaseModel):
    id: int
    plan_id: int
    project_id: int
    plan_name: str
    effective_from: datetime
    effective_to: Optional[datetime]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class APIKeyCreate(BaseModel):
    project_id: int
    name: str
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    id: int
    project_id: int
    key_prefix: str
    name: str
    status: APIKeyStatus
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class APIKeyCreateResponse(APIKeyResponse):
    api_key: str


class APIKeyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[APIKeyStatus] = None


class UsageEventCreate(BaseModel):
    api_key: str = Field(..., description="API Key")
    tenant_id: int = Field(..., description="租户ID")
    project_id: int = Field(..., description="项目ID")
    idempotency_key: str = Field(..., description="幂等键")
    resource_type: str = Field(..., description="资源类型")
    amount: float = Field(..., gt=0, description="消耗量")
    request_time: datetime = Field(..., description="请求时间")


class UsageEventResponse(BaseModel):
    id: int
    tenant_id: int
    project_id: int
    api_key_id: int
    idempotency_key: str
    resource_type: str
    amount: float
    unit_price: float
    request_time: datetime
    received_at: datetime
    is_processed: bool

    model_config = ConfigDict(from_attributes=True)


class UsageEventBatchResponse(BaseModel):
    success_count: int
    duplicate_count: int
    rejected_count: int
    processed_events: List[UsageEventResponse]


class BillingCycleResponse(BaseModel):
    id: int
    tenant_id: int
    period: BillingPeriod
    cycle_start: datetime
    cycle_end: datetime
    is_closed: bool
    total_amount: float
    created_at: datetime
    closed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class UsageAggregationResponse(BaseModel):
    id: int
    billing_cycle_id: int
    project_id: int
    resource_type: str
    total_usage: float
    over_limit_usage: float
    total_cost: float
    limit: float
    percentage: float
    unit_price: float
    over_limit_price: float
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class BillPreviewResponse(BaseModel):
    billing_cycle: BillingCycleResponse
    total_amount: float
    aggregations: List[UsageAggregationResponse]
    summary: Dict[str, Any]


class AlertRuleBase(BaseModel):
    name: str
    resource_type: Optional[str] = None
    threshold_type: AlertThresholdType = AlertThresholdType.PERCENTAGE
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    is_active: bool = True


class AlertRuleCreate(AlertRuleBase):
    tenant_id: int


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    resource_type: Optional[str] = None
    threshold_type: Optional[AlertThresholdType] = None
    threshold: Optional[float] = None
    severity: Optional[AlertSeverity] = None
    is_active: Optional[bool] = None


class AlertRuleResponse(AlertRuleBase):
    id: int
    tenant_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertRecordResponse(BaseModel):
    id: int
    tenant_id: int
    alert_rule_id: Optional[int]
    project_id: Optional[int]
    resource_type: str
    threshold: float
    current_usage: float
    percentage: float
    severity: AlertSeverity
    message: str
    is_acknowledged: bool
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[int]
    acknowledge_note: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertAcknowledgeRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=1000, description="确认备注")


class AlertBatchAcknowledgeRequest(BaseModel):
    record_ids: List[int] = Field(..., description="告警记录ID列表")
    note: Optional[str] = Field(None, max_length=1000, description="确认备注")


class AlertBatchAcknowledgeResponse(BaseModel):
    success_count: int
    failed_count: int
    failed_ids: List[int]
    details: Optional[Dict[int, str]] = None


class QuotaCheckResponse(BaseModel):
    allowed: bool
    reason: Optional[str] = None
    current_usage: float
    limit: float
    percentage: float
    over_limit_action: OverLimitAction
