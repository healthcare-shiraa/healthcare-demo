"""UI5–UI8: دورة الدواء كاملة من الواجهة (AppTest)، كل دور في جلسة مستقلة. قواعد وأدوية وهمية."""
import pytest
from streamlit.testing.v1 import AppTest

from conftest import AUDIT_KEY, PASSWORD, ROOT, make_sqlite_db
from hc import patients as P
from hc import prescriptions as RX
from hc import review as RV
from hc.audit import verify_chain
from hc.auth import login


def app_as(db, username):
    import streamlit as st
    st.cache_resource.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    for k, v in {"HC_ENV": "test", "HC_TEST_DATABASE_URL": db.app_url,
                 "HC_TEST_AUDIT_HMAC_KEY": AUDIT_KEY.decode(), "HC_DISPLAY_TZ": "Asia/Aden"}.items():
        at.secrets[k] = v
    at.run()
    [t for t in at.text_input if t.label == "اسم المستخدم"][0].input(username)
    [t for t in at.text_input if t.label == "كلمة السر"][0].input(PASSWORD)
    [b for b in at.button if b.label == "دخول"][0].click().run()
    assert not at.exception, at.exception
    return at


def nav(at, page):
    [r for r in at.radio if r.label == "القسم"][0].set_value(page).run()
    assert not at.exception, at.exception
    return at


def by_label(items, prefix):
    return [x for x in items if x.label.startswith(prefix)][0]


def texts(at):
    return " ".join([m.value for m in at.markdown] + [m.value for m in at.success] + [m.value for m in at.error]
                    + [m.value for m in at.caption])


@pytest.fixture
def world(tmp_path):
    db = make_sqlite_db(tmp_path)
    db.setup_cycle()
    for u, r in (("reg1", "registration"), ("doc1", "doctor"), ("ph1", "pharmacist"), ("nu1", "nurse")):
        db.user(u, r)
    ref = db.ref()
    reg = login(db.app, "reg1", PASSWORD)
    p = P.create_patient(db.app, reg, full_name="مريض اختبار الواجهة", age=50, allergy_status="has_allergies",
                         allergen_ids=[ref["حساسية-اختبار-أ"]])
    return db, ref, p


def test_UI5_full_cycle_through_screens(world):
    db, ref, p = world
    # الطبيب: وصفة تثير تنبيه حساسية حرجًا (قاعدة وهمية T-R1)
    at = nav(app_as(db, "doc1"), "وصفة جديدة")
    at.selectbox(key="doc_med").set_value(ref["دواء-اختبار-أ"]).run()
    by_label(at.text_input, "الجرعة (").input("10")
    by_label(at.button, "فحص وإرسال").click().run()
    assert not at.exception, at.exception
    assert any("أُنشئت الوصفة رقم 1" in s.value for s in at.success)
    assert "T-R1" in texts(at) and "حساسية مسجلة: حساسية-اختبار-أ" in texts(at)

    # الصيدلي: الاعتماد معطّل حتى التسوية، ثم تسوية بكل الشروط، ثم اعتماد
    at = app_as(db, "ph1")
    approve_btn = by_label(at.button, "اعتماد الوصفة")
    assert approve_btn.disabled
    by_label(at.checkbox, "1)").check()
    by_label(at.text_input, "2)").input("تحقق وهمي من الواجهة")
    by_label(at.button, "تسجيل التسوية").click().run()
    assert any("سُوّي التنبيه T-R1" in s.value for s in at.success), texts(at)
    by_label(at.button, "اعتماد الوصفة").click().run()
    assert any("اعتُمدت الوصفة رقم 1" in s.value for s in at.success), texts(at)

    # الممرض: التحقق من المريض والدواء وقرار الصيدلي، ثم التوثيق
    at = app_as(db, "nu1")
    assert "مستحقة الآن" in texts(at)
    by_label(at.button, "توثيق").click().run()          # بلا تحقق → رفض
    assert at.error, "كان يجب رفض التوثيق بلا تحقق"
    by_label(at.text_input, "رقم المريض").input(p["mrn"])
    by_label(at.checkbox, "تحققتُ من الدواء").check()
    by_label(at.checkbox, "تحققتُ من قرار الصيدلي").check()
    by_label(at.text_input, "الجرعة الفعلية").input("10")
    by_label(at.button, "توثيق").click().run()
    assert any("وُثّقت الجرعة: أُعطيت" in s.value for s in at.success), texts(at)

    assert db.count("administrations") == 1
    actions = [r["action"] for r in db.audit_rows() if r["outcome"] == "success"]
    for a in ("rx.create", "alert.resolve", "rx.review", "dose.document"):
        assert a in actions
    assert verify_chain(db.admin.engine, AUDIT_KEY).ok


