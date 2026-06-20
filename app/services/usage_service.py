from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
import secrets

from app.models import (
    APIKey, APIKeyStatus, UsageEvent, UsageAggregation,
    Plan, PlanQuota, PlanAssignment, Tenant, Project,
    BillingCycle, BillingPeriod, OverLimitAction,
    AlertRecord, AlertSeverity, AlertRule
)
from app.schemas import UsageEventCreate, QuotaCheckResponse
from app.security import verify_api_key
from app.services.billing_cycle_service import BillingCycleService


class UsageService:
    @staticmethod
    def _validate_api_key(
        db: Session,
        api_key_str: str,
        tenant_id: int,
        project_id: int
    ) -> Optional[APIKey]:
        api_key = db.query(APIKey).filter(
            and_(
                APIKey.project_id == project_id,
                Project.tenant_id == tenant_id
            )
        ).join(Project).first()

        if not api_key:
            return None

        api_keys = db.query(APIKey).filter(
            APIKey.project_id == project_id
        ).all()

        for key in api_keys:
            if verify_api_key(api_key_str, key.key_hash):
                if key.status == APIKeyStatus.DISABLED or key.status == APIKeyStatus.REVOKED:
                    return None
                return key

        return None

    @staticmethod
    def _get_active_plan_for_project(
        db: Session,
        project_id: int,
        reference_date: datetime
    ) -> Optional[Plan]:
        assignment = db.query(PlanAssignment).filter(
            and_(
                PlanAssignment.project_id == project_id,
                PlanAssignment.is_active == True,
                PlanAssignment.effective_from <= reference_date,
                (PlanAssignment.effective_to == None) | (PlanAssignment.effective_to > reference_date)
            )
        ).order_by(PlanAssignment.effective_from.desc()).first()

        if not assignment:
            return None

        return db.query(Plan).filter(
            Plan.id == assignment.plan_id,
            Plan.is_active == True
        ).first()

    @staticmethod
    def _get_quota_for_resource(
        plan: Plan,
        resource_type: str
    ) -> Optional[PlanQuota]:
        for quota in plan.quotas:
            if quota.resource_type == resource_type:
                return quota
        return None

    @staticmethod
    def _get_or_create_aggregation(
        db: Session,
        billing_cycle_id: int,
        project_id: int,
        resource_type: str
    ) -> UsageAggregation:
        aggregation = db.query(UsageAggregation).filter(
            and_(
                UsageAggregation.billing_cycle_id == billing_cycle_id,
                UsageAggregation.project_id == project_id,
                UsageAggregation.resource_type == resource_type
            )
        ).with_for_update().first()

        if not aggregation:
            try:
                aggregation = UsageAggregation(
                    billing_cycle_id=billing_cycle_id,
                    project_id=project_id,
                    resource_type=resource_type,
                    total_usage=0.0,
                    over_limit_usage=0.0,
                    total_cost=0.0
                )
                db.add(aggregation)
                db.flush()
                db.refresh(aggregation)
            except IntegrityError:
                db.rollback()
                aggregation = db.query(UsageAggregation).filter(
                    and_(
                        UsageAggregation.billing_cycle_id == billing_cycle_id,
                        UsageAggregation.project_id == project_id,
                        UsageAggregation.resource_type == resource_type
                    )
                ).with_for_update().first()

        return aggregation

    @staticmethod
    def _check_duplicate_event(
        db: Session,
        idempotency_key: str
    ) -> bool:
        return db.query(UsageEvent).filter(
            UsageEvent.idempotency_key == idempotency_key
        ).first() is not None

    @staticmethod
    def check_quota(
        db: Session,
        tenant_id: int,
        project_id: int,
        resource_type: str,
        requested_amount: float,
        reference_date: Optional[datetime] = None
    ) -> QuotaCheckResponse:
        now = reference_date or datetime.utcnow()

        plan = UsageService._get_active_plan_for_project(db, project_id, now)

        if not plan:
            return QuotaCheckResponse(
                allowed=True,
                reason="No active plan assigned, unlimited usage",
                current_usage=0.0,
                limit=float('inf'),
                percentage=0.0,
                over_limit_action=OverLimitAction.CHARGE
            )

        quota = UsageService._get_quota_for_resource(plan, resource_type)

        if not quota:
            return QuotaCheckResponse(
                allowed=True,
                reason=f"No quota defined for resource type: {resource_type}",
                current_usage=0.0,
                limit=float('inf'),
                percentage=0.0,
                over_limit_action=plan.over_limit_action
            )

        billing_cycle = BillingCycleService.get_cycle_for_date(
            db, tenant_id, plan.billing_period, now
        )

        aggregation = db.query(UsageAggregation).filter(
            and_(
                UsageAggregation.billing_cycle_id == billing_cycle.id,
                UsageAggregation.project_id == project_id,
                UsageAggregation.resource_type == resource_type
            )
        ).first()

        current_usage = aggregation.total_usage if aggregation else 0.0
        new_total = current_usage + requested_amount
        percentage = (new_total / quota.limit) * 100 if quota.limit > 0 else float('inf')

        if new_total > quota.limit and plan.over_limit_action == OverLimitAction.REJECT:
            return QuotaCheckResponse(
                allowed=False,
                reason=f"Quota exceeded. Current: {current_usage}, Limit: {quota.limit}, Requested: {requested_amount}",
                current_usage=current_usage,
                limit=quota.limit,
                percentage=percentage,
                over_limit_action=plan.over_limit_action
            )

        return QuotaCheckResponse(
            allowed=True,
            reason=None,
            current_usage=current_usage,
            limit=quota.limit,
            percentage=percentage,
            over_limit_action=plan.over_limit_action
        )

    @staticmethod
    def _trigger_alerts(
        db: Session,
        tenant_id: int,
        project_id: int,
        resource_type: str,
        current_usage: float,
        quota: PlanQuota,
        plan: Plan
    ) -> List[AlertRecord]:
        alert_records = []
        thresholds = [80, 100, 120]
        severities = {
            80: AlertSeverity.WARNING,
            100: AlertSeverity.CRITICAL,
            120: AlertSeverity.CRITICAL
        }

        if quota.limit <= 0:
            return alert_records

        percentage = (current_usage / quota.limit) * 100

        for threshold in thresholds:
            if percentage >= threshold:
                existing_alert = db.query(AlertRecord).filter(
                    and_(
                        AlertRecord.tenant_id == tenant_id,
                        AlertRecord.project_id == project_id,
                        AlertRecord.resource_type == resource_type,
                        AlertRecord.threshold == threshold,
                        AlertRecord.is_acknowledged == False,
                        func.date(AlertRecord.created_at) == func.date(datetime.utcnow())
                    )
                ).first()

                if not existing_alert:
                    message = (
                        f"Resource '{resource_type}' usage has reached {percentage:.1f}% "
                        f"of quota ({current_usage:.2f}/{quota.limit:.2f}). "
                        f"Threshold: {threshold}%"
                    )

                    alert_record = AlertRecord(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        resource_type=resource_type,
                        threshold=threshold,
                        current_usage=current_usage,
                        percentage=percentage,
                        severity=severities[threshold],
                        message=message
                    )
                    db.add(alert_record)
                    alert_records.append(alert_record)

        custom_rules = db.query(AlertRule).filter(
            and_(
                AlertRule.tenant_id == tenant_id,
                AlertRule.is_active == True,
                (AlertRule.resource_type == None) | (AlertRule.resource_type == resource_type)
            )
        ).all()

        for rule in custom_rules:
            if rule.threshold_type == "percentage":
                rule_threshold = (rule.threshold / 100) * quota.limit
            else:
                rule_threshold = rule.threshold

            if current_usage >= rule_threshold:
                existing_alert = db.query(AlertRecord).filter(
                    and_(
                        AlertRecord.tenant_id == tenant_id,
                        AlertRecord.alert_rule_id == rule.id,
                        AlertRecord.project_id == project_id,
                        AlertRecord.is_acknowledged == False,
                        func.date(AlertRecord.created_at) == func.date(datetime.utcnow())
                    )
                ).first()

                if not existing_alert:
                    message = (
                        f"Alert '{rule.name}' triggered. Resource '{resource_type}' "
                        f"usage: {current_usage:.2f}, Threshold: {rule.threshold}"
                    )

                    alert_record = AlertRecord(
                        tenant_id=tenant_id,
                        alert_rule_id=rule.id,
                        project_id=project_id,
                        resource_type=resource_type,
                        threshold=rule.threshold,
                        current_usage=current_usage,
                        percentage=percentage,
                        severity=rule.severity,
                        message=message
                    )
                    db.add(alert_record)
                    alert_records.append(alert_record)

        return alert_records

    @staticmethod
    def process_usage_event(
        db: Session,
        event_data: UsageEventCreate
    ) -> Tuple[Optional[UsageEvent], str]:
        api_key = UsageService._validate_api_key(
            db, event_data.api_key, event_data.tenant_id, event_data.project_id
        )

        if not api_key:
            return None, "invalid_api_key"

        project = db.query(Project).filter(
            Project.id == event_data.project_id,
            Project.tenant_id == event_data.tenant_id,
            Project.is_active == True
        ).first()

        if not project:
            return None, "invalid_project"

        tenant = db.query(Tenant).filter(
            Tenant.id == event_data.tenant_id
        ).first()

        if not tenant:
            return None, "invalid_tenant"

        if UsageService._check_duplicate_event(db, event_data.idempotency_key):
            existing = db.query(UsageEvent).filter(
                UsageEvent.idempotency_key == event_data.idempotency_key
            ).first()
            if (existing and
                existing.tenant_id == event_data.tenant_id and
                existing.project_id == event_data.project_id and
                existing.api_key_id == api_key.id and
                api_key.status == APIKeyStatus.ACTIVE):
                return existing, "duplicate"
            else:
                return None, "invalid_api_key"

        plan = UsageService._get_active_plan_for_project(
            db, event_data.project_id, event_data.request_time
        )

        unit_price = 0.0
        if plan:
            quota = UsageService._get_quota_for_resource(plan, event_data.resource_type)
            if quota:
                unit_price = quota.unit_price

        quota_check = UsageService.check_quota(
            db, event_data.tenant_id, event_data.project_id,
            event_data.resource_type, event_data.amount,
            event_data.request_time
        )

        if not quota_check.allowed:
            return None, "quota_exceeded"

        try:
            usage_event = UsageEvent(
                tenant_id=event_data.tenant_id,
                project_id=event_data.project_id,
                api_key_id=api_key.id,
                idempotency_key=event_data.idempotency_key,
                resource_type=event_data.resource_type,
                amount=event_data.amount,
                unit_price=unit_price,
                request_time=event_data.request_time,
                is_processed=True
            )
            db.add(usage_event)
            db.flush()

            api_key.last_used_at = datetime.utcnow()

            if plan:
                billing_cycle = BillingCycleService.get_cycle_for_date(
                    db, event_data.tenant_id, plan.billing_period, event_data.request_time
                )

                aggregation = UsageService._get_or_create_aggregation(
                    db, billing_cycle.id, event_data.project_id, event_data.resource_type
                )

                quota = UsageService._get_quota_for_resource(plan, event_data.resource_type)

                if quota:
                    old_total = aggregation.total_usage
                    new_total = old_total + event_data.amount
                    aggregation.total_usage = new_total

                    if new_total > quota.limit:
                        over_limit = new_total - quota.limit
                        previous_over_limit = max(0, old_total - quota.limit)
                        new_over_limit_amount = over_limit - previous_over_limit

                        within_limit_amount = max(0, event_data.amount - new_over_limit_amount)

                        cost = (within_limit_amount * quota.unit_price) + \
                               (new_over_limit_amount * quota.over_limit_price)

                        aggregation.over_limit_usage = over_limit
                    else:
                        cost = event_data.amount * quota.unit_price
                        aggregation.over_limit_usage = 0

                    aggregation.total_cost += cost
                    billing_cycle.total_amount += cost

                    UsageService._trigger_alerts(
                        db, event_data.tenant_id, event_data.project_id,
                        event_data.resource_type, aggregation.total_usage,
                        quota, plan
                    )
                else:
                    aggregation.total_usage += event_data.amount
                    aggregation.total_cost += event_data.amount * unit_price

            db.commit()
            db.refresh(usage_event)

            return usage_event, "success"

        except IntegrityError as e:
            db.rollback()
            if "idempotency_key" in str(e):
                existing = db.query(UsageEvent).filter(
                    UsageEvent.idempotency_key == event_data.idempotency_key
                ).first()
                if (existing and
                    existing.tenant_id == event_data.tenant_id and
                    existing.project_id == event_data.project_id and
                    existing.api_key_id == api_key.id and
                    api_key.status == APIKeyStatus.ACTIVE):
                    return existing, "duplicate"
                else:
                    return None, "invalid_api_key"
            raise

    @staticmethod
    def get_current_usage(
        db: Session,
        tenant_id: int,
        project_id: Optional[int] = None,
        resource_type: Optional[str] = None
    ) -> List[Dict]:
        now = datetime.utcnow()
        results = []

        plan_assignments = db.query(PlanAssignment).filter(
            PlanAssignment.is_active == True,
            PlanAssignment.effective_from <= now,
            (PlanAssignment.effective_to == None) | (PlanAssignment.effective_to > now)
        )

        if project_id:
            plan_assignments = plan_assignments.filter(PlanAssignment.project_id == project_id)

        plan_assignments = plan_assignments.all()

        for assignment in plan_assignments:
            plan = assignment.plan
            project = assignment.project

            if plan.tenant_id != tenant_id:
                continue

            billing_cycle = BillingCycleService.get_current_cycle(
                db, tenant_id, plan.billing_period
            )

            for quota in plan.quotas:
                if resource_type and quota.resource_type != resource_type:
                    continue

                aggregation = db.query(UsageAggregation).filter(
                    and_(
                        UsageAggregation.billing_cycle_id == billing_cycle.id,
                        UsageAggregation.project_id == project.id,
                        UsageAggregation.resource_type == quota.resource_type
                    )
                ).first()

                total_usage = aggregation.total_usage if aggregation else 0.0
                over_limit_usage = aggregation.over_limit_usage if aggregation else 0.0
                total_cost = aggregation.total_cost if aggregation else 0.0
                percentage = (total_usage / quota.limit) * 100 if quota.limit > 0 else 0

                results.append({
                    "project_id": project.id,
                    "project_name": project.name,
                    "plan_id": plan.id,
                    "plan_name": plan.name,
                    "billing_period": plan.billing_period,
                    "resource_type": quota.resource_type,
                    "limit": quota.limit,
                    "total_usage": total_usage,
                    "over_limit_usage": over_limit_usage,
                    "percentage": percentage,
                    "total_cost": total_cost,
                    "unit_price": quota.unit_price,
                    "over_limit_price": quota.over_limit_price,
                    "cycle_start": billing_cycle.cycle_start,
                    "cycle_end": billing_cycle.cycle_end
                })

        return results

    @staticmethod
    def get_event_history(
        db: Session,
        tenant_id: int,
        project_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[UsageEvent], int]:
        query = db.query(UsageEvent).filter(UsageEvent.tenant_id == tenant_id)

        if project_id:
            query = query.filter(UsageEvent.project_id == project_id)

        if resource_type:
            query = query.filter(UsageEvent.resource_type == resource_type)

        if start_time:
            query = query.filter(UsageEvent.request_time >= start_time)

        if end_time:
            query = query.filter(UsageEvent.request_time <= end_time)

        total = query.count()
        events = query.order_by(UsageEvent.request_time.desc())\
            .offset(offset).limit(limit).all()

        return events, total

    @staticmethod
    def export_events(
        db: Session,
        tenant_id: int,
        project_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10000
    ) -> List[Dict[str, Any]]:
        query = db.query(
            UsageEvent.id,
            UsageEvent.project_id,
            APIKey.key_prefix,
            UsageEvent.resource_type,
            UsageEvent.amount,
            UsageEvent.request_time,
            UsageEvent.unit_price,
            UsageEvent.idempotency_key
        ).join(
            APIKey, UsageEvent.api_key_id == APIKey.id
        ).filter(
            UsageEvent.tenant_id == tenant_id
        )

        if project_id:
            query = query.filter(UsageEvent.project_id == project_id)

        if resource_type:
            query = query.filter(UsageEvent.resource_type == resource_type)

        if start_time:
            query = query.filter(UsageEvent.request_time >= start_time)

        if end_time:
            query = query.filter(UsageEvent.request_time <= end_time)

        events = query.order_by(UsageEvent.request_time.desc())\
            .limit(limit).all()

        return [
            {
                "event_id": event.id,
                "project_id": event.project_id,
                "api_key_prefix": event.key_prefix,
                "resource_type": event.resource_type,
                "amount": event.amount,
                "request_time": event.request_time,
                "unit_price": event.unit_price,
                "idempotency_key": event.idempotency_key
            }
            for event in events
        ]
