"""شاشات الصيدلي السريري."""
from __future__ import annotations

import streamlit as st

from hc import prescriptions as RX
from hc import review as RV
from hc.labels import RX_STATUS
from hc.ui.common import UI, alert_card, attempt, flash_and_rerun, referral_line, rx_detail, rx_summary
from hc.ui.theme import alert_box, empty, kpis, page_header, patient_banner, section

PAGES = ["قائمة المراجعة", "المراجعات السابقة", "الإحالات"]


def _queue_table(ui: UI, rows: list[dict]) -> None:
    st.dataframe([{"رقم": r["id"], "المريض": f"{r['mrn']} — {r['patient_name']}", "الدواء": r["medication"],
                   "الجرعة": f"{r['dose']} {r['unit']}", "الطبيب": r["prescriber_name"],
                   "تنبيهات حرجة": r["critical_count"], "كل التنبيهات": r["alert_count"],
                   "أُنشئت": ui.t(r["created_at"])} for r in rows], hide_index=True, width="stretch")


def _alert_actions(ui: UI, a: dict) -> None:
    alert_card(a)
    if a["state"] == "needs_resolution":
        with st.form(f"resolve_{a['id']}"):
            st.markdown("**تسوية التنبيه — يجب استيفاء كل شروط القاعدة:**")
            evidence = {}
            for q in a["requirements"]:
                if q["evidence"] == "confirm":
                    evidence[q["id"]] = st.checkbox(f"{q['seq']}) {q['text']}", key=f"q_{a['id']}_{q['id']}")
                else:
                    evidence[q["id"]] = st.text_input(f"{q['seq']}) {q['text']}", key=f"q_{a['id']}_{q['id']}")
            note = st.text_input("ملاحظة إضافية (اختيارية — لا تحل محل أي شرط)", key=f"n_{a['id']}")
            if st.form_submit_button("تسجيل التسوية", type="primary", icon=":material/verified:"):
                ok, _ = attempt(RV.resolve_alert, ui.ctx, ui.session, a["id"], evidence=evidence, note=note)
                if ok:
                    flash_and_rerun(f"سُوّي التنبيه {a['code']}")
    elif a["state"] == "needs_ack":
        if st.button(f"أُقرّ بالاطلاع على التنبيه {a['code']}", key=f"ack_{a['id']}", icon=":material/visibility:"):
            ok, _ = attempt(RV.acknowledge_alert, ui.ctx, ui.session, a["id"])
            if ok:
                flash_and_rerun(f"سُجّل الإقرار بالتنبيه {a['code']}")
    elif a["state"] == "return_only":
        st.caption("قاعدة هذا التنبيه لا تقبل التسوية؛ القرار المتاح هو إعادة الوصفة للطبيب.")


