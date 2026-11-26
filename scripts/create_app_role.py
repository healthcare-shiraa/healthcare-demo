"""إنشاء حساب التطبيق في PostgreSQL (صلاحيات محدودة) إن لم يكن موجودًا. يُشغَّل بحساب المالك.

    HC_DEMO_ADMIN_DATABASE_URL=... APP_ROLE_PASSWORD=... python scripts/create_app_role.py --role hc_app

- كلمة السر تُقرأ من متغير البيئة APP_ROLE_PASSWORD فقط (لا من سطر الأوامر)، ولا تُطبع.
- تُبنى جملة SQL بأدوات psycopg الآمنة (Identifier / Literal) لا بلصق النصوص.
- الحساب يُنشأ بلا صلاحيات إدارية؛ الصلاحيات على الجداول تمنحها init_db.py لاحقًا.
"""
import argparse
import os
import re
import sys

from _common import ROOT  # noqa: F401  (يضبط sys.path)

from psycopg import sql
from sqlalchemy import text

from hc.db import make_engine
from hc.known_test_secrets import forbidden_here

ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MIN_PASSWORD_LEN = 12


def create_role(admin_url: str, role: str, password: str, *, env: str) -> bool:
    """يعيد True إذا أُنشئ الحساب، False إذا كان موجودًا مسبقًا."""
    if not ROLE_RE.match(role):
        raise ValueError("اسم حساب غير صالح")
    if forbidden_here(password, env):
        raise ValueError("كلمة السر هذه من ملفات الاختبار المنشورة؛ مرفوضة في بيئة العرض (demo)")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"كلمة سر حساب التطبيق يجب ألا تقل عن {MIN_PASSWORD_LEN} حرفًا")
    eng = make_engine(admin_url)
    try:
        with eng.begin() as c:
            if c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first():
                return False
            raw = c.connection.driver_connection
            stmt = sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password))
            c.exec_driver_sql(stmt.as_string(raw))
            return True
    finally:
        eng.dispose()


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--role", default="hc_app")
    args = p.parse_args(argv)
    env = os.environ.get("HC_ENV", "")
    admin_url = os.environ.get(f"HC_{env.upper()}_ADMIN_DATABASE_URL")
    password = os.environ.get("APP_ROLE_PASSWORD", "")
    if not admin_url:
        print("مرفوض: عنوان حساب المالك غير موجود", file=sys.stderr)
        return 2
    try:
        created = create_role(admin_url, args.role, password, env=env)
    except ValueError as e:
        print(f"مرفوض: {e}", file=sys.stderr)
        return 2
    print(f"أُنشئ حساب التطبيق {args.role}" if created else f"حساب التطبيق {args.role} موجود مسبقًا (لم يتغير)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
