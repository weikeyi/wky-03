import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.models import UsageAggregation, BillingCycle, APIKeyStatus
from app.schemas import UsageEventCreate
from app.services.usage_service import UsageService


class TestCrossTenantIdempotency:
    def test_cross_tenant_replay_with_same_idempotency_key_rejected(
        self, db_session, test_data
    ):
        api_key1, _ = test_data["api_key_active"]
        tenant1 = test_data["tenant"]
        project1 = test_data["project"]
        api_key2, _ = test_data["api_key_t2"]
        tenant2 = test_data["tenant2"]
        project_t2 = test_data["project_t2"]

        idem_key = str(uuid.uuid4())

        event1 = UsageEventCreate(
            api_key=api_key1,
            tenant_id=tenant1.id,
            project_id=project1.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result1, status1 = UsageService.process_usage_event(db_session, event1)
        assert status1 == "success"
        assert result1 is not None

        event2 = UsageEventCreate(
            api_key=api_key2,
            tenant_id=tenant2.id,
            project_id=project_t2.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result2, status2 = UsageService.process_usage_event(db_session, event2)
        assert status2 == "invalid_api_key"
        assert result2 is None

    def test_same_tenant_different_project_replay_rejected(
        self, db_session, test_data
    ):
        api_key1, _ = test_data["api_key_active"]
        api_key3, _ = test_data["api_key_project2"]
        tenant = test_data["tenant"]
        project1 = test_data["project"]
        project2 = test_data["project2"]

        idem_key = str(uuid.uuid4())

        event1 = UsageEventCreate(
            api_key=api_key1,
            tenant_id=tenant.id,
            project_id=project1.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result1, status1 = UsageService.process_usage_event(db_session, event1)
        assert status1 == "success"

        event2 = UsageEventCreate(
            api_key=api_key3,
            tenant_id=tenant.id,
            project_id=project2.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result2, status2 = UsageService.process_usage_event(db_session, event2)
        assert status2 == "invalid_api_key"
        assert result2 is None


class TestDisabledKeyIdempotency:
    def test_disabled_api_key_cannot_replay_success_event(
        self, db_session, test_data
    ):
        api_key_active, _ = test_data["api_key_active"]
        api_key_disabled, api_key_disabled_obj = test_data["api_key_disabled"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        idem_key = str(uuid.uuid4())

        event1 = UsageEventCreate(
            api_key=api_key_active,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result1, status1 = UsageService.process_usage_event(db_session, event1)
        assert status1 == "success"

        event2 = UsageEventCreate(
            api_key=api_key_disabled,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result2, status2 = UsageService.process_usage_event(db_session, event2)
        assert status2 == "invalid_api_key"
        assert result2 is None

    def test_wrong_api_key_cannot_replay_success_event(
        self, db_session, test_data
    ):
        api_key_active, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        idem_key = str(uuid.uuid4())

        event1 = UsageEventCreate(
            api_key=api_key_active,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result1, status1 = UsageService.process_usage_event(db_session, event1)
        assert status1 == "success"

        event2 = UsageEventCreate(
            api_key="sk_wrong_key_12345678901234567890123456789012",
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=100,
            request_time=datetime.utcnow()
        )
        result2, status2 = UsageService.process_usage_event(db_session, event2)
        assert status2 == "invalid_api_key"
        assert result2 is None


class TestConcurrentQuota:
    def test_concurrent_usage_aggregation_correct(
        self, db_session, test_data
    ):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        num_workers = 10
        amount_per_request = 10
        num_requests = 50

        results = []
        for i in range(num_requests):
            event = UsageEventCreate(
                api_key=api_key,
                tenant_id=tenant.id,
                project_id=project.id,
                idempotency_key=f"concurrent_test_{uuid.uuid4()}_{i}",
                resource_type="api_calls",
                amount=amount_per_request,
                request_time=datetime.utcnow()
            )
            result, status = UsageService.process_usage_event(db_session, event)
            results.append((result, status))

        success_count = sum(1 for _, s in results if s == "success")
        assert success_count == num_requests

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()

        assert aggregation.total_usage == num_requests * amount_per_request
        expected_cost = (num_requests * amount_per_request) * 0.01
        assert abs(aggregation.total_cost - expected_cost) < 0.001

    def test_concurrent_over_quota_reject_mode(
        self, db_session, test_data
    ):
        api_key, _ = test_data["api_key_project2"]
        tenant = test_data["tenant"]
        project = test_data["project2"]

        results = []
        for i in range(20):
            event = UsageEventCreate(
                api_key=api_key,
                tenant_id=tenant.id,
                project_id=project.id,
                idempotency_key=f"reject_concurrent_{uuid.uuid4()}_{i}",
                resource_type="api_calls",
                amount=50,
                request_time=datetime.utcnow()
            )
            result, status = UsageService.process_usage_event(db_session, event)
            results.append(status)

        success_count = sum(1 for s in results if s == "success")
        reject_count = sum(1 for s in results if s == "quota_exceeded")

        assert success_count + reject_count == 20
        assert success_count <= 10
        assert reject_count >= 10

        aggregation = db_session.query(UsageAggregation).filter(
            UsageAggregation.project_id == project.id,
            UsageAggregation.resource_type == "api_calls"
        ).first()
        if aggregation:
            assert aggregation.total_usage <= 500


class TestIdempotencySecurity:
    def test_disabled_key_replay_via_integrity_error_path(
        self, db_session, test_data
    ):
        api_key_active, _ = test_data["api_key_active"]
        api_key_disabled, _ = test_data["api_key_disabled"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        idem_key = f"security_test_{uuid.uuid4()}"

        event1 = UsageEventCreate(
            api_key=api_key_active,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=5,
            request_time=datetime.utcnow()
        )
        result1, status1 = UsageService.process_usage_event(db_session, event1)
        assert status1 == "success"

        event2 = UsageEventCreate(
            api_key=api_key_disabled,
            tenant_id=tenant.id,
            project_id=project.id,
            idempotency_key=idem_key,
            resource_type="api_calls",
            amount=5,
            request_time=datetime.utcnow()
        )
        result2, status2 = UsageService.process_usage_event(db_session, event2)
        assert status2 == "invalid_api_key"
        assert result2 is None
