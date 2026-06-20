from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class APIKeyStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


class BillingPeriod(str, enum.Enum):
    DAILY = "daily"
    MONTHLY = "monthly"


class OverLimitAction(str, enum.Enum):
    REJECT = "reject"
    CHARGE = "charge"


class AlertThresholdType(str, enum.Enum):
    PERCENTAGE = "percentage"
    ABSOLUTE = "absolute"


class AlertSeverity(str, enum.Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="users")


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    status = Column(Enum(TenantStatus), default=TenantStatus.ACTIVE, nullable=False)
    contact_email = Column(String(100))
    contact_phone = Column(String(20))
    billing_address = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    users = relationship("User", back_populates="tenant")
    projects = relationship("Project", back_populates="tenant")
    plans = relationship("Plan", back_populates="tenant")
    billing_cycles = relationship("BillingCycle", back_populates="tenant")
    alert_rules = relationship("AlertRule", back_populates="tenant")
    alert_records = relationship("AlertRecord", back_populates="tenant")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="projects")
    api_keys = relationship("APIKey", back_populates="project")
    usage_events = relationship("UsageEvent", back_populates="project")
    usage_aggregations = relationship("UsageAggregation", back_populates="project")
    plan_assignments = relationship("PlanAssignment", back_populates="project")

    __table_args__ = (
        UniqueConstraint('tenant_id', 'name', name='_tenant_project_uc'),
    )


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    billing_period = Column(Enum(BillingPeriod), default=BillingPeriod.MONTHLY, nullable=False)
    over_limit_action = Column(Enum(OverLimitAction), default=OverLimitAction.CHARGE, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="plans")
    quotas = relationship("PlanQuota", back_populates="plan")
    assignments = relationship("PlanAssignment", back_populates="plan")


class PlanQuota(Base):
    __tablename__ = "plan_quotas"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    resource_type = Column(String(50), nullable=False)
    limit = Column(Float, nullable=False)
    unit_price = Column(Float, default=0.0)
    over_limit_price = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    plan = relationship("Plan", back_populates="quotas")

    __table_args__ = (
        UniqueConstraint('plan_id', 'resource_type', name='_plan_resource_uc'),
    )


class PlanAssignment(Base):
    __tablename__ = "plan_assignments"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("Plan", back_populates="assignments")
    project = relationship("Project", back_populates="plan_assignments")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    key_hash = Column(String(255), unique=True, nullable=False)
    key_prefix = Column(String(10), nullable=False)
    name = Column(String(100), nullable=False)
    status = Column(Enum(APIKeyStatus), default=APIKeyStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="api_keys")
    usage_events = relationship("UsageEvent", back_populates="api_key")

    __table_args__ = (
        UniqueConstraint('project_id', 'key_prefix', name='_project_key_prefix_uc'),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    idempotency_key = Column(String(255), unique=True, nullable=False)
    resource_type = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    unit_price = Column(Float, default=0.0)
    request_time = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    is_processed = Column(Boolean, default=True)
    notes = Column(Text)

    project = relationship("Project", back_populates="usage_events")
    api_key = relationship("APIKey", back_populates="usage_events")

    __table_args__ = (
        UniqueConstraint('idempotency_key', name='_idempotency_key_uc'),
    )


class BillingCycle(Base):
    __tablename__ = "billing_cycles"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    period = Column(Enum(BillingPeriod), nullable=False)
    cycle_start = Column(DateTime(timezone=True), nullable=False)
    cycle_end = Column(DateTime(timezone=True), nullable=False)
    is_closed = Column(Boolean, default=False)
    total_amount = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant", back_populates="billing_cycles")
    usage_aggregations = relationship("UsageAggregation", back_populates="billing_cycle")

    __table_args__ = (
        UniqueConstraint('tenant_id', 'period', 'cycle_start', name='_tenant_cycle_uc'),
    )


class UsageAggregation(Base):
    __tablename__ = "usage_aggregations"

    id = Column(Integer, primary_key=True, index=True)
    billing_cycle_id = Column(Integer, ForeignKey("billing_cycles.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    resource_type = Column(String(50), nullable=False)
    total_usage = Column(Float, default=0.0)
    over_limit_usage = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    billing_cycle = relationship("BillingCycle", back_populates="usage_aggregations")
    project = relationship("Project", back_populates="usage_aggregations")

    __table_args__ = (
        UniqueConstraint('billing_cycle_id', 'project_id', 'resource_type', name='_cycle_project_resource_uc'),
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    threshold_type = Column(Enum(AlertThresholdType), default=AlertThresholdType.PERCENTAGE, nullable=False)
    threshold = Column(Float, nullable=False)
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.WARNING, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = relationship("Tenant", back_populates="alert_rules")


class AlertRecord(Base):
    __tablename__ = "alert_records"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    alert_rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    resource_type = Column(String(50), nullable=False)
    threshold = Column(Float, nullable=False)
    current_usage = Column(Float, nullable=False)
    percentage = Column(Float, nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False)
    message = Column(Text, nullable=False)
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledge_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = relationship("Tenant", back_populates="alert_records")
    alert_rule = relationship("AlertRule")
    project = relationship("Project")
    acknowledged_by_user = relationship("User", foreign_keys=[acknowledged_by])
