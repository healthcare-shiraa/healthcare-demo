"""D: أمان سير العمل الإداري للنشر (GitHub Actions) وإنشاء حساب التطبيق."""
import os
import re
import subprocess
import uuid

import pytest
import yaml
from sqlalchemy import create_engine, text

from conftest import PG_SUPER, ROOT

WF = ROOT / ".github" / "workflows" / "demo-admin.yml"


def _steps():
    wf = yaml.safe_load(WF.read_text("utf-8"))
    return wf, wf["jobs"]["admin"]["steps"]


def test_D1_no_expression_inside_run_commands():
    """لا يُدرَج أي ${{ … }} داخل نص run: المدخلات والأسرار تُمرَّر كمتغيرات بيئة فقط."""
    _, steps = _steps()
    for s in steps:
        if "run" in s:
            assert "${{" not in s["run"], f"تعبير داخل أوامر الخطوة {s.get('name')}"


def test_D2_validation_step_runs_first_and_rejects_injection(tmp_path):
    wf, steps = _steps()
    assert steps[0]["name"] == "validate-inputs"
    assert wf["permissions"] == {"contents": "read"}
    script = steps[0]["run"]
    marker = tmp_path / "pwned"

    def run(op, action="verify-audit", user=""):
        env = {**os.environ, "IN_OPERATOR": op, "IN_ACTION": action, "IN_USERNAME": user}
        return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True).returncode

    attacks = [f'x"; touch {marker}; echo "', f"$(touch {marker})", f"`touch {marker}`", "a\nb", "", "a" * 61,
               "x;id", "x|id"]
    for op in attacks:
        assert run(op) != 0, repr(op)
    for user in (f"x; touch {marker}", "Admin", "a", "../etc", "ab$(id)"):
        assert run("داليا", "deactivate-user", user) != 0, repr(user)
    assert not marker.exists()
    assert run("داليا") == 0 and run("Dalia S.") == 0
    assert run("داليا", "deactivate-user", "rn.demo") == 0


def test_D2b_inputs_only_used_quoted_env_vars():
    _, steps = _steps()
    for s in steps:
        for var in re.findall(r"\$IN_[A-Z]+", s.get("run", "")):
            assert f'"{var}"' in s["run"], f"{var} غير محاط بعلامتي تنصيص في {s.get('name')}"


def _tcp_login(role: str, password: str):
    """دخول حقيقي عبر الشبكة المحلية (127.0.0.1) حيث يتحقق الخادم من كلمة السر (scram-sha-256)."""
    import psycopg
    from sqlalchemy.engine import make_url
    port = make_url(PG_SUPER).query.get("port", "5432")
    with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user=role, password=password,
                         connect_timeout=5) as c:
        return c.execute("SELECT current_user").fetchone()[0]


@pytest.mark.skipif(not PG_SUPER, reason="يتطلب PostgreSQL")
def test_D3_create_app_role_safe_and_limited(pg_roles):
    import psycopg
    from create_app_role import create_role
    role = f"hc_app_{uuid.uuid4().hex[:8]}"
    password = "Ab'c;DROP ROLE x;--123"   # علامة تنصيص وفاصلة منقوطة: يجب أن تُعامل نصًا لا أمرًا
    sup = create_engine(PG_SUPER, isolation_level="AUTOCOMMIT")
    try:
        assert create_role(PG_SUPER, role, password, env="test") is True
        assert create_role(PG_SUPER, role, "another-Password-1", env="test") is False   # لا يتغير إن كان موجودًا
        with sup.connect() as c:
            r = c.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles"
                               " WHERE rolname = :r"), {"r": role}).one()
            assert tuple(r) == (False, False, False, True)
        # دخول حقيقي: كلمة السر الخاطئة يجب أن تُرفض أولًا (وإلا فالخادم لا يتحقق من كلمات السر)
        try:
            _tcp_login(role, "definitely-Wrong-Password-9")
            pytest.skip("الخادم المحلي لا يتحقق من كلمات السر عبر الشبكة؛ اختبار الدخول بلا معنى هنا")
        except psycopg.OperationalError as e:
            assert "password authentication failed" in str(e)
        assert _tcp_login(role, password) == role   # كلمة السر بعلامة التنصيص حُفظت حرفيًا وتعمل
        # كلمة السر الثانية لم تُطبَّق (الحساب الموجود لا يتغير)
        with pytest.raises(psycopg.OperationalError):
            _tcp_login(role, "another-Password-1")
        for bad_role in ("Bad-Name", "x; DROP", ""):
            with pytest.raises(ValueError):
                create_role(PG_SUPER, bad_role, password, env="test")
        with pytest.raises(ValueError):
            create_role(PG_SUPER, role + "z", "short", env="test")
    finally:
        with sup.connect() as c:
            c.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        sup.dispose()
