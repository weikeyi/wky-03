import sys
import os
from datetime import datetime, timedelta
import secrets
import string

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, Base, engine
from app.models import (
    User, Tenant, Project, Plan, PlanQuota, PlanAssignment,
    APIKey, AlertRule, AlertThresholdType, AlertSeverity,
    BillingPeriod, OverLimitAction, APIKeyStatus, TenantStatus
)
from app.security import get_password_hash, hash_api_key


def generate_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    prefix = "sk_" + "".join(secrets.choice(alphabet) for _ in range(8))
    rest = "".join(secrets.choice(alphabet) for _ in range(32))
    return f"{prefix}_{rest}"


def init_database():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully.")


def seed_data():
    db = SessionLocal()

    try:
        print("\n=== Seeding data ===")

        admin_user = db.query(User).filter(User.username == "admin").first()
        if not admin_user:
            admin_user = User(
                username="admin",
                email="admin@example.com",
                hashed_password=get_password_hash("admin123"),
                is_active=True,
                is_admin=True
            )
            db.add(admin_user)
            print("✓ Created admin user (admin/admin123)")

        tenant1 = db.query(Tenant).filter(Tenant.name == "示例科技有限公司").first()
        if not tenant1:
            tenant1 = Tenant(
                name="示例科技有限公司",
                status=TenantStatus.ACTIVE,
                contact_email="contact@example.com",
                contact_phone="400-123-4567",
                billing_address="北京市朝阳区科技园路88号"
            )
            db.add(tenant1)
            db.flush()
            print("✓ Created tenant: 示例科技有限公司")
        else:
            db.flush()

        tenant1_user = db.query(User).filter(User.username == "tenant1_admin").first()
        if not tenant1_user:
            tenant1_user = User(
                username="tenant1_admin",
                email="admin@techcorp.com",
                hashed_password=get_password_hash("tenant123"),
                is_active=True,
                is_admin=False,
                tenant_id=tenant1.id
            )
            db.add(tenant1_user)
            print("✓ Created tenant admin user (tenant1_admin/tenant123)")

        project1 = db.query(Project).filter(
            Project.tenant_id == tenant1.id,
            Project.name == "智能客服系统"
        ).first()
        if not project1:
            project1 = Project(
                tenant_id=tenant1.id,
                name="智能客服系统",
                description="企业级智能客服解决方案",
                is_active=True
            )
            db.add(project1)
            db.flush()
            print("✓ Created project: 智能客服系统")
        else:
            db.flush()

        project2 = db.query(Project).filter(
            Project.tenant_id == tenant1.id,
            Project.name == "数据分析平台"
        ).first()
        if not project2:
            project2 = Project(
                tenant_id=tenant1.id,
                name="数据分析平台",
                description="大数据分析与可视化平台",
                is_active=True
            )
            db.add(project2)
            db.flush()
            print("✓ Created project: 数据分析平台")
        else:
            db.flush()

        standard_plan = db.query(Plan).filter(
            Plan.tenant_id == tenant1.id,
            Plan.name == "标准版套餐"
        ).first()
        if not standard_plan:
            standard_plan = Plan(
                tenant_id=tenant1.id,
                name="标准版套餐",
                description="适合中小规模业务的标准套餐",
                billing_period=BillingPeriod.MONTHLY,
                over_limit_action=OverLimitAction.CHARGE,
                is_active=True
            )
            db.add(standard_plan)
            db.flush()

            quota1 = PlanQuota(
                plan_id=standard_plan.id,
                resource_type="api_calls",
                limit=100000,
                unit_price=0.001,
                over_limit_price=0.002
            )
            quota2 = PlanQuota(
                plan_id=standard_plan.id,
                resource_type="storage_gb",
                limit=100,
                unit_price=0.5,
                over_limit_price=1.0
            )
            quota3 = PlanQuota(
                plan_id=standard_plan.id,
                resource_type="compute_hours",
                limit=500,
                unit_price=0.1,
                over_limit_price=0.2
            )
            db.add_all([quota1, quota2, quota3])
            print("✓ Created plan: 标准版套餐 with 3 quotas")
        else:
            db.flush()

        enterprise_plan = db.query(Plan).filter(
            Plan.tenant_id == tenant1.id,
            Plan.name == "企业版套餐"
        ).first()
        if not enterprise_plan:
            enterprise_plan = Plan(
                tenant_id=tenant1.id,
                name="企业版套餐",
                description="适合大型企业的高级套餐，支持超额拒绝",
                billing_period=BillingPeriod.MONTHLY,
                over_limit_action=OverLimitAction.REJECT,
                is_active=True
            )
            db.add(enterprise_plan)
            db.flush()

            quota1 = PlanQuota(
                plan_id=enterprise_plan.id,
                resource_type="api_calls",
                limit=1000000,
                unit_price=0.0005,
                over_limit_price=0.001
            )
            quota2 = PlanQuota(
                plan_id=enterprise_plan.id,
                resource_type="storage_gb",
                limit=1000,
                unit_price=0.3,
                over_limit_price=0.6
            )
            quota3 = PlanQuota(
                plan_id=enterprise_plan.id,
                resource_type="compute_hours",
                limit=5000,
                unit_price=0.05,
                over_limit_price=0.1
            )
            db.add_all([quota1, quota2, quota3])
            print("✓ Created plan: 企业版套餐 with 3 quotas")
        else:
            db.flush()

        daily_plan = db.query(Plan).filter(
            Plan.tenant_id == tenant1.id,
            Plan.name == "日结测试套餐"
        ).first()
        if not daily_plan:
            daily_plan = Plan(
                tenant_id=tenant1.id,
                name="日结测试套餐",
                description="按日结算的测试套餐",
                billing_period=BillingPeriod.DAILY,
                over_limit_action=OverLimitAction.CHARGE,
                is_active=True
            )
            db.add(daily_plan)
            db.flush()

            quota1 = PlanQuota(
                plan_id=daily_plan.id,
                resource_type="api_calls",
                limit=1000,
                unit_price=0.001,
                over_limit_price=0.002
            )
            db.add(quota1)
            print("✓ Created plan: 日结测试套餐")
        else:
            db.flush()

        existing_assignment1 = db.query(PlanAssignment).filter(
            PlanAssignment.project_id == project1.id,
            PlanAssignment.is_active == True
        ).first()
        if not existing_assignment1:
            assignment1 = PlanAssignment(
                plan_id=standard_plan.id,
                project_id=project1.id,
                effective_from=datetime.utcnow() - timedelta(days=30),
                is_active=True
            )
            db.add(assignment1)
            print("✓ Assigned 标准版套餐 to 智能客服系统")
        else:
            db.flush()

        existing_assignment2 = db.query(PlanAssignment).filter(
            PlanAssignment.project_id == project2.id,
            PlanAssignment.is_active == True
        ).first()
        if not existing_assignment2:
            assignment2 = PlanAssignment(
                plan_id=enterprise_plan.id,
                project_id=project2.id,
                effective_from=datetime.utcnow() - timedelta(days=30),
                is_active=True
            )
            db.add(assignment2)
            print("✓ Assigned 企业版套餐 to 数据分析平台")
        else:
            db.flush()

        api_key1 = db.query(APIKey).filter(
            APIKey.project_id == project1.id,
            APIKey.name == "生产环境密钥"
        ).first()
        if not api_key1:
            raw_key1 = generate_api_key()
            api_key1 = APIKey(
                project_id=project1.id,
                key_hash=hash_api_key(raw_key1),
                key_prefix=raw_key1[:10],
                name="生产环境密钥",
                status=APIKeyStatus.ACTIVE
            )
            db.add(api_key1)
            print(f"✓ Created API Key for 智能客服系统: {raw_key1}")

        api_key2 = db.query(APIKey).filter(
            APIKey.project_id == project2.id,
            APIKey.name == "数据分析密钥"
        ).first()
        if not api_key2:
            raw_key2 = generate_api_key()
            api_key2 = APIKey(
                project_id=project2.id,
                key_hash=hash_api_key(raw_key2),
                key_prefix=raw_key2[:10],
                name="数据分析密钥",
                status=APIKeyStatus.ACTIVE
            )
            db.add(api_key2)
            print(f"✓ Created API Key for 数据分析平台: {raw_key2}")

        api_key3 = db.query(APIKey).filter(
            APIKey.project_id == project1.id,
            APIKey.name == "测试环境密钥（已禁用）"
        ).first()
        if not api_key3:
            raw_key3 = generate_api_key()
            api_key3 = APIKey(
                project_id=project1.id,
                key_hash=hash_api_key(raw_key3),
                key_prefix=raw_key3[:10],
                name="测试环境密钥（已禁用）",
                status=APIKeyStatus.DISABLED
            )
            db.add(api_key3)
            print(f"✓ Created disabled API Key: {raw_key3}")

        alert_rule1 = db.query(AlertRule).filter(
            AlertRule.tenant_id == tenant1.id,
            AlertRule.name == "API调用量75%预警"
        ).first()
        if not alert_rule1:
            alert_rule1 = AlertRule(
                tenant_id=tenant1.id,
                name="API调用量75%预警",
                resource_type="api_calls",
                threshold_type=AlertThresholdType.PERCENTAGE,
                threshold=75,
                severity=AlertSeverity.WARNING,
                is_active=True
            )
            db.add(alert_rule1)
            print("✓ Created alert rule: API调用量75%预警")

        alert_rule2 = db.query(AlertRule).filter(
            AlertRule.tenant_id == tenant1.id,
            AlertRule.name == "存储用量50GB预警"
        ).first()
        if not alert_rule2:
            alert_rule2 = AlertRule(
                tenant_id=tenant1.id,
                name="存储用量50GB预警",
                resource_type="storage_gb",
                threshold_type=AlertThresholdType.ABSOLUTE,
                threshold=50,
                severity=AlertSeverity.WARNING,
                is_active=True
            )
            db.add(alert_rule2)
            print("✓ Created alert rule: 存储用量50GB预警")

        alert_rule3 = db.query(AlertRule).filter(
            AlertRule.tenant_id == tenant1.id,
            AlertRule.name == "全资源90%严重告警"
        ).first()
        if not alert_rule3:
            alert_rule3 = AlertRule(
                tenant_id=tenant1.id,
                name="全资源90%严重告警",
                resource_type=None,
                threshold_type=AlertThresholdType.PERCENTAGE,
                threshold=90,
                severity=AlertSeverity.CRITICAL,
                is_active=True
            )
            db.add(alert_rule3)
            print("✓ Created alert rule: 全资源90%严重告警")

        db.commit()
        print("\n=== Seed data completed successfully! ===")
        print("\nDemo credentials:")
        print("  Admin: admin / admin123")
        print("  Tenant Admin: tenant1_admin / tenant123")

    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Multi-tenant API Billing & Quota Service - Data Seeder")
    print("=" * 60)

    init_database()
    seed_data()

    print("\n" + "=" * 60)
    print("Seeding completed! You can now run:")
    print("  python main.py")
    print("Then visit: http://localhost:8000/docs")
    print("=" * 60)
