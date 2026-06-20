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


class TestUsageEventExport:
    def _create_usage_events(self, db_session, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]
        project2 = test_data["project2"]
        api_key3, _ = test_data["api_key_project2"]

        events_data = [
            (api_key, project.id, "api_calls", 100, datetime(2024, 6, 1, 10, 0, 0)),
            (api_key, project.id, "api_calls", 200, datetime(2024, 6, 2, 10, 0, 0)),
            (api_key, project.id, "storage_gb", 5, datetime(2024, 6, 3, 10, 0, 0)),
            (api_key3, project2.id, "api_calls", 150, datetime(2024, 6, 4, 10, 0, 0)),
        ]

        for i, (key, proj_id, res_type, amount, req_time) in enumerate(events_data):
            event = UsageEventCreate(
                api_key=key,
                tenant_id=tenant.id,
                project_id=proj_id,
                idempotency_key=f"export_test_{uuid.uuid4()}_{i}",
                resource_type=res_type,
                amount=amount,
                request_time=req_time
            )
            UsageService.process_usage_event(db_session, event)

    def test_normal_export_csv(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/csv")
        assert "attachment; filename=usage_events_tenant_" in response.headers["Content-Disposition"]
        assert "X-Total-Count" in response.headers

        content = response.text
        lines = content.strip().split("\n")
        assert len(lines) == 5
        header = lines[0]
        assert "event_id" in header
        assert "project_id" in header
        assert "api_key_prefix" in header
        assert "resource_type" in header
        assert "amount" in header
        assert "request_time" in header
        assert "unit_price" in header
        assert "idempotency_key" in header

    def test_cross_tenant_export_denied(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")
        tenant2 = test_data["tenant2"]

        response = client.get(
            f"/api/v1/usage/export?tenant_id={tenant2.id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 403

    def test_admin_can_export_any_tenant(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        response = client.get(
            f"/api/v1/usage/export?tenant_id={tenant.id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 5

    def test_filter_by_project(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")
        project = test_data["project"]

        response = client.get(
            f"/api/v1/usage/export?project_id={project.id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 4

    def test_filter_by_resource_type(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export?resource_type=storage_gb",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 2

    def test_filter_by_time_range(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export?start_time=2024-06-02T00:00:00&end_time=2024-06-03T23:59:59",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 3

    def test_empty_result_export(self, db_session, client, test_data):
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "0"
        content = response.text
        lines = content.strip().split("\n")
        assert len(lines) == 1
        assert "event_id" in lines[0]

    def test_export_limit_capped_at_max(self, db_session, client, test_data):
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export?limit=100000",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200

    def test_export_negative_limit_rejected(self, db_session, client, test_data):
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export?limit=-1",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 400

    def test_export_zero_limit_rejected(self, db_session, client, test_data):
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export?limit=0",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 400

    def test_export_limit_applied(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.get(
            "/api/v1/usage/export?limit=2",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert int(response.headers["X-Total-Count"]) == 2
        lines = response.text.strip().split("\n")
        assert len(lines) == 3

    def test_combined_filters(self, db_session, client, test_data):
        self._create_usage_events(db_session, test_data)
        token = get_auth_token(client, "tenant_admin", "test123")
        project = test_data["project"]

        response = client.get(
            f"/api/v1/usage/export?project_id={project.id}&resource_type=api_calls&start_time=2024-06-01T00:00:00&end_time=2024-06-02T23:59:59",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 3


def get_auth_token(client, username, password):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password}
    )
    return response.json()["access_token"]
