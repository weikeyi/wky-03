from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import (
    Tenant, Project, Plan, PlanQuota, PlanAssignment,
    BillingCycle, BillingPeriod, UsageAggregation
)
from app.schemas import BillPreviewResponse, UsageAggregationResponse, BillingCycleResponse
from app.services.billing_cycle_service import BillingCycleService


class BillingService:
    @staticmethod
    def get_bill_preview(
        db: Session,
        tenant_id: int,
        period: BillingPeriod = BillingPeriod.MONTHLY,
        project_id: Optional[int] = None
    ) -> BillPreviewResponse:
        now = datetime.utcnow()
        billing_cycle = BillingCycleService.get_current_cycle(db, tenant_id, period)

        active_plans = BillingService._get_active_plans_for_tenant(db, tenant_id, now)

        aggregations = []
        total_amount = 0.0

        for plan in active_plans:
            assignments = db.query(PlanAssignment).filter(
                and_(
                    PlanAssignment.plan_id == plan.id,
                    PlanAssignment.is_active == True,
                    PlanAssignment.effective_from <= now,
                    (PlanAssignment.effective_to == None) | (PlanAssignment.effective_to > now)
                )
            ).all()

            for assignment in assignments:
                if project_id and assignment.project_id != project_id:
                    continue

                proj_plan_cycle = BillingCycleService.get_cycle_for_date(
                    db, tenant_id, plan.billing_period, now
                )

                for quota in plan.quotas:
                    agg = db.query(UsageAggregation).filter(
                        and_(
                            UsageAggregation.billing_cycle_id == proj_plan_cycle.id,
                            UsageAggregation.project_id == assignment.project_id,
                            UsageAggregation.resource_type == quota.resource_type
                        )
                    ).first()

                    total_usage = agg.total_usage if agg else 0.0
                    over_limit_usage = agg.over_limit_usage if agg else 0.0
                    total_cost = agg.total_cost if agg else 0.0
                    percentage = (total_usage / quota.limit) * 100 if quota.limit > 0 else 0

                    agg_response = UsageAggregationResponse(
                        id=agg.id if agg else 0,
                        billing_cycle_id=proj_plan_cycle.id,
                        project_id=assignment.project_id,
                        resource_type=quota.resource_type,
                        total_usage=total_usage,
                        over_limit_usage=over_limit_usage,
                        total_cost=total_cost,
                        limit=quota.limit,
                        percentage=percentage,
                        unit_price=quota.unit_price,
                        over_limit_price=quota.over_limit_price,
                        updated_at=agg.updated_at if agg else None
                    )
                    aggregations.append(agg_response)
                    total_amount += total_cost

        summary = BillingService._generate_summary(tenant_id, billing_cycle, aggregations, project_id)

        return BillPreviewResponse(
            billing_cycle=BillingCycleResponse.model_validate(billing_cycle),
            total_amount=round(total_amount, 4),
            aggregations=aggregations,
            summary=summary
        )

    @staticmethod
    def _get_active_plans_for_tenant(
        db: Session,
        tenant_id: int,
        reference_date: datetime
    ) -> List[Plan]:
        return db.query(Plan).filter(
            and_(
                Plan.tenant_id == tenant_id,
                Plan.is_active == True
            )
        ).all()

    @staticmethod
    def _generate_summary(
        tenant_id: int,
        billing_cycle: BillingCycle,
        aggregations: List[UsageAggregationResponse],
        project_id: Optional[int]
    ) -> Dict[str, Any]:
        by_project: Dict[int, Dict[str, Any]] = {}
        by_resource: Dict[str, Dict[str, Any]] = {}
        total_usage_by_resource: Dict[str, float] = {}
        total_cost_by_resource: Dict[str, float] = {}

        total_usage = 0.0
        total_over_limit = 0.0

        for agg in aggregations:
            if agg.project_id not in by_project:
                by_project[agg.project_id] = {
                    "total_usage": 0.0,
                    "total_cost": 0.0,
                    "resources": {}
                }

            by_project[agg.project_id]["total_usage"] += agg.total_usage
            by_project[agg.project_id]["total_cost"] += agg.total_cost

            if agg.resource_type not in by_project[agg.project_id]["resources"]:
                by_project[agg.project_id]["resources"][agg.resource_type] = {
                    "usage": 0.0,
                    "cost": 0.0,
                    "limit": agg.limit,
                    "percentage": 0.0
                }

            by_project[agg.project_id]["resources"][agg.resource_type]["usage"] += agg.total_usage
            by_project[agg.project_id]["resources"][agg.resource_type]["cost"] += agg.total_cost

            if agg.resource_type not in by_resource:
                by_resource[agg.resource_type] = {
                    "total_usage": 0.0,
                    "total_cost": 0.0,
                    "projects": 0,
                    "over_limit_projects": 0
                }

            by_resource[agg.resource_type]["total_usage"] += agg.total_usage
            by_resource[agg.resource_type]["total_cost"] += agg.total_cost
            by_resource[agg.resource_type]["projects"] += 1

            if agg.percentage >= 100:
                by_resource[agg.resource_type]["over_limit_projects"] += 1

            total_usage_by_resource[agg.resource_type] = total_usage_by_resource.get(agg.resource_type, 0) + agg.total_usage
            total_cost_by_resource[agg.resource_type] = total_cost_by_resource.get(agg.resource_type, 0) + agg.total_cost

            total_usage += agg.total_usage
            total_over_limit += agg.over_limit_usage

        cycle_duration = billing_cycle.cycle_end - billing_cycle.cycle_start
        days_passed = (datetime.utcnow() - billing_cycle.cycle_start).total_seconds() / 86400
        days_total = cycle_duration.total_seconds() / 86400
        progress_percentage = min(100, (days_passed / days_total) * 100)

        projected_amount = 0.0
        if progress_percentage > 0:
            projected_amount = sum(a.total_cost for a in aggregations) * (100 / progress_percentage)

        over_limit_resources = [
            r for r in by_resource.values()
            if r["over_limit_projects"] > 0
        ]

        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "cycle_progress_percentage": round(progress_percentage, 2),
            "days_passed": round(days_passed, 2),
            "days_total": round(days_total, 2),
            "total_projects": len(by_project),
            "total_resources": len(by_resource),
            "total_usage": round(total_usage, 4),
            "total_over_limit_usage": round(total_over_limit, 4),
            "projected_total_amount": round(projected_amount, 4),
            "over_limit_resources_count": len(over_limit_resources),
            "by_project": by_project,
            "by_resource": by_resource
        }

    @staticmethod
    def get_billing_history(
        db: Session,
        tenant_id: int,
        period: Optional[BillingPeriod] = None,
        limit: int = 12
    ) -> List[Dict[str, Any]]:
        cycles = BillingCycleService.get_cycles(
            db, tenant_id, period, include_closed=True, limit=limit
        )

        history = []
        for cycle in cycles:
            aggregations = db.query(UsageAggregation).filter(
                UsageAggregation.billing_cycle_id == cycle.id
            ).all()

            total_amount = sum(agg.total_cost for agg in aggregations)
            total_usage = sum(agg.total_usage for agg in aggregations)

            resource_breakdown = {}
            for agg in aggregations:
                if agg.resource_type not in resource_breakdown:
                    resource_breakdown[agg.resource_type] = {"usage": 0.0, "cost": 0.0}
                resource_breakdown[agg.resource_type]["usage"] += agg.total_usage
                resource_breakdown[agg.resource_type]["cost"] += agg.total_cost

            history.append({
                "cycle_id": cycle.id,
                "period": cycle.period,
                "cycle_start": cycle.cycle_start,
                "cycle_end": cycle.cycle_end,
                "is_closed": cycle.is_closed,
                "total_amount": round(total_amount, 4),
                "total_usage": round(total_usage, 4),
                "resource_breakdown": resource_breakdown
            })

        return history
