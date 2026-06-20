import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _safe_print(s="", end="\n"):
    try:
        print(s, end=end)
    except UnicodeEncodeError:
        ascii_s = s.replace("✓", "[OK]").replace("✗", "[FAIL]")
        try:
            print(ascii_s, end=end)
        except UnicodeEncodeError:
            print(s.encode("ascii", errors="replace").decode("ascii"), end=end)

def _setup_console_encoding():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            try:
                import io
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer, encoding="utf-8", errors="replace"
                )
                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer, encoding="utf-8", errors="replace"
                )
            except Exception:
                pass

_setup_console_encoding()

from app.database import Base, engine
from app import models  # noqa: F401

def init_database():
    _safe_print("=" * 60)
    _safe_print("Multi-tenant API Billing & Quota Service - DB Initializer")
    _safe_print("=" * 60)

    _safe_print("\n[1/2] Creating database tables...")
    Base.metadata.create_all(bind=engine)
    _safe_print("✓ Database tables created successfully.")

    _safe_print("\n[2/2] Verifying database tables...")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for table in sorted(tables):
        _safe_print(f"  - {table}")
    _safe_print(f"\n✓ Total {len(tables)} tables initialized.")

    _safe_print("\n" + "=" * 60)
    _safe_print("Database initialization completed!")
    _safe_print("Next step: python seed_data.py")
    _safe_print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        init_database()
    except Exception as e:
        _safe_print(f"\nError initializing database: {e}")
        sys.exit(1)
