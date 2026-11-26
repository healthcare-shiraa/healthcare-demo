"""شاشات الطبيب."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from hc import patients as P
from hc import prescriptions as RX
from hc import reference as REF
from hc.labels import REFERRAL_ACTION, RX_STATUS
from hc.ui.common import UI, attempt, flash_and_rerun, referral_line, rx_detail
from hc.ui.theme import alert_box, empty, kpis, page_header, patient_banner, section
from hc.timefmt import local_to_utc

PAGES = ["لوحة الطبيب", "وصفة جديدة", "وصفاتي", "الإحالات"]


def _rx_table(ui: UI, rows: list[dict]) -> None:
    st.dataframe([{"رقم": r["id"], "المريض": f"{r['mrn']} — {r['patient_name']}", "الدواء": r["medication"],
                   "الجرعة": f"{r['dose']} {r['unit']}", "التكرار": r["frequency"],
                   "الحالة": RX_STATUS[r["display_status"]],
                   "تنبيهات": f"{r['alert_count']} ({r['critical_count']} حرج)" if r["alert_count"] else "لا يوجد",
                   "أُنشئت": ui.t(r["created_at"])} for r in rows], hide_index=True, width="stretch")


def render(ui: UI, page: str) -> None:
    if page == "لوحة الطبيب":
        page_header("لوحة الطبيب", "وصفاتك وحالتها، والإحالات التي تنتظر قرارك")
        ok, mine = attempt(RX.list_prescriptions, ui.ctx, ui.session, mine=True)
        ok2, refs = attempt(RX.list_referrals, ui.ctx, ui.session)
        mine, refs = mine or [], refs or []
        kpis([("بانتظار الصيدلي", sum(r["status"] == "awaiting_pharmacist" for r in mine), "warning"),
              ("معتمدة وسارية", sum(r["display_status"] == "approved" for r in mine), "success"),
              ("مُعادة إليك", sum(r["status"] == "returned" for r in mine), "critical"),
              ("إحالات مفتوحة", len(refs), "info")])
        returned = [r for r in mine if r["status"] == "returned"]
        if returned:
            section("وصفات أعادها الصيدلي", "block")
            _rx_table(ui, returned)
        section("أحدث وصفاتك", "pill")
        if mine:
            _rx_table(ui, mine[:10])
        else:
            empty("لم تُنشئ أي وصفة بعد. ابدأ من «وصفة جديدة».")
        return

    if page == "وصفة جديدة":
        page_header("وصفة جديدة", "تُفحص الوصفة تلقائيًا بالقواعد الثابتة، ثم تُرسل للصيدلي السريري")
        ok, patients = attempt(P.list_patients, ui.ctx, ui.session)
        if not patients:
            empty("لا يوجد مرضى مسجلون.")
            return
        labels = {p["id"]: f"{p['mrn']} — {p['full_name']}" for p in patients}
        pid = st.selectbox("المريض", list(labels), format_func=labels.get, key="doc_patient")
        ok, p = attempt(P.get_patient, ui.ctx, ui.session, pid)
        if not ok:
            return
        patient_banner(p, p["allergen_names"])
        if p["allergy_status"] == "not_recorded":
            alert_box("warning", "حالة حساسية هذا المريض «لم تُسجَّل»",
                      "لن يقبل النظام إرسال الوصفة قبل أن يستكمل موظف التسجيل بيانات الحساسية.")
        ok, meds = attempt(REF.list_medications, ui.ctx, ui.session)
        if not meds:
            alert_box("warning", "لا توجد قائمة أدوية معتمدة محمّلة",
                      "تُحمَّل الأدوية والقواعد بعد اعتمادها سريريًا. في بيئة الاختبار تُحمَّل قائمة وهمية.")
            return
        med_map = {m["id"]: m for m in meds}
        mid = st.selectbox("الدواء", list(med_map), format_func=lambda i: med_map[i]["name"], key="doc_med")
        m = med_map[mid]
        ok, freqs = attempt(REF.list_medication_frequencies, ui.ctx, ui.session, mid)
        freqs = freqs or []
        tz = ZoneInfo(ui.cfg.display_tz)
        default_start = (datetime.now(tz) + timedelta(minutes=10)).replace(second=0, microsecond=0)
        with st.form("new_rx"):
            c1, c2 = st.columns(2)
            dose = c1.text_input(f"الجرعة ({m['unit']})", help=f"نطاق الاختبار المعتمد: {m['dose_min']}–{m['dose_max']}")
            fmap = {f["id"]: f["label"] for f in freqs}
            fid = c2.selectbox("التكرار", list(fmap), format_func=fmap.get) if fmap else None
            c3, c4, c5 = st.columns(3)
            sd = c3.date_input("تاريخ البداية", value=default_start.date())
            stime = c4.time_input("وقت البداية", value=default_start.time(), step=timedelta(minutes=5))
            days = c5.number_input("مدة العلاج (أيام)", min_value=1, step=1, value=1)
            st.caption(f"الأوقات بتوقيت {ui.cfg.display_tz}. نطاق جرعة الاختبار: {m['dose_min']}–{m['dose_max']} "
                       f"{m['unit']}. لا يقترح النظام جرعات ولا يعدّلها.")
            if st.form_submit_button("فحص وإرسال للصيدلي", type="primary", icon=":material/send:"):
                ok, res = attempt(RX.create_prescription, ui.ctx, ui.session, patient_id=pid, medication_id=mid,
                                  dose=dose, frequency_id=fid, start_at=local_to_utc(sd, stime, ui.cfg.display_tz),
                                  duration_days=days)
                if ok:
                    st.session_state["doc_last_rx"] = res["prescription_id"]
                    n = len(res["alerts"])
                    flash_and_rerun(f"أُنشئت الوصفة رقم {res['prescription_id']} وأُرسلت للصيدلي "
                                    f"({'بلا تنبيهات' if n == 0 else f'{n} تنبيه'}).")
        last = st.session_state.get("doc_last_rx")
        if last:
            section(f"نتيجة فحص الوصفة رقم {last}", "shield")
            rx_detail(ui, last, show_audit=False)
        return

    if page == "وصفاتي":
        page_header("وصفاتي", "تفاصيل كل وصفة: التنبيهات، قرار الصيدلي، والجرعات")
        ok, mine = attempt(RX.list_prescriptions, ui.ctx, ui.session, mine=True)
        if not mine:
            empty("لا توجد وصفات بعد.")
            return
        flt = st.segmented_control("تصفية", ["الكل", *[RX_STATUS[s] for s in ("awaiting_pharmacist", "approved",
                                                                               "returned", "stopped", "ended")]],
                                   default="الكل", key="doc_filter")
        rows = mine if flt in (None, "الكل") else [r for r in mine if RX_STATUS[r["display_status"]] == flt]
        if not rows:
            empty("لا توجد وصفات بهذه الحالة.")
            return
        _rx_table(ui, rows)
        lab = {r["id"]: f"#{r['id']} · {r['medication']} · {r['mrn']} — {r['patient_name']}" for r in rows}
        rid = st.selectbox("عرض الوصفة", list(lab), format_func=lab.get, key="doc_rx")
        d = rx_detail(ui, rid)
        if d and d["status"] in ("awaiting_pharmacist", "approved") and d["prescriber_id"] == ui.session.user_id:
            section("إيقاف الوصفة", "block")
            with st.form(f"stop_{rid}"):
                reason = st.text_input("سبب الإيقاف (إلزامي)")
                st.caption("الإيقاف نهائي. الجرعات التي يقع موعدها بعد الإيقاف تُلغى، وتبقى الجرعات الموثقة كما هي.")
                if st.form_submit_button("إيقاف الوصفة", icon=":material/stop_circle:"):
                    ok, _ = attempt(RX.stop_prescription, ui.ctx, ui.session, rid, reason=reason)
                    if ok:
                        flash_and_rerun(f"أُوقفت الوصفة رقم {rid}")
        return

    # الإحالات
    page_header("الإحالات", "جرعات لم تُعطَ وأحالها الممرض إليك. إغلاق الإحالة يوثّق قرارك ولا يغيّر حالة الجرعة.")
    ok, refs = attempt(RX.list_referrals, ui.ctx, ui.session)
    if not refs:
        empty("لا توجد إحالات مفتوحة.")
    for r in refs or []:
        with st.container(border=True):
            alert_box("warning", f"{r['mrn']} — {r['patient_name']}", referral_line(ui, r),
                      f"أحالها: {r['nurse_name']} · {ui.t(r['created_at'])}" + (f" · ملاحظة: {r['note']}" if r["note"] else ""))
            with st.form(f"close_{r['id']}"):
                action = st.radio("قرارك", list(REFERRAL_ACTION), format_func=REFERRAL_ACTION.get, horizontal=True)
                ok, prx = attempt(RX.list_prescriptions, ui.ctx, ui.session, patient_id=None, mine=True)
                same = [x for x in (prx or []) if x["mrn"] == r["mrn"] and x["id"] != r["prescription_id"]]
                new_id = st.selectbox("الوصفة الجديدة (عند اختيار «أنشأتُ وصفة جديدة»)", [None] + [x["id"] for x in same],
                                      format_func=lambda i: "—" if i is None else f"#{i}")
                note = st.text_input("ملاحظة (إلزامية عند «لا إجراء»)")
                if st.form_submit_button("إغلاق الإحالة", type="primary", icon=":material/task_alt:"):
                    ok, _ = attempt(RX.close_referral, ui.ctx, ui.session, r["id"], action=action,
                                    new_prescription_id=new_id, note=note)
                    if ok:
                        flash_and_rerun("أُغلقت الإحالة. الجرعة تبقى «لم تُعطَ» في السجل.")
    ok, closed = attempt(RX.list_referrals, ui.ctx, ui.session, open_only=False)
    closed = [c for c in (closed or []) if c["closure_action"]]
    if closed:
        section("إحالات مغلقة", "check")
        for c in closed:
            st.caption(referral_line(ui, c) + (f" — {c['closure_note']}" if c["closure_note"] else ""))
