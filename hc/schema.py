"""تهيئة قاعدة البيانات: إنشاء الجداول، تسجيل اسم البيئة، وصلاحيات حساب التطبيق.

يُستدعى من scripts/init_db.py بحساب المالك فقط.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .db import read_db_env
from .errors import EnvironmentMismatch

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"

# صلاحيات حساب التطبيق في PostgreSQL. لا UPDATE/DELETE على السجل،
# ولا INSERT/UPDATE على المستخدمين (لا تسجيل ذاتي ولا رفع صلاحيات من التطبيق).
APP_GRANTS = {
    "meta": "SELECT",
    "counters": "SELECT, UPDATE",
    "users": "SELECT",
    "patients": "SELECT, INSERT, UPDATE",
    "allergens": "SELECT",
    # لا DELETE: التاريخ يُحفظ. UPDATE على حقول الإزالة فقط (والمشغّل يسمح بها مرة واحدة)
    "patient_allergies": "SELECT, INSERT, UPDATE (removed_by, removed_at, removal_reason)",
    "audit_log": "SELECT, INSERT",
    # دورة الدواء: المراجع والقواعد قراءة فقط (تُحمَّل بسكربت المالك)
    "medications": "SELECT", "frequencies": "SELECT", "medication_frequencies": "SELECT",
    "not_given_reasons": "SELECT", "policy_settings": "SELECT", "ruleset_versions": "SELECT",
    "rule_versions": "SELECT", "rule_conditions": "SELECT", "rule_resolution_requirements": "SELECT",
    "incomplete_rules": "SELECT",
    # الوصفة: تعديل حقل الحالة فقط (والمشغّل يقيّد الانتقالات). UPDATE لازم أيضًا لقفل FOR UPDATE.
    "prescriptions": "SELECT, INSERT, UPDATE (status)",
    "prescription_stops": "SELECT, INSERT",
    "alerts": "SELECT, INSERT", "alert_resolutions": "SELECT, INSERT",
    "alert_resolution_items": "SELECT, INSERT", "alert_acknowledgments": "SELECT, INSERT",
    "pharmacist_reviews": "SELECT, INSERT",
    # UPDATE (id) فقط ليسمح بقفل FOR UPDATE؛ المشغّل يرفض أي تعديل فعلي
    "scheduled_doses": "SELECT, INSERT, UPDATE (id)",
    "administrations": "SELECT, INSERT",
    "referrals": "SELECT, INSERT", "referral_closures": "SELECT, INSERT",
}

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def run_sql_script(engine: Engine, script: str) -> None:
    if engine.dialect.name == "sqlite":
        raw = engine.raw_connection()
        try:
            raw.driver_connection.executescript(script)
        finally:
            raw.close()
    else:
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute(script)  # بلا معاملات: لا تُفسَّر علامة % كموضع متغير
            raw.commit()
        finally:
            raw.close()


def init_database(engine: Engine, env: str, app_role: str | None = None) -> None:
    existing = read_db_env(engine)
    if existing is not None and existing != env:
        raise EnvironmentMismatch(f"القاعدة مهيأة مسبقًا لبيئة '{existing}'")

    dialect = engine.dialect.name
    script = (SCHEMA_DIR / ("sqlite.sql" if dialect == "sqlite" else "postgres.sql")).read_text("utf-8")
    run_sql_script(engine, script)

    if existing is None:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO meta(key, value) VALUES ('env', :e)"), {"e": env})

    if dialect == "postgresql":
        if not app_role or not _ROLE_RE.match(app_role):
            raise ValueError("يجب تحديد اسم حساب التطبيق في PostgreSQL")
        grant_app_role(engine, app_role, APP_GRANTS)


def grant_app_role(engine: Engine, app_role: str, grants: dict[str, str]) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{app_role}"')
        for table, privs in grants.items():
            conn.exec_driver_sql(f'GRANT {privs} ON "{table}" TO "{app_role}"')
        conn.exec_driver_sql(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')
