"""شاشات موظف التسجيل."""
from __future__ import annotations

import streamlit as st

from hc import patients as P
from hc.ui.common import UI, attempt, flash_and_rerun
from hc.ui.theme import allergy_chip, empty, kpis, page_header, patient_banner, section

PAGES = ["المرضى", "إضافة مريض", "تعديل مريض"]


def allergen_picker(ui: UI, key: str, default_ids=(), default_status: str = "not_recorded"):
    ok, allergens = attempt(P.list_allergens, ui.ctx, ui.session)
    allergens = allergens or []
    options = list(P.ALLERGY_STATUSES)
    # نموذج التعديل يبدأ من الحالة المحفوظة فعلًا، حتى لا يمسحها حفظ غير مقصود
    status = st.radio("حالة الحساسية", options, index=options.index(default_status), key=f"{key}_status",
                      format_func=lambda s: P.ALLERGY_STATUSES[s], horizontal=True)
    ids: list[int] = []
    if status == "has_allergies":
        if not allergens:
            st.warning("قائمة الحساسيات المعتمدة لم تُحمَّل بعد، فلا يمكن اختيار حساسية.")
        else:
            names = {a["id"]: a["name"] for a in allergens}
            ids = st.multiselect("الحساسيات", list(names), default=[i for i in default_ids if i in names],
                                 format_func=lambda i: names[i], key=f"{key}_ids")
    return status, ids


def render(ui: UI, page: str) -> None:
    if page == "المرضى":
        page_header("سجل المرضى", "كل المرضى المسجلين وحالة بيانات الحساسية لديهم")
        ok, rows = attempt(P.list_patients, ui.ctx, ui.session)
        rows = rows or []
        kpis([("إجمالي المرضى", len(rows), "brand"),
              ("حساسية لم تُسجَّل", sum(r["allergy_status"] == "not_recorded" for r in rows), "warning"),
              ("لديهم حساسية مسجلة", sum(r["allergy_status"] == "has_allergies" for r in rows), "critical"),
              ("لا حساسية معروفة", sum(r["allergy_status"] == "none_known" for r in rows), "success")])
        q = st.text_input("بحث بالاسم أو رقم المريض", placeholder="مثال: HC-0001", key="reg_search",
                          icon=":material/search:")
        if q:
            rows = [r for r in rows if q.strip().lower() in (r["full_name"] + " " + r["mrn"]).lower()]
        if not rows:
            empty("لا يوجد مرضى مطابقون." if q else "لا يوجد مرضى مسجلون بعد.")
            return
        st.dataframe([{"رقم المريض": r["mrn"], "الاسم": r["full_name"], "العمر": r["age"],
                       "حالة الحساسية": P.ALLERGY_STATUSES[r["allergy_status"]],
                       "أُنشئ": ui.t(r["created_at"]), "آخر تعديل": ui.t(r["updated_at"])} for r in rows],
                     hide_index=True, width="stretch")
        return

    if page == "إضافة مريض":
        page_header("تسجيل مريض جديد", "يولّد النظام رقم المريض تلقائيًا. استخدم بيانات اصطناعية فقط.")
        # بلا st.form: اختيار «توجد حساسية» يجب أن يُظهر قائمة الحساسيات فورًا
        n = st.session_state.get("new_patient_n", 0)
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            name = c1.text_input("الاسم الافتراضي (اصطناعي)", key=f"np_name_{n}")
            age = c2.text_input("العمر (18 فأكثر)", key=f"np_age_{n}")
            status, ids = allergen_picker(ui, f"new{n}")
            st.caption("«لم تُسجَّل» تعني أن البيانات غير معروفة بعد، ولا تعني عدم وجود حساسية. "
                       "لا يستطيع الطبيب إرسال وصفة لمريض حالته «لم تُسجَّل».")
            if st.button("حفظ المريض", type="primary", icon=":material/person_add:"):
                ok, p = attempt(P.create_patient, ui.ctx, ui.session, full_name=name, age=age,
                                allergy_status=status, allergen_ids=ids)
                if ok:
                    st.session_state["new_patient_n"] = n + 1  # نموذج فارغ للمريض التالي
                    flash_and_rerun(f"حُفظ المريض برقم {p['mrn']}")
        return

    # تعديل مريض
    page_header("ملف المريض", "تعديل البيانات والحساسيات، مع الاحتفاظ بتاريخ كل حساسية")
    ok, rows = attempt(P.list_patients, ui.ctx, ui.session)
    if not rows:
        empty("لا يوجد مرضى مسجلون بعد.")
        return
    labels = {r["id"]: f"{r['mrn']} — {r['full_name']}" for r in rows}
    choice = st.selectbox("اختر المريض", list(labels), format_func=labels.get, key="reg_patient")
    ok, p = attempt(P.get_patient, ui.ctx, ui.session, choice)
    if not ok:
        return
    patient_banner(p, p["allergen_names"])
    left, right = st.columns(2, gap="large")
    with left:
        section("البيانات الأساسية", "user")
        with st.form(f"edit_{choice}"):
            name = st.text_input("الاسم", value=p["full_name"])
            age = st.text_input("العمر", value=str(p["age"]))
            st.caption(f"نسخة السجل: {p['row_version']} — إذا عدّل غيرك السجل بعد فتحه سيُرفض الحفظ لحماية بياناته.")
            if st.form_submit_button("حفظ البيانات", type="primary", icon=":material/save:"):
                ok, _ = attempt(P.update_patient, ui.ctx, ui.session, choice, expected_version=p["row_version"],
                                full_name=name, age=age)
                if ok:
                    flash_and_rerun("حُفظ التعديل")
    with right:
        section("الحساسيات", "alert")
        with st.container(border=True):  # بلا st.form حتى تتجاوب القائمة مع تغيير الحالة فورًا
            status, ids = allergen_picker(ui, f"edit{choice}_v{p['row_version']}", p["allergen_ids"],
                                          p["allergy_status"])
            reason = st.text_input("سبب إزالة الحساسية (إلزامي عند إزالة حساسية مسجلة)",
                                   key=f"rm_reason_{choice}_v{p['row_version']}")
            if st.button("حفظ الحساسيات", type="primary", icon=":material/save:"):
                ok, _ = attempt(P.set_allergies, ui.ctx, ui.session, choice, expected_version=p["row_version"],
                                allergy_status=status, allergen_ids=ids, removal_reason=reason)
                if ok:
                    flash_and_rerun("حُفظت الحساسيات")
    section("تاريخ الحساسيات", "clock")
    ok, hist = attempt(P.allergy_history, ui.ctx, ui.session, choice)
    if not hist:
        st.caption("لا توجد سطور حساسية مسجلة لهذا المريض.")
    else:
        st.dataframe([{"الحساسية": h["allergen_name"], "سُجّلت": ui.t(h["recorded_at"]), "سجّلها": h["recorded_by"],
                       "الحالة": "حالية" if h["removed_at"] is None else "أُزيلت",
                       "أُزيلت": ui.t(h["removed_at"]), "أزالها": h["removed_by"] or "—",
                       "سبب الإزالة": h["removal_reason"] or "—"} for h in hist],
                     hide_index=True, width="stretch")
