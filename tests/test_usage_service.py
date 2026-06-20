import pytest
from datetime import datetime, timedelta
import uuid
from sqlalchemy.orm import Session

from app.services.usage_service import UsageService
from app.services.billing_cycle_service import BillingCycleService
from app.models import (
    UsageEvent, UsageAggregation, AlertRecord,
    APIKeyStatus, BillingPeriod, OverLimitAction,
    PlanAssignment
)
from app.schemas import UsageEventCreate
from tests.conftest import get_auth_token


class TestIdempotency:
    def test_duplicate_event_returns_original(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]
        idempotency_key = str(uuid.uuid4())

        event1 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idempotency_key,
            resource_type="api_calls",
            amount=10,
            request_time=datetime.utcnow()
        )

        result1, status1 = UsageService.process_usage_event(db_session, event1)
        assert status1 == "success"
        assert result1 is not None
        event_id = result1.id

        result2, status2 = UsageService.process_usage_event(db_session, event1)
        assert status2 == "duplicate"
        assert result2 is not None
        assert result2.id == event_id

        events = db_session.query(UsageEvent).filter(
            UsageEvent.idempotency_key == idempotency_key
        ).all()
        assert len(events) == 1

    def test_different_idempotency_keys_create_multiple_events(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        for i in range(3):
            event = UsageEventCreate(
                api_key=api_key,
                tenant_id=tenant.id,
                project_id=project.id,
                idempotency_key=str(uuid.uuid4()),
                resource_type="api_calls",
                amount=10,
                request_time=datetime.utcnow()
            )
            result, status = UsageService.process_usage_event(db_session, event)
            assert status == "success"

        events = db_session.query(UsageEvent).filter(
            UsageEvent.project_id == project.id
        ).all()
        assert len(events) == 3


class TestAPIKeyValidation:
    def test_active_api_key_accepted(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=10,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "success"
        assert result is not None

    def test_disabled_api_key_rejected(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_disabled"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=10,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "invalid_api_key"
        assert result is None

    def test_wrong_tenant_api_key_rejected(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=99999,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=10,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "invalid_api_key"
        assert result is None

    def test_wrong_project_api_key_rejected(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=99999,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=10,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "invalid_api_key"
        assert result is None


class TestQuotaEnforcement:
    def test_within_quota_allowed(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "success"
        assert result is not None

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()
        assert aggregation is not None
        assert aggregation.total_usage == 100
        assert aggregation.total_cost == 1.0

    def test_over_quota_charge_mode_allowed(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=1200,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "success"
        assert result is not None

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()
        assert aggregation.total_usage == 1200
        assert aggregation.over_limit_usage == 200
        assert aggregation.total_cost == 10 + 4

    def test_over_quota_reject_mode_rejected(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_project2"]
        tenant = test_data["tenant"]
        project = test_data["project2"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=600,
            request_time=datetime.utcnow()
        )

        result, status = UsageService.process_usage_event(db_session, event)
        assert status == "quota_exceeded"
        assert result is None

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()
        assert aggregation is None

    def test_multiple_events_accumulate_usage(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        for i in range(5):
            event = UsageEventCreate(
                api_key=api_key,
                tenant_id=tenant.id,
                project_id=project.id,
                idempotency_key=str(uuid.uuid4()),
                resource_type="api_calls",
                amount=100,
                request_time=datetime.utcnow()
            )
            UsageService.process_usage_event(db_session, event)

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()
        assert aggregation.total_usage == 500
        assert aggregation.total_cost == 5.0


class TestBillingCycles:
    def test_different_dates_different_cycles(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]
        plan = test_data["plan_charge"]

        event1 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=100,
            request_time=datetime(2024, 1, 15, 10, 0, 0)
        )
        UsageService.process_usage_event(db_session, event1)

        event2 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=200,
            request_time=datetime(2024, 2, 15, 10, 0, 0)
        )
        UsageService.process_usage_event(db_session, event2)

        cycles = BillingCycleService.get_cycles(
            db_session, tenant.id, BillingPeriod.MONTHLY, include_closed=True
        )
        assert len(cycles) >= 2

        agg_jan = db_session.query(UsageAggregation).join(
            UsageAggregation.billing_cycle
        ).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls",
            BillingPeriod.MONTHLY == BillingPeriod.MONTHLY,
            UsageAggregation.billing_cycle.has(cycle_start=datetime(2024, 1, 1))
        ).first()

        agg_feb = db_session.query(UsageAggregation).join(
            UsageAggregation.billing_cycle
        ).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls",
            UsageAggregation.billing_cycle.has(cycle_start=datetime(2024, 2, 1))
        ).first()

        assert agg_jan.total_usage == 100
        assert agg_feb.total_usage == 200


class TestAlerts:
    def test_80_percent_threshold_triggers_warning(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=850,
            request_time=datetime.utcnow()
        )
        UsageService.process_usage_event(db_session, event)

        alerts = db_session.query(AlertRecord).filter(
            AlertRecord.tenant_id == tenant.id,
            AlertRecord.project_id == project.id,
            AlertRecord.resource_type == "api_calls",
            AlertRecord.threshold == 80
        ).all()
        assert len(alerts) >= 1

    def test_100_percent_threshold_triggers_critical(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=1050,
            request_time=datetime.utcnow()
        )
        UsageService.process_usage_event(db_session, event)

        alerts = db_session.query(AlertRecord).filter(
            AlertRecord.tenant_id == tenant.id,
            AlertRecord.project_id == project.id,
            AlertRecord.resource_type == "api_calls",
            AlertRecord.threshold == 100
        ).all()
        assert len(alerts) >= 1

    def test_120_percent_threshold_triggers_critical(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=1300,
            request_time=datetime.utcnow()
        )
        UsageService.process_usage_event(db_session, event)

        alerts = db_session.query(AlertRecord).filter(
            AlertRecord.tenant_id == tenant.id,
            AlertRecord.project_id == project.id,
            AlertRecord.resource_type == "api_calls",
            AlertRecord.threshold == 120
        ).all()
        assert len(alerts) >= 1


class TestPlanUpgrade:
    def test_mid_cycle_plan_upgrade(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]
        plan_charge = test_data["plan_charge"]
        plan_daily = test_data["plan_daily"]

        event1 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow() - timedelta(days=5)
        )
        result1, _ = UsageService.process_usage_event(db_session, event1)

        db_session.query(PlanAssignment).filter(
            PlanAssignment.project_id == project.id,
            PlanAssignment.is_active == True
        ).update({"is_active": False, "effective_to": datetime.utcnow()})

        new_assignment = PlanAssignment(
            plan_id=plan_daily.id,
            project_id=project.id,
            effective_from=datetime.utcnow(),
            is_active=True
        )
        db_session.add(new_assignment)
        db_session.commit()

        event2 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=50,
            request_time=datetime.utcnow()
        )
        result2, _ = UsageService.process_usage_event(db_session, event2)

        assert result1 is not None
        assert result2 is not None

        monthly_agg = db_session.query(UsageAggregation).join(
            UsageAggregation.billing_cycle
        ).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls",
            UsageAggregation.billing_cycle.has(period=BillingPeriod.MONTHLY)
        ).first()

        daily_agg = db_session.query(UsageAggregation).join(
            UsageAggregation.billing_cycle
        ).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls",
            UsageAggregation.billing_cycle.has(period=BillingPeriod.DAILY)
        ).first()

        assert monthly_agg is not None
        assert monthly_agg.total_usage == 100
        assert daily_agg is not None
        assert daily_agg.total_usage == 50


class TestOutOfOrderEvents:
    def test_out_of_order_events_handled_correctly(self, client, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        event1 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow() + timedelta(hours=2)
        )
        UsageService.process_usage_event(db_session, event1)

        event2 = UsageEventCreate(
            api_key=api_key,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=str(uuid.uuid4()),
            resource_type="api_calls",
            amount=50,
            request_time=datetime.utcnow()
        )
        UsageService.process_usage_event(db_session, event2)

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()
        assert aggregation.total_usage == 150
        assert aggregation.total_cost == 1.5


class TestQuotaCheckAPI:
    def test_quota_check_within_limit(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]
        project = test_data["project"]

        response = client.get(
            "/api/v1/usage/check-quota",
            params={
                "tenant_id": tenant.id,
                "project_id": project.id,
                "resource_type": "api_calls",
                "amount": 100
            },
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] == True
        assert data["limit"] == 1000
        assert data["percentage"] == 10

    def test_quota_check_over_limit_reject(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]
        project2 = test_data["project2"]

        response = client.get(
            "/api/v1/usage/check-quota",
            params={
                "tenant_id": tenant.id,
                "project_id": project2.id,
                "resource_type": "api_calls",
                "amount": 600
            },
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] == False
        assert data["limit"] == 500
