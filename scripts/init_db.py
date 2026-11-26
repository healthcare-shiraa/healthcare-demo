"""تهيئة قاعدة بيانات بيئة ما. يُشغَّل بحساب المالك.

مثال (SQLite للتطوير):
    HC_ENV=dev HC_DEV_DATABASE_URL=sqlite:///hc_dev.db HC_DEV_AUDIT_HMAC_KEY=... \
    HC_DISPLAY_TZ=Asia/Aden python scripts/init_db.py
PostgreSQL: يتطلب HC_<ENV>_ADMIN_DATABASE_URL و --app-role باسم حساب التطبيق.
"""
import argparse
import sys

from _common import admin_ctx  # noqa: F401  (يضبط sys.path)

from hc.schema import init_database


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--app-role", help="اسم حساب التطبيق في PostgreSQL")
    args = p.parse_args()
    ctx = admin_ctx(check_env=False)
    init_database(ctx.engine, ctx.env, app_role=args.app_role)
    print(f"تمت تهيئة قاعدة بيئة {ctx.env}.")


if __name__ == "__main__":
    sys.exit(main())
