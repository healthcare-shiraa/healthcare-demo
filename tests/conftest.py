"""بيئة الاختبار: كل اختبار يعمل على قاعدة جديدة فارغة، مرة على SQLite ومرة على PostgreSQL.

PostgreSQL يُستخدم إذا ضُبط HC_PG_TEST_SUPERUSER_URL (خادم محلي للاختبار فقط).
في PostgreSQL يُستخدم حسابان: hc_owner (المالك/الإدارة) و hc_app (التطبيق بصلاحيات محدودة).
"""
from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from hc import admin_users  # noqa: E402
from hc.audit import Ctx  # noqa: E402
from hc.auth import login  # noqa: E402
from hc.db import make_engine  # noqa: E402
from hc.schema import APP_GRANTS, grant_app_role, init_database, run_sql_script  # noqa: E402

AUDIT_KEY = b"test-audit-key-0123456789abcdef-XYZ"
PASSWORD = "Test-Password-123"
# قواعد بيئة demo في الاختبارات: قيم تُولَّد عشوائيًا عند كل تشغيل (ليست ثوابت منشورة)،
# لأن النظام يرفض ثوابت الاختبار المعروفة في بيئة demo.
import secrets as _secrets  # noqa: E402
DEMO_AUDIT_KEY = ("demo-" + _secrets.token_urlsafe(32)).encode()
DEMO_PASSWORD = "Dm-" + _secrets.token_urlsafe(18)


def creds_for(env: str) -> tuple[bytes, str]:
    return (DEMO_AUDIT_KEY, DEMO_PASSWORD) if env == "demo" else (AUDIT_KEY, PASSWORD)
PG_SUPER = os.environ.get("HC_PG_TEST_SUPERUSER_URL")

PROBE_SQL = {
    "sqlite": """
        CREATE TABLE probe_items (id INTEGER PRIMARY KEY);
        CREATE TABLE probe_claims (id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL UNIQUE REFERENCES probe_items(id), claimed_by INTEGER NOT NULL);
    """,
    "postgresql": """
        CREATE TABLE probe_items (id bigint PRIMARY KEY);
        CREATE TABLE probe_claims (id bigserial PRIMARY KEY,
            item_id bigint NOT NULL UNIQUE REFERENCES probe_items(id), claimed_by bigint NOT NULL);
    """,
}


@dataclass
class TestDB:
    kind: str
    app: Ctx
    admin: Ctx
    app_url: str
    admin_url: str
    db_name: str | None = None
    password: str = PASSWORD

    def user(self, username: str, role: str) -> None:
        admin_users.create_user(self.admin, operator="pytest", username=username,
                                full_name=f"مستخدم {username}", role=role, password=self.password)

    def session(self, username: str, role: str):
        self.user(username, role)
        return login(self.app, username, self.password)

    def count(self, table: str, where: str = "1=1", **params) -> int:
        with self.admin.engine.connect() as c:
            return c.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params).scalar_one()

    def audit_rows(self, **filters):
        sql = "SELECT * FROM audit_log"
        if filters:
            sql += " WHERE " + " AND ".join(f"{k} = :{k}" for k in filters)
        with self.admin.engine.connect() as c:
            return [dict(r) for r in c.execute(text(sql + " ORDER BY seq"), filters).mappings()]

    def add_fake_allergens(self) -> list[int]:
        from load_test_fixtures import load
        env = {"HC_ENV": "test", "HC_TEST_DATABASE_URL": self.app_url,
               "HC_TEST_ADMIN_DATABASE_URL": self.admin_url}
        load(env)
        with self.admin.engine.connect() as c:
            return [r[0] for r in c.execute(text("SELECT id FROM allergens ORDER BY id"))]


    def setup_cycle(self, **policies) -> dict:
        """يحمّل القواعد والأدوية والإعدادات الوهمية لدورة الدواء (بيئة test فقط)."""
        from load_test_fixtures import load_medication_cycle
        env = {"HC_ENV": "test", "HC_TEST_DATABASE_URL": self.app_url,
               "HC_TEST_ADMIN_DATABASE_URL": self.admin_url, "HC_TEST_AUDIT_HMAC_KEY": AUDIT_KEY.decode()}
        self.add_fake_allergens()
        return load_medication_cycle(env, policies={k: str(v) for k, v in policies.items()})

    def ref(self) -> dict:
        """أسماء العناصر الوهمية ← معرّفاتها."""
        with self.admin.engine.connect() as c:
            out = {}
            for table, col in (("medications", "name"), ("allergens", "name"), ("frequencies", "code"),
                               ("not_given_reasons", "code")):
                out.update({r[0]: r[1] for r in c.execute(text(f"SELECT {col}, id FROM {table}"))})
            return out


def _pg_url(user: str, db: str) -> str:
    u = make_url(PG_SUPER)
    return str(u.set(username=user, database=db).render_as_string(hide_password=False))


@pytest.fixture(scope="session")
def pg_roles():
    if not PG_SUPER:
        return None
    eng = create_engine(PG_SUPER, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        for role in ("hc_owner", "hc_app"):
            if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).first():
                c.exec_driver_sql(f'CREATE ROLE "{role}" LOGIN')
    eng.dispose()
    return True


def make_sqlite_db(tmp_path, name="hc_test.db", env="test") -> TestDB:
    url = f"sqlite:///{tmp_path / name}"
    eng = make_engine(url)
    init_database(eng, env)
    run_sql_script(eng, PROBE_SQL["sqlite"])
    key, pw = creds_for(env)
    ctx = Ctx(engine=eng, hmac_key=key, env=env)
    return TestDB("sqlite", ctx, ctx, url, url, password=pw)


def create_pg_db(env="test") -> TestDB:
    name = f"hc_{uuid.uuid4().hex[:10]}_test"
    sup = create_engine(PG_SUPER, isolation_level="AUTOCOMMIT")
    with sup.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE "{name}" OWNER hc_owner')
    sup.dispose()
    admin_url, app_url = _pg_url("hc_owner", name), _pg_url("hc_app", name)
    admin_eng = make_engine(admin_url)
    init_database(admin_eng, env, app_role="hc_app")
    run_sql_script(admin_eng, PROBE_SQL["postgresql"])
    grant_app_role(admin_eng, "hc_app", {**APP_GRANTS, "probe_items": "SELECT, UPDATE (id)", "probe_claims": "SELECT, INSERT"})
    key, pw = creds_for(env)
    return TestDB("postgresql", Ctx(make_engine(app_url), key, env),
                  Ctx(admin_eng, key, env), app_url, admin_url, name, password=pw)


def drop_pg_db(name: str) -> None:
    sup = create_engine(PG_SUPER, isolation_level="AUTOCOMMIT")
    with sup.connect() as c:
        c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    sup.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def tdb(request, tmp_path, pg_roles):
    if request.param == "sqlite":
        db = make_sqlite_db(tmp_path)
        yield db
        db.app.engine.dispose()
        return
    if not PG_SUPER:
        pytest.skip("PostgreSQL غير متاح: HC_PG_TEST_SUPERUSER_URL غير مضبوط")
    db = create_pg_db()
    yield db
    db.app.engine.dispose()
    db.admin.engine.dispose()
    drop_pg_db(db.db_name)
