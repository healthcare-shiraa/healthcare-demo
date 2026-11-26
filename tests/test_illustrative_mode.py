"""I: القواعد التوضيحية لنسخة العرض — مسموحة في demo فقط بإعداد صريح، ومنفصلة تمامًا عن قواعد الاختبار."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import text

from conftest import AUDIT_KEY, DEMO_AUDIT_KEY, PG_SUPER, ROOT, create_pg_db, drop_pg_db, make_sqlite_db
from hc import patients as P
from hc import prescriptions as RX
from hc.audit import Ctx
from hc.config import load_config
from hc.db import db_now
from hc.errors import ConfigError
from hc.reference import ConfigMissing, set_policy
from hc.rules import RulesetError, load_ruleset
from hc.timefmt import parse_utc

ILL = json.loads((ROOT / "demo" / "illustrative_ruleset.json").read_text("utf-8"))
ILL_POL = {k: v for k, v in json.loads((ROOT / "demo" / "illustrative_policies.json").read_text("utf-8")).items()
           if not k.startswith("_")}
FIX = json.loads((ROOT / "fixtures" / "test_ruleset.json").read_text("utf-8"))


def demo_db(tmp_path, allow=True):
    db = make_sqlite_db(tmp_path, name="demo.db", env="demo")
    for c in (db.admin, db.app):
        c.env, c.allow_illustrative = "demo", allow
    return db


def test_I1_illustrative_refused_in_test_env(tmp_path):
    db = make_sqlite_db(tmp_path)                      # بيئة test
    for allow in (False, True):
        ctx = Ctx(db.admin.engine, AUDIT_KEY, "test", allow_illustrative=allow)
        with pytest.raises(RulesetError):
            load_ruleset(ctx, ILL, operator="pytest")
    assert db.count("ruleset_versions") == 0


def test_I2_illustrative_refused_in_demo_without_flag(tmp_path):
    db = demo_db(tmp_path, allow=False)
    with pytest.raises(RulesetError):
        load_ruleset(db.admin, ILL, operator="pytest")
    with pytest.raises(Exception):
        set_policy(db.admin, operator="pytest", key="max_treatment_days", value="7", synthetic=True)
    assert db.count("ruleset_versions") == 0 and db.count("policy_settings") == 0


def test_I3_test_fixtures_refused_in_demo_even_with_flag(tmp_path):
    db = demo_db(tmp_path, allow=True)
    with pytest.raises(RulesetError):
        load_ruleset(db.admin, FIX, operator="pytest")
    assert db.count("ruleset_versions") == 0


def test_I4_illustrative_loads_in_demo_with_flag_and_is_labelled(tmp_path):
    db = demo_db(tmp_path, allow=True)
    s = load_ruleset(db.admin, ILL, operator="pytest")
    assert s["kind"] == "illustrative" and len(s["loaded"]) == 7 and not s["incomplete"]
    with db.admin.engine.connect() as c:
        assert c.execute(text("SELECT kind, is_synthetic FROM ruleset_versions")).one() == ("illustrative", 1)
        assert c.execute(text("SELECT count(*) FROM medications WHERE is_synthetic = 0")).scalar_one() == 0


def test_I5_separation_no_shared_names_or_codes():
    def names(d):
        return ({r["code"] for r in d["rules"]} | set(d["allergens"]) | {m["name"] for m in d["medications"]}
                | {f["code"] for f in d["frequencies"]} | {r["code"] for r in d["not_given_reasons"]})
    assert names(ILL).isdisjoint(names(FIX))
    assert ILL["kind"] == "illustrative" and "synthetic" not in ILL
    assert all("توضيحي" in r["alert_text"] and "غير معتمد" in r["alert_text"] for r in ILL["rules"])


def _demo_world(db):
    load_ruleset(db.admin, ILL, operator="pytest")
    for k, v in ILL_POL.items():
        set_policy(db.admin, operator="pytest", key=k, value=v, synthetic=True)
    ref = db.ref()
    reg, doc = db.session("reg1", "registration"), db.session("doc1", "doctor")
    p = P.create_patient(db.app, reg, full_name="مريض توضيحي", age=40, allergy_status="has_allergies",
                         allergen_ids=[ref["حساسية-توضيحية-١"]])
    with db.app.engine.connect() as c:
        start = parse_utc(db_now(c)).replace(second=0, microsecond=0) + timedelta(minutes=5)
    return ref, doc, p, start


def test_I6_runtime_flag_required_for_prescribing(tmp_path):
    db = demo_db(tmp_path, allow=True)
    ref, doc, p, start = _demo_world(db)
    kw = dict(patient_id=p["id"], medication_id=ref["دواء-توضيحي-١"], dose="10",
              frequency_id=ref["demo-q8h"], start_at=start, duration_days=1)
    db.app.allow_illustrative = False                  # أُطفئ الإعداد بعد التحميل
    with pytest.raises(ConfigMissing) as ei:
        RX.create_prescription(db.app, doc, **kw)
    assert ei.value.code == "ruleset_kind_not_allowed"
    db.app.allow_illustrative = True
    r = RX.create_prescription(db.app, doc, **kw)
    assert [a["code"] for a in r["alerts"]] == ["D-R1"]


def test_I7_illustrative_ruleset_unusable_in_test_env(tmp_path):
    db = demo_db(tmp_path, allow=True)
    ref, doc, p, start = _demo_world(db)
    test_ctx = Ctx(db.app.engine, AUDIT_KEY, "test")
    with pytest.raises(ConfigMissing):
        RX.create_prescription(test_ctx, doc, patient_id=p["id"], medication_id=ref["دواء-توضيحي-١"], dose="10",
                               frequency_id=ref["demo-q8h"], start_at=start, duration_days=1)


def test_I8_config_flag_rules():
    base = {"HC_DISPLAY_TZ": "Asia/Aden", "HC_DEMO_AUDIT_HMAC_KEY": DEMO_AUDIT_KEY.decode(),
            "HC_DEMO_DATABASE_URL": "postgresql+psycopg://u@h/d"}
    assert load_config({**base, "HC_ENV": "demo"}).allow_illustrative is False
    assert load_config({**base, "HC_ENV": "demo", "HC_DEMO_ALLOW_ILLUSTRATIVE_RULES": "true"}).allow_illustrative
    for bad in ("TRUE", "yes", "1", ""):
        with pytest.raises(ConfigError):
            load_config({**base, "HC_ENV": "demo", "HC_DEMO_ALLOW_ILLUSTRATIVE_RULES": bad})
    with pytest.raises(ConfigError):   # الإعداد مرفوض خارج demo
        load_config({"HC_ENV": "test", "HC_DISPLAY_TZ": "Asia/Aden", "HC_TEST_AUDIT_HMAC_KEY": "k" * 40,
                     "HC_TEST_DATABASE_URL": "sqlite:///x.db", "HC_DEMO_ALLOW_ILLUSTRATIVE_RULES": "true"})


@pytest.mark.skipif(not PG_SUPER, reason="يتطلب PostgreSQL (بيئة demo لا تقبل SQLite)")
def test_I9_warning_banner_on_every_page_in_demo(pg_roles):
    """التحذير يظهر في صفحة الدخول وكل صفحات الأدوار الأربعة."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    db = create_pg_db(env="demo")
    try:
        for c in (db.admin, db.app):
            c.allow_illustrative = True
        _demo_world(db)
        db.user("ph1", "pharmacist")
        db.user("nu1", "nurse")
        pages = {"reg1": ["المرضى", "إضافة مريض", "تعديل مريض"],
                 "doc1": ["لوحة الطبيب", "وصفة جديدة", "وصفاتي", "الإحالات"],
                 "ph1": ["قائمة المراجعة", "المراجعات السابقة", "الإحالات"], "nu1": ["جدول الإعطاء", "الوصفات السارية"]}
        warn = "لا يُستخدم هذا الموقع لاتخاذ أي قرار علاجي حقيقي"
        for user, plist in pages.items():
            st.cache_resource.clear()
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
            for k, v in {"HC_ENV": "demo", "HC_DEMO_DATABASE_URL": db.app_url, "HC_DISPLAY_TZ": "Asia/Aden",
                         "HC_DEMO_AUDIT_HMAC_KEY": DEMO_AUDIT_KEY.decode(),
                         "HC_DEMO_ALLOW_ILLUSTRATIVE_RULES": "true"}.items():
                at.secrets[k] = v
            at.run()
            assert any(warn in m.value for m in at.markdown), "التحذير غائب عن صفحة الدخول"
            [t for t in at.text_input if t.label == "اسم المستخدم"][0].input(user)
            [t for t in at.text_input if t.label == "كلمة السر"][0].input(db.password)
            [b for b in at.button if b.label == "دخول"][0].click().run()
            for pg in plist:
                [r for r in at.radio if r.label == "القسم"][0].set_value(pg).run()
                assert not at.exception, (user, pg, at.exception)
                assert any(warn in m.value for m in at.markdown), (user, pg)
    finally:
        db.app.engine.dispose()
        db.admin.engine.dispose()
        drop_pg_db(db.db_name)
