from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import BillingCycle, Tenant, BillingPeriod
from app import models


class BillingCycleService:
    @staticmethod
    def _calculate_cycle_boundaries(
        period: BillingPeriod,
        reference_date: datetime
    ) -> Tuple[datetime, datetime]:
        if period == BillingPeriod.DAILY:
            cycle_start = reference_date.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            cycle_end = cycle_start + timedelta(days=1)
        elif period == BillingPeriod.MONTHLY:
            cycle_start = reference_date.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if cycle_start.month == 12:
                cycle_end = cycle_start.replace(year=cycle_start.year + 1, month=1)
            else:
                cycle_end = cycle_start.replace(month=cycle_start.month + 1)
        else:
            raise ValueError(f"Unknown billing period: {period}")
        return cycle_start, cycle_end

    @staticmethod
    def get_or_create_cycle(
        db: Session,
        tenant_id: int,
        period: BillingPeriod,
        reference_date: datetime
    ) -> BillingCycle:
        cycle_start, cycle_end = BillingCycleService._calculate_cycle_boundaries(
            period, reference_date
        )

        cycle = db.query(BillingCycle).filter(
            and_(
                BillingCycle.tenant_id == tenant_id,
                BillingCycle.period == period,
                BillingCycle.cycle_start == cycle_start
            )
        ).first()

        if not cycle:
            cycle = BillingCycle(
                tenant_id=tenant_id,
                period=period,
                cycle_start=cycle_start,
                cycle_end=cycle_end,
                is_closed=False,
                total_amount=0.0
            )
            db.add(cycle)
            db.flush()

        return cycle

    @staticmethod
    def get_current_cycle(
        db: Session,
        tenant_id: int,
        period: BillingPeriod
    ) -> Optional[BillingCycle]:
        now = datetime.utcnow()
        return BillingCycleService.get_or_create_cycle(db, tenant_id, period, now)

    @staticmethod
    def get_cycle_for_date(
        db: Session,
        tenant_id: int,
        period: BillingPeriod,
        date: datetime
    ) -> BillingCycle:
        return BillingCycleService.get_or_create_cycle(db, tenant_id, period, date)

    @staticmethod
    def get_cycle_by_id(db: Session, cycle_id: int) -> Optional[BillingCycle]:
        return db.query(BillingCycle).filter(BillingCycle.id == cycle_id).first()

    @staticmethod
    def close_cycle(db: Session, cycle_id: int) -> Optional[BillingCycle]:
        cycle = db.query(BillingCycle).filter(
            BillingCycle.id == cycle_id,
            BillingCycle.is_closed == False
        ).first()

        if cycle:
            cycle.is_closed = True
            cycle.closed_at = datetime.utcnow()
            db.flush()

        return cycle

    @staticmethod
    def get_cycles(
        db: Session,
        tenant_id: int,
        period: Optional[BillingPeriod] = None,
        include_closed: bool = False,
        limit: int = 100
    ):
        query = db.query(BillingCycle).filter(BillingCycle.tenant_id == tenant_id)

        if period:
            query = query.filter(BillingCycle.period == period)

        if not include_closed:
            query = query.filter(BillingCycle.is_closed == False)

        return query.order_by(BillingCycle.cycle_start.desc()).limit(limit).all()
