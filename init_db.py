import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import Base, engine
from app import models  # noqa: F401

def init_database():
    print("=" * 60)
    print("Multi-tenant API Billing & Quota Service - DB Initializer")
    print("=" * 60)

    print("\n[1/2] Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created successfully.")

    print("\n[2/2] Verifying database tables...")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for table in sorted(tables):
        print(f"  - {table}")
    print(f"\n✓ Total {len(tables)} tables initialized.")

    print("\n" + "=" * 60)
    print("Database initialization completed!")
    print("Next step: python seed_data.py")
    print("=" * 60)


if __name__ == "__main__":
    init_database()
