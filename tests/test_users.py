"""U: المستخدمون، الصلاحيات، الجلسات، الحساب الأول."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from conftest import AUDIT_KEY, PASSWORD, ROOT, make_sqlite_db
from hc import admin_users
from hc import patients as P
from hc.auth import login
from hc.errors import AuthenticationFailed, PermissionDenied, ValidationFailed


def test_U1_login_ok_and_bad(tdb):
    tdb.user("doc1", "doctor")
    s = login(tdb.app, "doc1", PASSWORD)
    assert s.role == "doctor"
    with pytest.raises(AuthenticationFailed) as ei:
        login(tdb.app, "doc1", "wrong-password-xyz")
    assert ei.value.audit_persisted is True
    with pytest.raises(AuthenticationFailed):
        login(tdb.app, "nobody", PASSWORD)
    logins = tdb.audit_rows(action="auth.login")
    assert [r["outcome"] for r in logins] == ["success", "denied", "denied"]
    all_text = " ".join(r["details"] for r in tdb.audit_rows())
    assert PASSWORD not in all_text and "wrong-password-xyz" not in all_text


def test_U2_deactivated_cannot_login(tdb):
    tdb.user("nurse1", "nurse")
    admin_users.deactivate_user(tdb.admin, operator="pytest", username="nurse1")
    with pytest.raises(AuthenticationFailed):
        login(tdb.app, "nurse1", PASSWORD)


def test_U3_reset_password(tdb):
    s_old = tdb.session("ph1", "pharmacist")
    new_pw = "Brand-New-Pass-456"
    admin_users.reset_password(tdb.admin, operator="pytest", username="ph1", new_password=new_pw)
    with pytest.raises(AuthenticationFailed):
        login(tdb.app, "ph1", PASSWORD)
    s_new = login(tdb.app, "ph1", new_pw)
    assert s_new.credential_version == s_old.credential_version + 1
    with pytest.raises(PermissionDenied) as ei:  # الجلسة القديمة أصبحت غير صالحة
        P.list_patients(tdb.app, s_old)
    assert ei.value.code == "stale_session"
    P.list_patients(tdb.app, s_new)
    all_text = " ".join(r["details"] for r in tdb.audit_rows())
    assert new_pw not in all_text


def test_U3b_short_password_rejected(tdb):
    with pytest.raises(ValidationFailed):
        admin_users.create_user(tdb.admin, operator="pytest", username="x1", full_name="x",
                                role="nurse", password="short")
    assert tdb.count("users") == 0


@pytest.mark.parametrize("role", ["doctor", "pharmacist", "nurse"])
def test_U4_only_registration_writes_patients(tdb, role):
    reg = tdb.session("reg1", "registration")
    p = P.create_patient(tdb.app, reg, full_name="مريض", age=30, allergy_status="none_known")
    s = tdb.session("other1", role)
    before = tdb.count("audit_log", "outcome='denied'")
    with pytest.raises(PermissionDenied) as e1:
        P.create_patient(tdb.app, s, full_name="س", age=30, allergy_status="none_known")
    with pytest.raises(PermissionDenied):
        P.update_patient(tdb.app, s, p["id"], expected_version=1, full_name="تغيير", age=40)
    with pytest.raises(PermissionDenied):
        P.set_allergies(tdb.app, s, p["id"], expected_version=1, allergy_status="not_recorded")
    assert e1.value.audit_persisted is True
    assert tdb.count("patients") == 1
    assert P.get_patient(tdb.app, reg, p["id"])["full_name"] == "مريض"
    assert tdb.count("audit_log", "outcome='denied'") == before + 3
    # القراءة مسموحة لكل الأدوار الأربعة
    assert len(P.list_patients(tdb.app, s)) == 1


def test_U4b_no_session_denied_and_audited(tdb):
    with pytest.raises(PermissionDenied):
        P.list_patients(tdb.app, None)
    assert tdb.count("audit_log", "outcome='denied' AND actor_type='anonymous'") == 1


def test_U5_deactivated_mid_session_rejected_immediately(tdb):
    s = tdb.session("reg1", "registration")
    P.create_patient(tdb.app, s, full_name="أول", age=30, allergy_status="none_known")
    admin_users.deactivate_user(tdb.admin, operator="pytest", username="reg1")
    with pytest.raises(PermissionDenied) as ei:
        P.create_patient(tdb.app, s, full_name="ثانٍ", age=30, allergy_status="none_known")
    assert ei.value.code in ("inactive_or_missing", "stale_session")
    assert tdb.count("patients") == 1
    with pytest.raises(PermissionDenied):
        P.list_patients(tdb.app, s)


def test_U6_role_cannot_be_changed_even_by_owner(tdb):
    tdb.user("nurse1", "nurse")
    with pytest.raises(DBAPIError):
        with tdb.admin.engine.begin() as c:
            c.execute(text("UPDATE users SET role='doctor' WHERE username='nurse1'"))
    with pytest.raises(DBAPIError):
        with tdb.admin.engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE username='nurse1'"))


def test_U6b_app_db_account_cannot_create_or_promote_users(tdb):
    if tdb.kind != "postgresql":
        pytest.skip("SQLite لا يملك حسابات قاعدة بيانات منفصلة؛ الحماية هنا في الكود فقط (U6c)")
    tdb.user("nurse1", "nurse")
    with pytest.raises(DBAPIError, match="permission denied"):
        with tdb.app.engine.begin() as c:
            c.execute(text("INSERT INTO users (username, password_hash, full_name, role)"
                           " VALUES ('evil','x','x','doctor')"))
    with pytest.raises(DBAPIError, match="permission denied"):
        with tdb.app.engine.begin() as c:
            c.execute(text("UPDATE users SET is_active=true WHERE username='nurse1'"))
    with pytest.raises(DBAPIError, match="permission denied"):
        with tdb.app.engine.begin() as c:
            c.execute(text("UPDATE audit_log SET details='{}'"))


def test_U6c_app_code_has_no_user_creation_path():
    app_files = [ROOT / "app.py"] + [p for p in (ROOT / "hc").glob("*.py") if p.name != "admin_users.py"]
    pat = re.compile(r"(INSERT\s+INTO\s+users|UPDATE\s+users)", re.I)
    for f in app_files:
        src = f.read_text("utf-8")
        assert not pat.search(src), f"{f.name} يحتوي كتابة على جدول users"
        assert not re.search(r"^\s*(from\s+\S*admin_users|import\s+\S*admin_users|from\s+\S+\s+import\s+.*\badmin_users\b)", src, re.M), \
            f"{f.name} يستورد admin_users"


def _run_script(args, env_extra, stdin=""):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HC_")}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "manage_users.py"), *args],
                          input=stdin, capture_output=True, text=True, env=env, timeout=60)


def test_U7_first_account_via_script_no_default_password(tmp_path):
    db = make_sqlite_db(tmp_path)
    env = {"HC_ENV": "test", "HC_TEST_DATABASE_URL": db.app_url,
           "HC_TEST_AUDIT_HMAC_KEY": AUDIT_KEY.decode(), "HC_DISPLAY_TZ": "Asia/Aden"}
    assert db.count("users") == 0
    secret = "First-Account-Pass-789"
    r = _run_script(["create", "--username", "reg.first", "--full-name", "موظف تسجيل",
                     "--role", "registration", "--operator", "داليا", "--password-stdin"], env, secret + "\n")
    assert r.returncode == 0, r.stderr
    assert secret not in r.stdout + r.stderr
    assert login(db.app, "reg.first", secret).role == "registration"
    row = db.audit_rows(action="admin.user_create")[0]
    assert row["actor_type"] == "script" and row["operator_name"] == "داليا"
    assert secret not in row["details"]
    # بلا كلمة سر (إدخال فارغ) يُرفض: لا توجد قيمة افتراضية
    r2 = _run_script(["create", "--username", "nurse.x", "--full-name", "ممرض", "--role", "nurse",
                      "--operator", "داليا", "--password-stdin"], env, "\n")
    assert r2.returncode == 2
    # بلا اسم منفّذ يُرفض
    r3 = _run_script(["create", "--username", "nurse.y", "--full-name", "ممرض", "--role", "nurse",
                      "--password-stdin"], env, secret + "\n")
    assert r3.returncode != 0
    assert db.count("users") == 1
    # السكربت يرفض العمل على قاعدة بيئة أخرى
    other = make_sqlite_db(tmp_path, name="dev.db", env="dev")
    r4 = _run_script(["deactivate", "--username", "reg.first", "--operator", "داليا"],
                     {**env, "HC_TEST_DATABASE_URL": other.app_url})
    assert r4.returncode != 0 and "EnvironmentMismatch" in r4.stderr
