"""شاشات الممرض: جدول الإعطاء والتوثيق."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from hc import administration as AD
from hc import prescriptions as RX
from hc import reference as REF
from hc.labels import DOSE_STATUS, RX_STATUS
from hc.timefmt import local_to_utc
from hc.ui.common import UI, attempt, dose_chip, flash_and_rerun, rx_detail, rx_summary
from hc.ui.theme import alert_box, empty, kpis, page_header, patient_banner, section

PAGES = ["جدول الإعطاء", "الوصفات السارية"]
UPCOMING_HOURS = 12  # نطاق العرض فقط (ليس قيمة سريرية): ما يظهر من الجرعات القادمة في الجدول


def _dose_table(ui: UI, rows: list[dict]) -> None:
    st.dataframe([{"الموعد": ui.t(r["scheduled_at"]), "الحالة": DOSE_STATUS[r["status"]],
                   "المريض": f"{r['mrn']} — {r['patient_name']}", "الدواء": r["medication"],
                   "الجرعة المقررة": f"{r['planned_dose']} {r['unit']}", "رقم الجرعة": r["dose_number"],
                   "الوصفة": r["prescription_id"]} for r in rows], hide_index=True, width="stretch")


def _document(ui: UI, dose: dict) -> None:
    ok, ctxd = attempt(AD.dose_context, ui.ctx, ui.session, dose["id"])
    ok2, d = attempt(RX.get_detail, ui.ctx, ui.session, dose["prescription_id"])
    if not (ok and ok2):
        return
    patient_banner(d["patient"], d["patient"]["allergies"])
    rx_summary(ui, d)
    st.markdown(f"**الجرعة {dose['dose_number']}** — موعدها {ui.t(dose['scheduled_at'])} — "
                f"الكمية المقررة {dose['planned_dose']} {dose['unit']} &nbsp; {dose_chip(dose['status'])}",
                unsafe_allow_html=True)
    if d["review"]:
        st.caption(f"قرار الصيدلي: اعتماد — {d['review']['pharmacist_name']} ({ui.t(d['review']['created_at'])})"
                   + (f" — {d['review']['note']}" if d["review"]["note"] else ""))
    for b in ctxd["blocks"]:
        alert_box("critical", "يُمنع توثيق الإعطاء الآن", b, "يمكن توثيق «لم تُعطَ» مع السبب.", ic="block")
    for wmsg in ctxd["warnings"]:
        alert_box("warning", "تحذير (لا يمنع التوثيق، ويُحفظ معه)", wmsg)

    section("التحقق والتوثيق", "shield")
    outcome = st.radio("النتيجة", ["given", "not_given"], horizontal=True, key=f"oc_{dose['id']}",
                       format_func={"given": "أُعطيت", "not_given": "لم تُعطَ"}.get)
    tz = ZoneInfo(ui.cfg.display_tz)
    with st.form(f"doc_{dose['id']}"):
        c1, c2 = st.columns([1, 2])
        mrn = c1.text_input("رقم المريض كما على سوار التعريف", placeholder="HC-0000")
        with c2:
            vm = st.checkbox(f"تحققتُ من الدواء: {d['medication']['name']} — {dose['planned_dose']} {dose['unit']}")
            vp = st.checkbox("تحققتُ من قرار الصيدلي (معتمدة)")
        kw: dict = {}
        if outcome == "given":
            c3, c4, c5 = st.columns(3)
            actual = c3.text_input(f"الجرعة الفعلية المعطاة ({dose['unit']})")
            now_local = datetime.now(tz).replace(second=0, microsecond=0)
            ad = c4.date_input("تاريخ الإعطاء الفعلي", value=now_local.date())
            at = c5.time_input("وقت الإعطاء الفعلي", value=now_local.time(), step=timedelta(minutes=1))
            st.caption("وقت الإعطاء يُدخله الممرض ويُحفظ كما أُدخل؛ وقت التوثيق يضعه الخادم تلقائيًا. "
                       "إذا اختلفت الجرعة الفعلية عن المقررة لا تُسجَّل «أُعطيت».")
            kw = dict(actual_dose=actual, administered_at=local_to_utc(ad, at, ui.cfg.display_tz))
        else:
            ok, reasons = attempt(REF.list_not_given_reasons, ui.ctx, ui.session)
            rmap = {r["id"]: r for r in reasons or []}
            rid = st.selectbox("سبب عدم الإعطاء", list(rmap), format_func=lambda i: rmap[i]["label"])
            rtext = st.text_input("توضيح السبب (إلزامي لبعض الأسباب)")
            ref = st.checkbox("إحالة الحالة للطبيب الواصف")
            rnote = st.text_input("ملاحظة الإحالة (اختيارية)")
            kw = dict(not_given_reason_id=rid, reason_text=rtext, create_referral=ref, referral_note=rnote)
        late = st.text_input("سبب التأخير (إلزامي إذا كان التوثيق بعد نهاية النافذة الزمنية)")
        if st.form_submit_button("توثيق", type="primary", icon=":material/assignment_turned_in:"):
            ok, res = attempt(AD.record_administration, ui.ctx, ui.session, dose["id"], verified_mrn=mrn,
                              verified_medication=vm, verified_pharmacist_decision=vp, outcome=outcome,
                              late_reason=late, **kw)
            if ok:
                msg = "وُثّقت الجرعة: " + ("أُعطيت" if outcome == "given" else "لم تُعطَ")
                if res["late_documentation"]:
                    msg += " (توثيق متأخر)"
                if res["referral_id"]:
                    msg += " — وأُحيلت للطبيب"
                flash_and_rerun(msg)


def render(ui: UI, page: str) -> None:
    if page == "جدول الإعطاء":
        page_header("جدول الإعطاء", "الجرعات المستحقة والفائتة والقادمة للوصفات المعتمدة")
        ok, rows = attempt(AD.dose_worklist, ui.ctx, ui.session, include_upcoming_hours=UPCOMING_HOURS)
        rows = rows or []
        due = [r for r in rows if r["status"] == "due"]
        missed = [r for r in rows if r["status"] == "missed"]
        upcoming = [r for r in rows if r["status"] == "upcoming"]
        unknown = [r for r in rows if r["status"] == "unknown"]
        kpis([("مستحقة الآن", len(due), "brand"), ("فائتة غير موثقة", len(missed), "critical"),
              (f"قادمة خلال {UPCOMING_HOURS} ساعة", len(upcoming), "neutral")])
        if unknown:
            alert_box("warning", "إعداد النافذة الزمنية غير معتمد بعد",
                      "لا يمكن حساب استحقاق الجرعات ولا توثيقها حتى يُضبط الإعداد.")
        if not rows:
            empty("لا توجد جرعات للعرض.")
            return
        for title, group in (("مستحقة الآن", due), ("فائتة غير موثقة", missed), ("قادمة", upcoming)):
            if group:
                section(title, "clock")
                _dose_table(ui, group)
        selectable = due + missed + upcoming
        if not selectable:
            return
        lab = {r["id"]: f"{DOSE_STATUS[r['status']]} · {ui.t(r['scheduled_at'])} · {r['mrn']} — "
                        f"{r['patient_name']} · {r['medication']} (جرعة {r['dose_number']})" for r in selectable}
        did = st.selectbox("اختر الجرعة للتحقق والتوثيق", list(lab), format_func=lab.get, key="nu_dose")
        _document(ui, next(r for r in selectable if r["id"] == did))
        return

    page_header("الوصفات السارية", "الوصفات المعتمدة والموقوفة وسجل جرعاتها")
    ok, rows = attempt(RX.list_prescriptions, ui.ctx, ui.session)
    rows = [r for r in rows or [] if r["status"] in ("approved", "stopped")]
    if not rows:
        empty("لا توجد وصفات معتمدة.")
        return
    st.dataframe([{"رقم": r["id"], "المريض": f"{r['mrn']} — {r['patient_name']}", "الدواء": r["medication"],
                   "الحالة": RX_STATUS[r["display_status"]], "بداية": ui.t(r["start_at"]), "نهاية": ui.t(r["end_at"])}
                  for r in rows], hide_index=True, width="stretch")
    lab = {r["id"]: f"#{r['id']} · {r['medication']} · {r['mrn']} — {r['patient_name']}" for r in rows}
    rid = st.selectbox("عرض الوصفة", list(lab), format_func=lab.get, key="nu_rx")
    rx_detail(ui, rid)
