"""UI4: إزالة حساسية من الواجهة مع سبب، وظهورها في جدول التاريخ."""
from streamlit.testing.v1 import AppTest

from conftest import AUDIT_KEY, PASSWORD, ROOT, make_sqlite_db
from hc import patients as P
from hc.auth import login


def test_UI4_allergy_removal_shows_in_history(tmp_path):
    import streamlit as st
    st.cache_resource.clear()
    db = make_sqlite_db(tmp_path)
    ids = db.add_fake_allergens()
    db.user("reg1", "registration")
    s = login(db.app, "reg1", PASSWORD)
    P.create_patient(db.app, s, full_name="مريض", age=30, allergy_status="has_allergies", allergen_ids=ids[:2])

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    for k, v in {"HC_ENV": "test", "HC_TEST_DATABASE_URL": db.app_url,
                 "HC_TEST_AUDIT_HMAC_KEY": AUDIT_KEY.decode(), "HC_DISPLAY_TZ": "Asia/Aden"}.items():
        at.secrets[k] = v
    at.run()
    at.text_input[0].input("reg1")
    at.text_input[1].input(PASSWORD)
    at.button[0].click().run()
    [r for r in at.radio if r.label == "القسم"][0].set_value("تعديل مريض").run()
    at.multiselect[0].set_value(ids[1:2])
    [t for t in at.text_input if t.label.startswith("سبب إزالة")][0].input("سبب تجريبي للإزالة")
    [b for b in at.button if b.label == "حفظ الحساسيات"][0].click().run()
    assert not at.exception, at.exception
    assert any("حُفظت الحساسيات" in m.value for m in at.success)
    hist = at.dataframe[-1].value
    assert len(hist) == 2
    removed = hist[hist["الحالة"] == "أُزيلت"]
    assert len(removed) == 1 and removed.iloc[0]["سبب الإزالة"] == "سبب تجريبي للإزالة"