def render(ui: UI, page: str) -> None:
    if page == "قائمة المراجعة":
        page_header("قائمة المراجعة", "كل وصفة تمر عليك قبل وصولها للممرض، بتنبيهات أو بدونها")
        ok, rows = attempt(RX.list_prescriptions, ui.ctx, ui.session, status="awaiting_pharmacist")
        rows = sorted(rows or [], key=lambda r: (-r["critical_count"], r["id"]))
        kpis([("بانتظار المراجعة", len(rows), "warning"),
              ("فيها تنبيه حرج", sum(r["critical_count"] > 0 for r in rows), "critical"),
              ("بلا تنبيهات", sum(r["alert_count"] == 0 for r in rows), "success")])
        if not rows:
            empty("لا توجد وصفات بانتظار المراجعة.")
            return
        _queue_table(ui, rows)
        lab = {r["id"]: f"#{r['id']} · {r['medication']} · {r['mrn']} — {r['patient_name']}"
               + (f" · {r['critical_count']} حرج" if r["critical_count"] else "") for r in rows}
        rid = st.selectbox("الوصفة قيد المراجعة", list(lab), format_func=lab.get, key="ph_rx")
        ok, d = attempt(RX.get_detail, ui.ctx, ui.session, rid)
        if not ok:
            return
        patient_banner(d["patient"], d["patient"]["allergies"])
        rx_summary(ui, d)
        c1, c2 = st.columns([3, 1])
        c1.caption("إذا تغيّرت حساسيات المريض أو أدويته بعد إنشاء الوصفة، أعد الفحص قبل القرار. "
                   "النظام يرفض الاعتماد إذا ظهرت تنبيهات جديدة لم تُراجع.")
        if c2.button("إعادة الفحص", icon=":material/refresh:", key=f"recheck_{rid}"):
            ok, n = attempt(RV.recheck, ui.ctx, ui.session, rid)
            if ok:
                flash_and_rerun("لا تنبيهات جديدة." if n == 0 else f"سُجّل {n} تنبيه جديد؛ راجعه أدناه.")
        section("التنبيهات", "alert")
        if not d["alerts"]:
            alert_box("info", "لم تُنتج القواعد المحمّلة أي تنبيه لهذه الوصفة.",
                      foot="غياب التنبيه لا يعني أن الدواء آمن؛ الفحص يقتصر على القواعد المحمّلة.", ic="info")
        for a in d["alerts"]:
            _alert_actions(ui, a)
        section("القرار", "shield")
        pending = [a for a in d["alerts"] if a["state"] in ("needs_resolution", "needs_ack", "return_only")]
        if pending:
            alert_box("warning", "الاعتماد غير متاح بعد",
                      "تنبيهات تحتاج إجراء: " + "، ".join(a["code"] for a in pending)
                      + ". الإعادة للطبيب متاحة دائمًا.")
        left, right = st.columns(2, gap="large")
        with left:
            with st.form(f"approve_{rid}"):
                note = st.text_input("ملاحظة الاعتماد (اختيارية)")
                if st.form_submit_button("اعتماد الوصفة", type="primary", icon=":material/check_circle:",
                                         disabled=bool(pending)):
                    ok, n = attempt(RV.approve, ui.ctx, ui.session, rid, note=note)
                    if ok:
                        flash_and_rerun(f"اعتُمدت الوصفة رقم {rid} وولّدت {n} جرعة مقررة.")
        with right:
            with st.form(f"return_{rid}"):
                note = st.text_input("سبب الإعادة للطبيب (إلزامي)")
                if st.form_submit_button("إعادة للطبيب", icon=":material/undo:"):
                    ok, _ = attempt(RV.return_to_doctor, ui.ctx, ui.session, rid, note=note)
                    if ok:
                        flash_and_rerun(f"أُعيدت الوصفة رقم {rid} للطبيب.")
        return

    if page == "المراجعات السابقة":
        page_header("المراجعات السابقة", "الوصفات التي سُجّل لها قرار")
        ok, rows = attempt(RX.list_prescriptions, ui.ctx, ui.session)
        rows = [r for r in rows or [] if r["status"] != "awaiting_pharmacist"]
        if not rows:
            empty("لا توجد مراجعات سابقة.")
            return
        st.dataframe([{"رقم": r["id"], "المريض": f"{r['mrn']} — {r['patient_name']}", "الدواء": r["medication"],
                       "الحالة": RX_STATUS[r["display_status"]], "الطبيب": r["prescriber_name"]} for r in rows],
                     hide_index=True, width="stretch")
        lab = {r["id"]: f"#{r['id']} · {r['medication']} · {r['mrn']}" for r in rows}
        rid = st.selectbox("عرض الوصفة", list(lab), format_func=lab.get, key="ph_hist")
        rx_detail(ui, rid)
        return

    page_header("الإحالات", "للاطلاع: جرعات لم تُعطَ وأُحيلت للطبيب الواصف")
    ok, refs = attempt(RX.list_referrals, ui.ctx, ui.session, open_only=False)
    if not refs:
        empty("لا توجد إحالات.")
    for r in refs or []:
        alert_box("info" if r["closure_action"] else "warning", f"{r['mrn']} — {r['patient_name']}",
                  referral_line(ui, r), f"أحالها: {r['nurse_name']}", ic="info")
