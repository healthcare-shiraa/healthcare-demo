"""أدوات مشتركة للسكربتات الإدارية (تعمل خارج التطبيق)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hc.audit import Ctx  # noqa: E402
from hc.config import load_config  # noqa: E402
from hc.db import check_db_env, make_engine  # noqa: E402


def admin_ctx(check_env: bool = True) -> Ctx:
    """سياق بحساب المالك. في PostgreSQL يجب تحديد HC_<ENV>_ADMIN_DATABASE_URL."""
    cfg = load_config(os.environ, for_app=False)
    url = cfg.admin_database_url
    if url is None:
        if cfg.database_url.startswith("sqlite"):
            url = cfg.database_url  # SQLite لا يملك حسابات منفصلة
        else:
            sys.exit(f"المتغير HC_{cfg.env.upper()}_ADMIN_DATABASE_URL مطلوب")
    engine = make_engine(url)
    if check_env:
        check_db_env(engine, cfg.env)
    return Ctx(engine=engine, hmac_key=cfg.audit_hmac_key, env=cfg.env, allow_illustrative=cfg.allow_illustrative)
