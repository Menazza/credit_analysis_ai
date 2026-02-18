"""
Seed default tenant, roles, user, company, canonical accounts, and rating model.
Run from backend: python -m scripts.seed
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.db.session import async_session_maker
from app.models.tenancy import Tenant, User, Role, UserRole
from app.models.company import Company
from app.models.mapping import CanonicalAccount
from app.models.metrics import RatingModel
from app.core.security import get_password_hash
from app.core.canonical_accounts import CANONICAL_ACCOUNTS


async def seed():
    async with async_session_maker() as db:
        result = await db.execute(select(Tenant).limit(1))
        if result.scalar_one_or_none():
            print("Tenant already exists. Skip seed.")
            return
        tenant = Tenant(name="Default Bank")
        db.add(tenant)
        await db.flush()
        role_analyst = Role(tenant_id=tenant.id, name="ANALYST")
        role_reviewer = Role(tenant_id=tenant.id, name="REVIEWER")
        role_approver = Role(tenant_id=tenant.id, name="APPROVER")
        role_admin = Role(tenant_id=tenant.id, name="ADMIN")
        db.add_all([role_analyst, role_reviewer, role_approver, role_admin])
        await db.flush()
        user = User(
            tenant_id=tenant.id,
            email="analyst@bank.com",
            name="Analyst User",
            hashed_password=get_password_hash("password"),
        )
        db.add(user)
        await db.flush()
        db.add(UserRole(user_id=user.id, role_id=role_analyst.id))
        db.add(UserRole(user_id=user.id, role_id=role_reviewer.id))
        company = Company(
            tenant_id=tenant.id,
            name="Sample (Pty) Ltd",
            sector="Retail",
            is_listed="false",
        )
        db.add(company)
        await db.flush()
        for acc in CANONICAL_ACCOUNTS:
            db.add(CanonicalAccount(**acc))
        config_path = Path(__file__).resolve().parent.parent / "app" / "core" / "rating_config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            rating_model = RatingModel(
                tenant_id=tenant.id,
                name=config.get("model_name", "Corporate Mid-Market v1"),
                version=config.get("version", "2026.01"),
                config_json=config,
            )
            db.add(rating_model)
        await db.commit()
        print("Seed done.")
        print("  Tenant:", tenant.name, str(tenant.id))
        print("  User: analyst@bank.com / password")
        print("  Company: Sample (Pty) Ltd")


if __name__ == "__main__":
    asyncio.run(seed())
