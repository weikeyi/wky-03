import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import subprocess
import tempfile
import shutil
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = sys.executable


@pytest.fixture(scope="module")
def tmp_workdir():
    tmpdir = tempfile.mkdtemp(prefix="test_billing_init_")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope="module")
def tmp_db_url(tmp_workdir):
    db_path = os.path.join(tmp_workdir, "test.db")
    return f"sqlite:///{db_path}"


class TestDatabaseSchema:
    def test_all_models_create_expected_tables(self):
        from app.database import Base
        from app import models  # noqa: F401

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        expected = {
            "users", "tenants", "projects", "plans", "plan_quotas",
            "plan_assignments", "api_keys", "usage_events", "billing_cycles",
            "usage_aggregations", "alert_rules", "alert_records"
        }
        assert set(tables) == expected
        engine.dispose()

    def test_create_all_is_idempotent(self):
        from app.database import Base
        from app import models  # noqa: F401

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        inspector = inspect(engine)
        assert len(inspector.get_table_names()) == 12
        engine.dispose()

    def test_every_table_has_primary_key(self):
        from app.database import Base
        from app import models  # noqa: F401

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

        for table in inspector.get_table_names():
            pk = inspector.get_pk_constraint(table)
            assert len(pk["constrained_columns"]) > 0, \
                f"Table '{table}' has no primary key"
        engine.dispose()

    def test_usage_events_has_idempotency_unique_constraint(self):
        from app.database import Base
        from app import models  # noqa: F401

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

        ucs = inspector.get_unique_constraints("usage_events")
        idem_uc = [uc for uc in ucs
                   if "idempotency_key" in uc["column_names"]]
        assert len(idem_uc) > 0
        engine.dispose()

    def test_foreign_keys_present(self):
        from app.database import Base
        from app import models  # noqa: F401

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

        expected_fks = {
            "projects": ["tenant_id"],
            "plans": ["tenant_id"],
            "plan_quotas": ["plan_id"],
            "plan_assignments": ["plan_id", "project_id"],
            "api_keys": ["project_id"],
            "usage_events": ["tenant_id", "project_id", "api_key_id"],
            "billing_cycles": ["tenant_id"],
            "usage_aggregations": ["billing_cycle_id", "project_id"],
            "alert_rules": ["tenant_id"],
            "alert_records": ["tenant_id", "alert_rule_id", "project_id"],
            "users": ["tenant_id"],
        }

        for table, cols in expected_fks.items():
            fks = inspector.get_foreign_keys(table)
            fk_cols = {c for fk in fks for c in fk["constrained_columns"]}
            for col in cols:
                assert col in fk_cols, \
                    f"Table '{table}' missing FK column '{col}'"
        engine.dispose()


def _run_cmd(args, env=None, cwd=None):
    result = subprocess.run(
        args, capture_output=True, env=env, cwd=cwd
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    return result.returncode, stdout, stderr


class TestInitDbCommand:
    def test_init_db_runs_successfully(self, tmp_workdir, tmp_db_url):
        env = os.environ.copy()
        env["DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"

        rc, stdout, stderr = _run_cmd(
            [PYTHON_EXE, "init_db.py"],
            env=env, cwd=PROJECT_ROOT
        )
        assert rc == 0, f"STDOUT: {stdout}\nSTDERR: {stderr}"
        assert "Database tables created successfully" in stdout
        assert "Total 12 tables" in stdout

    def test_init_db_is_idempotent(self, tmp_workdir, tmp_db_url):
        env = os.environ.copy()
        env["DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"

        rc1, _, _ = _run_cmd(
            [PYTHON_EXE, "init_db.py"], env=env, cwd=PROJECT_ROOT
        )
        assert rc1 == 0

        rc2, stdout2, _ = _run_cmd(
            [PYTHON_EXE, "init_db.py"], env=env, cwd=PROJECT_ROOT
        )
        assert rc2 == 0
        assert "Database tables created successfully" in stdout2


class TestSeedDataCommand:
    def test_seed_data_runs_successfully(self, tmp_workdir, tmp_db_url):
        env = os.environ.copy()
        env["DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"

        _run_cmd([PYTHON_EXE, "init_db.py"], env=env, cwd=PROJECT_ROOT)

        rc, stdout, stderr = _run_cmd(
            [PYTHON_EXE, "seed_data.py"], env=env, cwd=PROJECT_ROOT
        )
        assert rc == 0, f"STDOUT: {stdout}\nSTDERR: {stderr}"
        assert "Seed data completed successfully" in stdout
        assert "admin / admin123" in stdout
        assert "tenant1_admin / tenant123" in stdout

    def test_seed_data_is_idempotent(self, tmp_workdir, tmp_db_url):
        env = os.environ.copy()
        env["DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"

        _run_cmd([PYTHON_EXE, "init_db.py"], env=env, cwd=PROJECT_ROOT)

        rc1, _, _ = _run_cmd(
            [PYTHON_EXE, "seed_data.py"], env=env, cwd=PROJECT_ROOT
        )
        assert rc1 == 0

        rc2, stdout2, _ = _run_cmd(
            [PYTHON_EXE, "seed_data.py"], env=env, cwd=PROJECT_ROOT
        )
        assert rc2 == 0
        assert "Seed data completed successfully" in stdout2

    def test_seeded_data_can_be_verified(self, tmp_workdir, tmp_db_url):
        env = os.environ.copy()
        env["DATABASE_URL"] = tmp_db_url
        env["PYTHONIOENCODING"] = "utf-8"

        _run_cmd([PYTHON_EXE, "init_db.py"], env=env, cwd=PROJECT_ROOT)
        _run_cmd([PYTHON_EXE, "seed_data.py"], env=env, cwd=PROJECT_ROOT)

        engine = create_engine(tmp_db_url, connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)
        session = Session()

        from app.models import User, Tenant, Project, Plan, APIKey, AlertRule

        assert session.query(User).count() >= 2
        assert session.query(Tenant).count() >= 1
        assert session.query(Project).count() >= 2
        assert session.query(Plan).count() >= 3
        assert session.query(APIKey).count() >= 3
        assert session.query(AlertRule).count() >= 3

        admin = session.query(User).filter_by(username="admin").first()
        assert admin is not None
        assert admin.is_admin is True

        tenant_admin = session.query(User).filter_by(username="tenant1_admin").first()
        assert tenant_admin is not None
        assert tenant_admin.is_admin is False

        session.close()
        engine.dispose()


class TestAcceptanceCompile:
    def test_compileall_passes(self):
        rc, stdout, stderr = _run_cmd(
            [PYTHON_EXE, "-m", "compileall", "-f",
             "app", "main.py", "seed_data.py", "init_db.py"],
            cwd=PROJECT_ROOT
        )
        assert rc == 0, f"STDOUT: {stdout}\nSTDERR: {stderr}"
        assert "Compiling" in stdout or "compiling" in stdout.lower()
