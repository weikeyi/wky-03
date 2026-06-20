import pytest
from datetime import datetime, timedelta
import uuid
from tests.conftest import get_auth_token


class TestAuthAPI:
    def test_login_success(self, client, test_data):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test_admin", "password": "test123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client, test_data):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test_admin", "password": "wrong_password"}
        )
        assert response.status_code == 401

    def test_get_current_user(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "test_admin"
        assert data["is_admin"] == True

    def test_register_user(self, client, test_data):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "new_user",
                "email": "new@test.com",
                "password": "newpass123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "new_user"


class TestTenantAPI:
    def test_create_tenant_as_admin(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        response = client.post(
            "/api/v1/tenants",
            json={
                "name": "New Test Tenant",
                "contact_email": "new@tenant.com"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Test Tenant"

    def test_create_tenant_as_non_admin(self, client, test_data):
        token = get_auth_token(client, "tenant_admin", "test123")
        response = client.post(
            "/api/v1/tenants",
            json={
                "name": "Unauthorized Tenant",
                "contact_email": "bad@tenant.com"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    def test_get_tenants(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        response = client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_get_tenant_by_id(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]
        response = client.get(
            f"/api/v1/tenants/{tenant.id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == tenant.id
        assert data["name"] == tenant.name


class TestProjectAPI:
    def test_create_project(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]
        response = client.post(
            "/api/v1/projects",
            json={
                "tenant_id": tenant.id,
                "name": "New API Project",
                "description": "Test project for API"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New API Project"

    def test_get_projects(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        response = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    def test_update_project(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        project = test_data["project"]
        response = client.put(
            f"/api/v1/projects/{project.id}",
            json={
                "name": "Updated Project Name",
                "description": "Updated description"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Project Name"


class TestAPIKeyAPI:
    def test_create_api_key(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        project = test_data["project"]
        response = client.post(
            "/api/v1/api-keys",
            json={
                "project_id": project.id,
                "name": "New Test Key"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert "api_key" in data
        assert data["name"] == "New Test Key"

    def test_get_api_keys(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        response = client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    def test_disable_api_key(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        _, api_key_obj = test_data["api_key_active"]
        response = client.post(
            f"/api/v1/api-keys/{api_key_obj.id}/disable",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"

    def test_enable_api_key(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        _, api_key_obj = test_data["api_key_disabled"]
        response = client.post(
            f"/api/v1/api-keys/{api_key_obj.id}/enable",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"


class TestPlanAPI:
    def test_create_plan(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]
        response = client.post(
            "/api/v1/plans",
            json={
                "tenant_id": tenant.id,
                "name": "New Test Plan",
                "description": "Test plan",
                "billing_period": "monthly",
                "over_limit_action": "charge",
                "quotas": [
                    {
                        "resource_type": "new_resource",
                        "limit": 500,
                        "unit_price": 0.01,
                        "over_limit_price": 0.02
                    }
                ]
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Test Plan"
        assert len(data["quotas"]) == 1

    def test_get_plans(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        response = client.get(
            "/api/v1/plans",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    def test_assign_plan_to_project(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        project = test_data["project"]
        plan = test_data["plan_charge"]
        response = client.post(
            "/api/v1/plans/assignments",
            json={
                "plan_id": plan.id,
                "project_id": project.id,
                "effective_from": datetime.utcnow().isoformat()
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201


class TestUsageAPI:
    def test_report_usage_success(self, client, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        response = client.post(
            "/api/v1/usage/report",
            json={
                "api_key": api_key,
                "tenant_id": tenant.id,
                "project_id": project.id,
                "idempotency_key": str(uuid.uuid4()),
                "resource_type": "api_calls",
                "amount": 50,
                "request_time": datetime.utcnow().isoformat()
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["amount"] == 50

    def test_report_usage_with_disabled_key(self, client, test_data):
        api_key, _ = test_data["api_key_disabled"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        response = client.post(
            "/api/v1/usage/report",
            json={
                "api_key": api_key,
                "tenant_id": tenant.id,
                "project_id": project.id,
                "idempotency_key": str(uuid.uuid4()),
                "resource_type": "api_calls",
                "amount": 50,
                "request_time": datetime.utcnow().isoformat()
            }
        )
        assert response.status_code == 401

    def test_batch_report_usage(self, client, test_data):
        api_key, _ = test_data["api_key_active"]
        tenant = test_data["tenant"]
        project = test_data["project"]

        events = []
        for i in range(3):
            events.append({
                "api_key": api_key,
                "tenant_id": tenant.id,
                "project_id": project.id,
                "idempotency_key": str(uuid.uuid4()),
                "resource_type": "api_calls",
                "amount": 10,
                "request_time": datetime.utcnow().isoformat()
            })

        events.append({
            "api_key": api_key,
            "tenant_id": tenant.id,
            "project_id": project.id,
            "idempotency_key": events[0]["idempotency_key"],
            "resource_type": "api_calls",
            "amount": 10,
            "request_time": datetime.utcnow().isoformat()
        })

        response = client.post(
            "/api/v1/usage/batch",
            json=events
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 3
        assert data["duplicate_count"] == 1

    def test_get_current_usage(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        api_key, _ = test_data["api_key_active"]
        project = test_data["project"]
        client.post(
            "/api/v1/usage/report",
            json={
                "api_key": api_key,
                "tenant_id": tenant.id,
                "project_id": project.id,
                "idempotency_key": str(uuid.uuid4()),
                "resource_type": "api_calls",
                "amount": 100,
                "request_time": datetime.utcnow().isoformat()
            }
        )

        response = client.get(
            "/api/v1/usage/current",
            params={"tenant_id": tenant.id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1


class TestBillingAPI:
    def test_get_bill_preview(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        response = client.get(
            "/api/v1/billing/preview",
            params={"tenant_id": tenant.id, "period": "monthly"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "billing_cycle" in data
        assert "total_amount" in data
        assert "aggregations" in data
        assert "summary" in data

    def test_get_billing_cycles(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        response = client.get(
            "/api/v1/billing/cycles",
            params={"tenant_id": tenant.id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    def test_get_billing_history(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        response = client.get(
            "/api/v1/billing/history",
            params={"tenant_id": tenant.id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200


class TestAlertAPI:
    def test_create_alert_rule(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        response = client.post(
            "/api/v1/alerts/rules",
            json={
                "tenant_id": tenant.id,
                "name": "Custom Alert Rule",
                "resource_type": "api_calls",
                "threshold_type": "percentage",
                "threshold": 85,
                "severity": "warning"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Custom Alert Rule"

    def test_get_alert_rules(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")

        response = client.get(
            "/api/v1/alerts/rules",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    def test_get_alert_records(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        api_key, _ = test_data["api_key_active"]
        project = test_data["project"]
        client.post(
            "/api/v1/usage/report",
            json={
                "api_key": api_key,
                "tenant_id": tenant.id,
                "project_id": project.id,
                "idempotency_key": str(uuid.uuid4()),
                "resource_type": "api_calls",
                "amount": 900,
                "request_time": datetime.utcnow().isoformat()
            }
        )

        response = client.get(
            "/api/v1/alerts/records",
            params={"tenant_id": tenant.id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_acknowledge_alert(self, client, test_data):
        token = get_auth_token(client, "test_admin", "test123")
        tenant = test_data["tenant"]

        api_key, _ = test_data["api_key_active"]
        project = test_data["project"]
        client.post(
            "/api/v1/usage/report",
            json={
                "api_key": api_key,
                "tenant_id": tenant.id,
                "project_id": project.id,
                "idempotency_key": str(uuid.uuid4()),
                "resource_type": "api_calls",
                "amount": 900,
                "request_time": datetime.utcnow().isoformat()
            }
        )

        response = client.get(
            "/api/v1/alerts/records",
            params={"tenant_id": tenant.id, "is_acknowledged": False},
            headers={"Authorization": f"Bearer {token}"}
        )
        alerts = response.json()
        if len(alerts) > 0:
            alert_id = alerts[0]["id"]
            ack_response = client.post(
                f"/api/v1/alerts/records/{alert_id}/acknowledge",
                json={},
                headers={"Authorization": f"Bearer {token}"}
            )
            assert ack_response.status_code == 200
            data = ack_response.json()
            assert data["is_acknowledged"] == True


class TestSystemAPI:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_root_endpoint(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["status"] == "running"
