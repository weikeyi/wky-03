import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.models import UsageAggregation, BillingCycle, APIKeyStatus, AlertRecord, AlertSeverity
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


class TestAlertAcknowledgment:

    def _create_alert_records(self, db_session, tenant_id, project_id, count=3, ack=False):
        records = []
        for i in range(count):
            record = AlertRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                resource_type="api_calls",
                threshold=80.0,
                current_usage=85.0 + i * 5,
                percentage=85.0 + i * 5,
                severity=AlertSeverity.WARNING if i < 2 else AlertSeverity.CRITICAL,
                message=f"Test alert {i + 1}: usage exceeded threshold",
                is_acknowledged=ack,
                acknowledged_at=datetime.utcnow() if ack else None,
                acknowledged_by=None,
                acknowledge_note=None
            )
            db_session.add(record)
            records.append(record)
        db_session.commit()
        for r in records:
            db_session.refresh(r)
        return records

    def test_get_unhandled_alerts_list(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        token = get_auth_token(client, "tenant_admin", "test123")

        self._create_alert_records(db_session, tenant.id, project.id, count=3, ack=False)
        self._create_alert_records(db_session, tenant.id, project.id, count=2, ack=True)

        response = client.get(
            "/api/v1/alerts/records",
            params={"is_acknowledged": False},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        for record in data:
            assert record["is_acknowledged"] is False
            assert record["acknowledged_at"] is None
            assert record["acknowledged_by"] is None
            assert record["acknowledge_note"] is None

    def test_single_acknowledge_with_note(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        tenant_admin = test_data["tenant_admin"]
        token = get_auth_token(client, "tenant_admin", "test123")

        records = self._create_alert_records(db_session, tenant.id, project.id, count=1, ack=False)
        alert_id = records[0].id
        test_note = "已通知相关负责人处理，预计2小时内恢复"

        response = client.post(
            f"/api/v1/alerts/records/{alert_id}/acknowledge",
            json={"note": test_note},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_acknowledged"] is True
        assert data["acknowledged_at"] is not None
        assert data["acknowledged_by"] == tenant_admin.id
        assert data["acknowledge_note"] == test_note

        db_record = db_session.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
        assert db_record.is_acknowledged is True
        assert db_record.acknowledged_by == tenant_admin.id
        assert db_record.acknowledge_note == test_note
        assert db_record.acknowledged_at is not None

    def test_single_acknowledge_without_note(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        tenant_admin = test_data["tenant_admin"]
        token = get_auth_token(client, "tenant_admin", "test123")

        records = self._create_alert_records(db_session, tenant.id, project.id, count=1, ack=False)
        alert_id = records[0].id

        response = client.post(
            f"/api/v1/alerts/records/{alert_id}/acknowledge",
            json={},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_acknowledged"] is True
        assert data["acknowledged_by"] == tenant_admin.id
        assert data["acknowledge_note"] is None

    def test_batch_acknowledge_success(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        tenant_admin = test_data["tenant_admin"]
        token = get_auth_token(client, "tenant_admin", "test123")

        records = self._create_alert_records(db_session, tenant.id, project.id, count=3, ack=False)
        record_ids = [r.id for r in records]
        test_note = "批量确认：已安排运维团队处理"

        response = client.post(
            "/api/v1/alerts/records/batch-acknowledge",
            json={
                "record_ids": record_ids,
                "note": test_note
            },
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 3
        assert data["failed_count"] == 0
        assert data["failed_ids"] == []

        for record_id in record_ids:
            db_record = db_session.query(AlertRecord).filter(AlertRecord.id == record_id).first()
            assert db_record.is_acknowledged is True
            assert db_record.acknowledged_by == tenant_admin.id
            assert db_record.acknowledge_note == test_note
            assert db_record.acknowledged_at is not None

    def test_batch_acknowledge_partial_failure(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        token = get_auth_token(client, "tenant_admin", "test123")

        unacked_records = self._create_alert_records(db_session, tenant.id, project.id, count=2, ack=False)
        acked_records = self._create_alert_records(db_session, tenant.id, project.id, count=1, ack=True)

        all_ids = [r.id for r in unacked_records] + [r.id for r in acked_records] + [99999]

        response = client.post(
            "/api/v1/alerts/records/batch-acknowledge",
            json={
                "record_ids": all_ids,
                "note": "批量处理"
            },
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 2
        assert data["failed_count"] == 2
        assert len(data["failed_ids"]) == 2
        assert 99999 in data["failed_ids"]
        assert data["details"]["99999"] == "Alert record not found"

        for acked_id in [r.id for r in acked_records]:
            assert acked_id in data["failed_ids"]
            assert data["details"][str(acked_id)] == "Alert already acknowledged"

    def test_cross_tenant_acknowledge_denied(self, db_session, client, test_data):
        tenant1 = test_data["tenant"]
        project1 = test_data["project"]
        tenant2 = test_data["tenant2"]
        project_t2 = test_data["project_t2"]

        t1_token = get_auth_token(client, "tenant_admin", "test123")

        t2_records = self._create_alert_records(db_session, tenant2.id, project_t2.id, count=2, ack=False)
        t2_alert_id = t2_records[0].id

        response = client.post(
            f"/api/v1/alerts/records/{t2_alert_id}/acknowledge",
            json={"note": "越权测试"},
            headers={"Authorization": f"Bearer {t1_token}"}
        )

        assert response.status_code == 403
        assert "other tenants" in response.json()["detail"].lower() or "Access denied" in response.json()["detail"]

        db_record = db_session.query(AlertRecord).filter(AlertRecord.id == t2_alert_id).first()
        assert db_record.is_acknowledged is False

    def test_cross_tenant_batch_acknowledge_denied(self, db_session, client, test_data):
        tenant1 = test_data["tenant"]
        project1 = test_data["project"]
        tenant2 = test_data["tenant2"]
        project_t2 = test_data["project_t2"]

        t1_token = get_auth_token(client, "tenant_admin", "test123")

        t1_records = self._create_alert_records(db_session, tenant1.id, project1.id, count=2, ack=False)
        t2_records = self._create_alert_records(db_session, tenant2.id, project_t2.id, count=2, ack=False)

        all_ids = [r.id for r in t1_records] + [r.id for r in t2_records]

        response = client.post(
            "/api/v1/alerts/records/batch-acknowledge",
            json={
                "record_ids": all_ids,
                "note": "批量测试"
            },
            headers={"Authorization": f"Bearer {t1_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 2
        assert data["failed_count"] == 2

        for t2_id in [r.id for r in t2_records]:
            assert t2_id in data["failed_ids"]
            assert "other tenants" in data["details"][str(t2_id)].lower() or "Access denied" in data["details"][str(t2_id)]

        for t2_id in [r.id for r in t2_records]:
            db_record = db_session.query(AlertRecord).filter(AlertRecord.id == t2_id).first()
            assert db_record.is_acknowledged is False

    def test_duplicate_acknowledge_returns_error(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        token = get_auth_token(client, "tenant_admin", "test123")

        records = self._create_alert_records(db_session, tenant.id, project.id, count=1, ack=False)
        alert_id = records[0].id

        first_response = client.post(
            f"/api/v1/alerts/records/{alert_id}/acknowledge",
            json={"note": "第一次确认"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert first_response.status_code == 200

        second_response = client.post(
            f"/api/v1/alerts/records/{alert_id}/acknowledge",
            json={"note": "重复确认"},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert second_response.status_code == 400
        assert "already acknowledged" in second_response.json()["detail"].lower()

        db_record = db_session.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
        assert db_record.acknowledge_note == "第一次确认"

    def test_acknowledge_note_persisted_in_db(self, db_session, client, test_data):
        tenant = test_data["tenant"]
        project = test_data["project"]
        tenant_admin = test_data["tenant_admin"]
        token = get_auth_token(client, "tenant_admin", "test123")

        records = self._create_alert_records(db_session, tenant.id, project.id, count=1, ack=False)
        alert_id = records[0].id
        test_note = "备注内容测试：这是一条很长的备注，包含中文、English 和数字 12345，以及特殊字符 !@#$%^&*()"

        response = client.post(
            f"/api/v1/alerts/records/{alert_id}/acknowledge",
            json={"note": test_note},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200

        db_record = db_session.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
        assert db_record.acknowledge_note == test_note
        assert db_record.acknowledged_by == tenant_admin.id
        assert db_record.acknowledged_at is not None

        detail_response = client.get(
            f"/api/v1/alerts/records/{alert_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert detail_response.status_code == 200
        detail_data = detail_response.json()
        assert detail_data["acknowledge_note"] == test_note
        assert detail_data["acknowledged_by"] == tenant_admin.id

    def test_admin_can_acknowledge_any_tenant_alert(self, db_session, client, test_data):
        tenant2 = test_data["tenant2"]
        project_t2 = test_data["project_t2"]
        admin = test_data["admin"]
        admin_token = get_auth_token(client, "test_admin", "test123")

        records = self._create_alert_records(db_session, tenant2.id, project_t2.id, count=1, ack=False)
        alert_id = records[0].id

        response = client.post(
            f"/api/v1/alerts/records/{alert_id}/acknowledge",
            json={"note": "管理员确认"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_acknowledged"] is True
        assert data["acknowledged_by"] == admin.id
        assert data["acknowledge_note"] == "管理员确认"

    def test_empty_batch_acknowledge_returns_error(self, db_session, client, test_data):
        token = get_auth_token(client, "tenant_admin", "test123")

        response = client.post(
            "/api/v1/alerts/records/batch-acknowledge",
            json={"record_ids": []},
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 400
        assert "No record IDs provided" in response.json()["detail"]

    def test_tenant_admin_sees_only_own_tenant_alerts(self, db_session, client, test_data):
        tenant1 = test_data["tenant"]
        project1 = test_data["project"]
        tenant2 = test_data["tenant2"]
        project_t2 = test_data["project_t2"]

        t1_token = get_auth_token(client, "tenant_admin", "test123")

        self._create_alert_records(db_session, tenant1.id, project1.id, count=3, ack=False)
        self._create_alert_records(db_session, tenant2.id, project_t2.id, count=2, ack=False)

        response = client.get(
            "/api/v1/alerts/records",
            params={"is_acknowledged": False},
            headers={"Authorization": f"Bearer {t1_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        for record in data:
            assert record["tenant_id"] == tenant1.id


def get_auth_token(client, username, password):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password}
    )
    return response.json()["access_token"]
