import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import secrets
import string

from app.database import Base, get_db
from app.models import (
    User, Tenant, Project, Plan, PlanQuota, PlanAssignment,
    APIKey, APIKeyStatus, BillingPeriod, OverLimitAction,
    TenantStatus
)
from app.security import get_password_hash, hash_api_key
from main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def generate_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    prefix = "sk_" + "".join(secrets.choice(alphabet) for _ in range(8))
    rest = "".join(secrets.choice(alphabet) for _ in range(32))
    return f"{prefix}_{rest}"


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_data(db_session):
    admin = User(
        username="test_admin",
        email="admin@test.com",
        hashed_password=get_password_hash("test123"),
        is_active=True,
        is_admin=True
    )
    db_session.add(admin)

    tenant_admin = User(
        username="tenant_admin",
        email="tenant@test.com",
        hashed_password=get_password_hash("test123"),
        is_active=True,
        is_admin=False
    )
    db_session.add(tenant_admin)

    tenant = Tenant(
        name="Test Tenant",
        status=TenantStatus.ACTIVE,
        contact_email="tenant@test.com"
    )
    db_session.add(tenant)
    db_session.flush()

    tenant_admin.tenant_id = tenant.id

    project = Project(
        tenant_id=tenant.id,
        name="Test Project",
        description="Test project",
        is_active=True
    )
    db_session.add(project)
    db_session.flush()

    project2 = Project(
        tenant_id=tenant.id,
        name="Test Project 2",
        description="Test project 2",
        is_active=True
    )
    db_session.add(project2)
    db_session.flush()

    plan_charge = Plan(
        tenant_id=tenant.id,
        name="Charge Plan",
        description="Over limit will be charged",
        billing_period=BillingPeriod.MONTHLY,
        over_limit_action=OverLimitAction.CHARGE,
        is_active=True
    )
    db_session.add(plan_charge)
    db_session.flush()

    quota1 = PlanQuota(
        plan_id=plan_charge.id,
        resource_type="api_calls",
        limit=1000,
        unit_price=0.01,
        over_limit_price=0.02
    )
    quota2 = PlanQuota(
        plan_id=plan_charge.id,
        resource_type="storage_gb",
        limit=100,
        unit_price=0.5,
        over_limit_price=1.0
    )
    db_session.add_all([quota1, quota2])

    plan_reject = Plan(
        tenant_id=tenant.id,
        name="Reject Plan",
        description="Over limit will be rejected",
        billing_period=BillingPeriod.MONTHLY,
        over_limit_action=OverLimitAction.REJECT,
        is_active=True
    )
    db_session.add(plan_reject)
    db_session.flush()

    quota3 = PlanQuota(
        plan_id=plan_reject.id,
        resource_type="api_calls",
        limit=500,
        unit_price=0.01,
        over_limit_price=0.02
    )
    db_session.add(quota3)

    plan_daily = Plan(
        tenant_id=tenant.id,
        name="Daily Plan",
        description="Daily billing plan",
        billing_period=BillingPeriod.DAILY,
        over_limit_action=OverLimitAction.CHARGE,
        is_active=True
    )
    db_session.add(plan_daily)
    db_session.flush()

    quota4 = PlanQuota(
        plan_id=plan_daily.id,
        resource_type="api_calls",
        limit=100,
        unit_price=0.01,
        over_limit_price=0.02
    )
    db_session.add(quota4)

    assignment1 = PlanAssignment(
        plan_id=plan_charge.id,
        project_id=project.id,
        effective_from=datetime(2024, 1, 1),
        is_active=True
    )
    db_session.add(assignment1)

    assignment2 = PlanAssignment(
        plan_id=plan_reject.id,
        project_id=project2.id,
        effective_from=datetime(2024, 1, 1),
        is_active=True
    )
    db_session.add(assignment2)

    raw_key1 = generate_api_key()
    api_key1 = APIKey(
        project_id=project.id,
        key_hash=hash_api_key(raw_key1),
        key_prefix=raw_key1[:10],
        name="Active Key",
        status=APIKeyStatus.ACTIVE
    )
    db_session.add(api_key1)

    raw_key2 = generate_api_key()
    api_key2 = APIKey(
        project_id=project.id,
        key_hash=hash_api_key(raw_key2),
        key_prefix=raw_key2[:10],
        name="Disabled Key",
        status=APIKeyStatus.DISABLED
    )
    db_session.add(api_key2)

    raw_key3 = generate_api_key()
    api_key3 = APIKey(
        project_id=project2.id,
        key_hash=hash_api_key(raw_key3),
        key_prefix=raw_key3[:10],
        name="Project 2 Key",
        status=APIKeyStatus.ACTIVE
    )
    db_session.add(api_key3)

    tenant2 = Tenant(
        name="Test Tenant 2",
        status=TenantStatus.ACTIVE,
        contact_email="tenant2@test.com"
    )
    db_session.add(tenant2)
    db_session.flush()

    project_t2 = Project(
        tenant_id=tenant2.id,
        name="Tenant 2 Project",
        description="Project for tenant 2",
        is_active=True
    )
    db_session.add(project_t2)
    db_session.flush()

    plan_t2 = Plan(
        tenant_id=tenant2.id,
        name="Tenant 2 Plan",
        description="Plan for tenant 2",
        billing_period=BillingPeriod.MONTHLY,
        over_limit_action=OverLimitAction.CHARGE,
        is_active=True
    )
    db_session.add(plan_t2)
    db_session.flush()

    quota_t2 = PlanQuota(
        plan_id=plan_t2.id,
        resource_type="api_calls",
        limit=500,
        unit_price=0.01,
        over_limit_price=0.02
    )
    db_session.add(quota_t2)

    assignment_t2 = PlanAssignment(
        plan_id=plan_t2.id,
        project_id=project_t2.id,
        effective_from=datetime(2024, 1, 1),
        is_active=True
    )
    db_session.add(assignment_t2)

    raw_key_t2 = generate_api_key()
    api_key_t2 = APIKey(
        project_id=project_t2.id,
        key_hash=hash_api_key(raw_key_t2),
        key_prefix=raw_key_t2[:10],
        name="Tenant 2 Active Key",
        status=APIKeyStatus.ACTIVE
    )
    db_session.add(api_key_t2)

    tenant2_admin = User(
        username="tenant2_admin",
        email="tenant2@test.com",
        hashed_password=get_password_hash("test123"),
        is_active=True,
        is_admin=False,
        tenant_id=tenant2.id
    )
    db_session.add(tenant2_admin)

    db_session.commit()

    return {
        "admin": admin,
        "tenant_admin": tenant_admin,
        "tenant": tenant,
        "project": project,
        "project2": project2,
        "plan_charge": plan_charge,
        "plan_reject": plan_reject,
        "plan_daily": plan_daily,
        "api_key_active": (raw_key1, api_key1),
        "api_key_disabled": (raw_key2, api_key2),
        "api_key_project2": (raw_key3, api_key3),
        "tenant2": tenant2,
        "tenant2_admin": tenant2_admin,
        "project_t2": project_t2,
        "api_key_t2": (raw_key_t2, api_key_t2)
    }


def get_auth_token(client, username, password):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password}
    )
    return response.json()["access_token"]
