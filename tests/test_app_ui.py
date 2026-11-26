"""UI: اختبار دخان للواجهة عبر Streamlit AppTest (SQLite فقط).
يتأكد أن الواجهة تمر بدوال الخادم: الدخول، إضافة مريض، ورفض دور آخر.
"""
from streamlit.testing.v1 import AppTest

from conftest import AUDIT_KEY, PASSWORD, ROOT, make_sqlite_db


def _app(db):
    import streamlit as st
    st.cache_resource.clear()  # كل اختبار بقاعدته الخاصة؛ لا نعيد استخدام اتصال اختبار سابق
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.secrets["HC_ENV"] = "test"
    at.secrets["HC_TEST_DATABASE_URL"] = db.app_url
    at.secrets["HC_TEST_AUDIT_HMAC_KEY"] = AUDIT_KEY.decode()
    at.secrets["HC_DISPLAY_TZ"] = "Asia/Aden"
    return at


def _login(at, username, password=PASSWORD):
    at.run()
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button[0].click().run()
    return at


def test_UI1_login_and_register_patient(tmp_path):
    db = make_sqlite_db(tmp_path)
    db.user("reg1", "registration")
    at = _login(_app(db), "reg1")
    assert not at.exception, at.exception
    assert any("موظف التسجيل" in m.value for m in at.markdown)
    [r for r in at.radio if r.label == "القسم"][0].set_value("إضافة مريض").run()
    name_box = [t for t in at.text_input if t.label.startswith("الاسم الافتراضي")][0]
    age_box = [t for t in at.text_input if t.label.startswith("العمر (18")][0]
    name_box.input("مريض واجهة")
    age_box.input("45")
    [r for r in at.radio if r.label == "حالة الحساسية"][0].set_value("none_known")
    [b for b in at.button if b.label == "حفظ المريض"][0].click().run()
    assert not at.exception, at.exception
    assert any("HC-0001" in s.value for s in at.success)
    # خطأ تحقق يبقى ظاهرًا في القسم نفسه، ولا يُحفظ شيء
    [t for t in at.text_input if t.label.startswith("الاسم الافتراضي")][0].input("قاصر")
    [t for t in at.text_input if t.label.startswith("العمر (18")][0].input("16")
    [b for b in at.button if b.label == "حفظ المريض"][0].click().run()
    assert any("18" in e.value for e in at.error)
    assert db.count("patients") == 1
    assert db.count("patients") == 1


def test_UI2_bad_login_shows_error_and_wrong_role_cannot_see_forms(tmp_path):
    db = make_sqlite_db(tmp_path)
    db.user("nurse1", "nurse")
    at = _login(_app(db), "nurse1", "wrong-password-000")
    assert any("غير صحيحة" in e.value for e in at.error)
    at = _login(_app(db), "nurse1")
    assert not [b for b in at.button if b.label == "حفظ المريض"]
    # عُدّل في المرحلة الثانية: كانت شاشة الممرض «قيد البناء»، والآن تظهر مساحة عمله الفعلية
    assert [r for r in at.radio if r.label == "القسم"][0].options == ["جدول الإعطاء", "الوصفات السارية"]


def test_UI3_wrong_env_db_refuses_to_start(tmp_path):
    db = make_sqlite_db(tmp_path, env="dev")
    at = _app(db)
    at.run()
    assert any("لا يمكن تشغيل التطبيق" in e.value for e in at.error)
