"""K: ثوابت الاختبار المنشورة (كلمات سر ومفاتيح) مرفوضة في بيئة العرض demo."""
import ast
import os
import subprocess
import sys
import uuid

import pytest

import conftest
from conftest import AUDIT_KEY, DEMO_AUDIT_KEY, PASSWORD, PG_SUPER, ROOT, make_sqlite_db
from hc import admin_users
from hc.config import load_config
from hc.errors import ConfigError, ValidationFailed
from hc.known_test_secrets import forbidden_here, is_known_test_secret

DEMO_BASE = {"HC_ENV": "demo", "HC_DISPLAY_TZ": "Asia/Aden", "HC_DEMO_DATABASE_URL": "postgresql+psycopg://u@h/d"}


def test_K1_test_audit_key_refused_as_demo_key():
    with pytest.raises(ConfigError, match="الاختبار"):
        load_config({**DEMO_BASE, "HC_DEMO_AUDIT_HMAC_KEY": AUDIT_KEY.decode()})
    with pytest.raises(ConfigError):   # كذلك مثال ملف الإعدادات إن لُصق حرفيًا
        load_config({**DEMO_BASE, "HC_DEMO_AUDIT_HMAC_KEY": "ضعي-هنا-مفتاحًا-عشوائيًا-لا-يقل-عن-32-حرفًا"})
    assert load_config({**DEMO_BASE, "HC_DEMO_AUDIT_HMAC_KEY": DEMO_AUDIT_KEY.decode()}).env == "demo"
    # البيئات المحلية غير مشمولة (الاختبارات نفسها تستخدم هذه القيم)
    assert load_config({"HC_ENV": "test", "HC_DISPLAY_TZ": "Asia/Aden", "HC_TEST_DATABASE_URL": "sqlite:///x.db",
                        "HC_TEST_AUDIT_HMAC_KEY": AUDIT_KEY.decode()}).env == "test"


def test_K2_test_passwords_refused_for_demo_accounts(tmp_path):
    db = make_sqlite_db(tmp_path, name="demo.db", env="demo")
    for pw in (PASSWORD, "First-Account-Pass-789", "Brand-New-Pass-456"):
        with pytest.raises(ValidationFailed) as ei:
            admin_users.create_user(db.admin, operator="pytest", username="rn.x", full_name="ممرض", role="nurse",
                                    password=pw)
        assert ei.value.code == "known_test_secret"
    assert db.count("users") == 0
    admin_users.create_user(db.admin, operator="pytest", username="rn.x", full_name="ممرض", role="nurse",
                            password=conftest.DEMO_PASSWORD)
    with pytest.raises(ValidationFailed) as ei:
        admin_users.reset_password(db.admin, operator="pytest", username="rn.x", new_password=PASSWORD)
    assert ei.value.code == "known_test_secret"
    assert db.count("audit_log", "action='admin.user_create' AND outcome='validation_error'") == 3


def test_K3_test_passwords_still_allowed_in_test_env(tmp_path):
    db = make_sqlite_db(tmp_path)
    admin_users.create_user(db.admin, operator="pytest", username="rn.y", full_name="ممرض", role="nurse",
                            password=PASSWORD)
    assert db.count("users") == 1


def test_K4_test_anchor_key_refused_in_demo(tmp_path):
    db = make_sqlite_db(tmp_path, name="demo.db", env="demo")
    from test_anchor import ANCHOR_KEY
    env = {k: v for k, v in os.environ.items() if not k.startswith("HC_")}
    env.update({"HC_ENV": "demo", "HC_DISPLAY_TZ": "Asia/Aden", "HC_DEMO_DATABASE_URL": "postgresql+psycopg://u@h/d",
                "HC_DEMO_ADMIN_DATABASE_URL": db.admin_url, "HC_DEMO_AUDIT_HMAC_KEY": DEMO_AUDIT_KEY.decode(),
                "HC_ANCHOR_KEY": ANCHOR_KEY.decode()})
    out = tmp_path / "team" / "a.json"
    out.parent.mkdir()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_audit.py"), "export-anchor",
                        "--out", str(out), "--operator", "pytest"], env=env, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode != 0 and "الاختبار" in r.stderr
    assert not out.exists()


@pytest.mark.skipif(not PG_SUPER, reason="يتطلب PostgreSQL")
def test_K5_test_password_refused_for_app_role_in_demo(pg_roles):
    from create_app_role import create_role
    role = f"hc_app_{uuid.uuid4().hex[:8]}"
    with pytest.raises(ValueError, match="الاختبار"):
        create_role(PG_SUPER, role, PASSWORD, env="demo")
    from sqlalchemy import create_engine, text
    eng = create_engine(PG_SUPER)
    with eng.connect() as c:
        assert c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first() is None
    eng.dispose()


def _secret_literals():
    """كل نص ثابت (12 حرفًا فأكثر) يُسند إلى اسم يدل على سر في ملفات tests/."""
    found = []
    for f in (ROOT / "tests").glob("*.py"):
        tree = ast.parse(f.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, (str, bytes)):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                val = node.value.value
                if any(k in n.lower() for n in names for k in ("key", "password", "secret", "pw")) and len(val) >= 12:
                    found.append((f.name, names[0], val))
    return found


def test_K6_every_secret_constant_in_tests_is_guarded():
    lits = _secret_literals()
    assert len(lits) >= 6, lits     # فحص أن الماسح يجد الثوابت فعلًا
    missing = [(f, n) for f, n, v in lits if not is_known_test_secret(v)]
    assert not missing, f"ثوابت سرية في الاختبارات غير مدرجة في قائمة الحماية: {missing}"
    for _, _, v in lits:
        assert forbidden_here(v, "demo") and not forbidden_here(v, "test") and not forbidden_here(v, "dev")


def test_K7_guard_module_stores_hashes_not_values():
    src = (ROOT / "hc" / "known_test_secrets.py").read_text("utf-8")
    for _, _, v in _secret_literals():
        text_v = v.decode() if isinstance(v, bytes) else v
        assert text_v not in src