def test_UI6_nurse_sees_block_and_cannot_document_given(world):
    db, ref, p = world
    doc, ph = login(db.app, "doc1", PASSWORD), login(db.app, "ph1", PASSWORD)
    from datetime import timedelta
    from hc.db import db_now
    from hc.timefmt import parse_utc
    with db.app.engine.connect() as c:
        start = parse_utc(db_now(c)).replace(second=0, microsecond=0) + timedelta(minutes=2)
    b = RX.create_prescription(db.app, doc, patient_id=p["id"], medication_id=ref["دواء-اختبار-ب"], dose="5",
                               frequency_id=ref["test-q8h"], start_at=start, duration_days=1)["prescription_id"]
    RV.approve(db.app, ph, b)
    RX.create_prescription(db.app, doc, patient_id=p["id"], medication_id=ref["دواء-اختبار-ج"], dose="5",
                           frequency_id=ref["test-q8h"], start_at=start, duration_days=1)  # T-R2 يمنع
    at = app_as(db, "nu1")
    assert "يُمنع توثيق الإعطاء الآن" in texts(at)
    by_label(at.text_input, "رقم المريض").input(p["mrn"])
    by_label(at.checkbox, "تحققتُ من الدواء").check()
    by_label(at.checkbox, "تحققتُ من قرار الصيدلي").check()
    by_label(at.text_input, "الجرعة الفعلية").input("5")
    by_label(at.button, "توثيق").click().run()
    assert any("يُمنع توثيق الإعطاء" in e.value for e in at.error)
    assert db.count("administrations") == 0
    # «لم تُعطَ» مع إحالة متاحة رغم المنع
    at.radio(key="oc_1").set_value("not_given").run()
    by_label(at.text_input, "رقم المريض").input(p["mrn"])
    by_label(at.checkbox, "تحققتُ من الدواء").check()
    by_label(at.checkbox, "تحققتُ من قرار الصيدلي").check()
    by_label(at.checkbox, "إحالة الحالة").check()
    by_label(at.button, "توثيق").click().run()
    assert any("لم تُعطَ" in s.value and "أُحيلت" in s.value for s in at.success), texts(at)
    # الطبيب يرى الإحالة ويغلقها
    at = nav(app_as(db, "doc1"), "الإحالات")
    assert "أحالها" in texts(at)
    [r for r in at.radio if r.label == "قرارك"][0].set_value("no_action")
    by_label(at.text_input, "ملاحظة").input("اطلعت (اختبار)")
    by_label(at.button, "إغلاق الإحالة").click().run()
    assert any("أُغلقت الإحالة" in s.value for s in at.success), texts(at)


def test_UI7_every_role_every_page_renders(world):
    db, ref, p = world
    pages = {"reg1": ["المرضى", "إضافة مريض", "تعديل مريض"],
             "doc1": ["لوحة الطبيب", "وصفة جديدة", "وصفاتي", "الإحالات"],
             "ph1": ["قائمة المراجعة", "المراجعات السابقة", "الإحالات"],
             "nu1": ["جدول الإعطاء", "الوصفات السارية"]}
    for user, plist in pages.items():
        at = app_as(db, user)
        for pg in plist:
            nav(at, pg)
            assert not at.exception, (user, pg, at.exception)
            assert "بيئة اختبار" in texts(at)   # شريط البيانات الوهمية ظاهر في كل شاشة


def test_UI8_doctor_cannot_send_when_allergy_not_recorded(world):
    db, ref, p = world
    reg = login(db.app, "reg1", PASSWORD)
    P.create_patient(db.app, reg, full_name="مريض بلا بيانات حساسية", age=40, allergy_status="not_recorded")
    at = nav(app_as(db, "doc1"), "وصفة جديدة")
    at.selectbox(key="doc_patient").set_value(2).run()
    assert "لم تُسجَّل" in texts(at)
    by_label(at.text_input, "الجرعة (").input("10")
    by_label(at.button, "فحص وإرسال").click().run()
    assert any("لم تُسجَّل" in e.value for e in at.error)
    assert db.count("prescriptions") == 0


def test_UI9_register_new_patient_with_allergies_from_screen(world):
    """خطأ اكتُشف في المتصفح: داخل st.form لم تكن قائمة الحساسيات تظهر عند اختيار «توجد حساسية»."""
    db, ref, p = world
    at = nav(app_as(db, "reg1"), "إضافة مريض")
    by_label(at.text_input, "الاسم الافتراضي").input("مريض بحساسية من الواجهة")
    by_label(at.text_input, "العمر (18").input("33")
    [r for r in at.radio if r.label == "حالة الحساسية"][0].set_value("has_allergies").run()
    assert at.multiselect, "قائمة الحساسيات يجب أن تظهر فور اختيار «توجد حساسية»"
    at.multiselect[0].set_value([ref["حساسية-اختبار-ب"]]).run()
    by_label(at.button, "حفظ المريض").click().run()
    assert any("حُفظ المريض برقم HC-0002" in s.value for s in at.success), texts(at)
    reg = login(db.app, "reg1", PASSWORD)
    assert P.get_patient(db.app, reg, 2)["allergen_names"] == ["حساسية-اختبار-ب"]
