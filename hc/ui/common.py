"""مكونات مشتركة بين شاشات الأدوار: تشغيل العمليات وعرض الأخطاء، وتفاصيل الوصفة."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from hc import prescriptions as RX
from hc.audit import Ctx
from hc.auth import Session
from hc.config import Config
from hc.errors import DomainError, OperationFailed, PermissionDenied
from hc.labels import (DOSE_STATUS, EXISTING_RX_POLICY, REFERRAL_ACTION, RESOLUTION_POLICY, RULE_TYPE, RX_STATUS,
                       SEVERITY, TIMING)
from hc.timefmt import to_display
from hc.ui.theme import TONES, alert_box, card, chip, e, icon, kv, section

RX_TONE = {"awaiting_pharmacist": "warning", "approved": "success", "returned": "critical",
           "stopped": "neutral", "ended": "neutral"}
DOSE_TONE = {"due": "brand", "missed": "critical", "upcoming": "neutral", "given": "success",
             "not_given": "warning", "cancelled": "neutral", "unknown": "neutral"}
ALERT_STATE = {"needs_resolution": ("يحتاج تسوية بشروط القاعدة", "critical"),
               "return_only": ("إعادة إلزامية — لا يُعتمد", "critical"),
               "resolved": ("سُوّي", "success"), "needs_ack": ("يحتاج إقرارًا بالاطلاع", "warning"),
               "acknowledged": ("أُقرّ بالاطلاع", "success")}


@dataclass
class UI:
    ctx: Ctx
    cfg: Config
    session: Session

    def t(self, v) -> str:
        # عزل اتجاه النص (LRI…PDI) حتى لا ينعكس «التاريخ الوقت» داخل سطر عربي
        out = to_display(v, self.cfg.display_tz)
        return out if out == "—" else "\u2066" + out + "\u2069"


def show_error(err: Exception) -> None:
    if isinstance(err, PermissionDenied) and err.code in ("inactive_or_missing", "stale_session"):
        st.session_state.pop("session", None)
    st.error(getattr(err, "message", str(err)), icon=":material/error:")


def flash_and_rerun(message: str) -> None:
    """بعد كل حفظ ناجح نعيد رسم الصفحة حتى تعرض كل الأقسام البيانات المحدثة."""
    st.session_state["flash"] = message
    st.rerun()


def attempt(fn, *args, **kwargs):
    """ينفذ عملية خادم ويعرض الخطأ بوضوح. يعيد (نجحت؟، النتيجة)."""
    try:
        return True, fn(*args, **kwargs)
    except (DomainError, OperationFailed) as err:
        show_error(err)
        return False, None


def rx_chip(status: str) -> str:
    return chip(RX_STATUS[status], RX_TONE[status])


def dose_chip(status: str) -> str:
    return chip(DOSE_STATUS[status], DOSE_TONE[status])


def alert_card(a: dict) -> None:
    tone = "critical" if a["severity"] == "critical" else "warning"
    state_label, state_tone = ALERT_STATE[a["state"]]
    related = (f"حساسية مسجلة: {a['allergen_name']}" if a.get("allergen_name")
               else f"يتداخل مع الوصفة رقم {a['related_prescription_id']} ({a.get('related_medication')})")
    fg, bg, bd = TONES[tone]
    synthetic = {"test_fixture": chip("قاعدة وهمية للاختبار — غير سريرية", "warning", "flask"),
                 "illustrative": chip("قاعدة توضيحية — غير معتمدة سريريًا", "warning", "flask")}.get(
        a.get("ruleset_kind"), "")
    st.markdown(
        f'<div class="hc-alert" style="--fg:{fg};--bg2:{bg};--bd:{bd}"><div class="hd">{icon("alert", 18, fg)}'
        f'{e(SEVERITY[a["severity"]])} · {e(RULE_TYPE[a["rule_type"]])} · {e(a["code"])} (إصدار {e(a["version"])})'
        f'<span style="margin-inline-start:auto">{chip(state_label, state_tone)}</span></div>'
        f'<div class="bd">{e(a["alert_text"])}</div><div class="bd"><b>السبب:</b> {e(related)}</div>'
        f'<div class="ft">سياسة التسوية: {e(RESOLUTION_POLICY[a["resolution_policy"]])} · أثره على الوصفة القائمة: '
        f'{e(EXISTING_RX_POLICY[a["existing_rx_policy"]])} {synthetic}</div></div>', unsafe_allow_html=True)
    if a["state"] == "resolved":
        items = "؛ ".join(f"{q['seq']}) {q['text']}: " + ("مؤكَّد" if q["confirmed"] else (q["text_value"] or ""))
                          for q in a["requirements"])
        st.caption(f"سُوّي بواسطة {a['resolved_by']} — {items}" + (f" — ملاحظة: {a['resolution_note']}"
                                                                     if a["resolution_note"] else ""))
    elif a["state"] == "acknowledged":
        st.caption(f"أقرّ بالاطلاع: {a['acknowledged_by']}")


def rx_summary(ui: UI, d: dict) -> None:
    med = d["medication"]
    card(f"الوصفة رقم {d['id']}", kv([
        ("الدواء", med["name"]), ("الجرعة", f"{d['dose']} {med['unit']}"), ("التكرار", d["frequency"]["label"]),
        ("بداية العلاج", ui.t(d["start_at"])), ("نهاية العلاج", ui.t(d["end_at"])),
        ("الطبيب الواصف", d["prescriber"]["full_name"]), ("أُنشئت", ui.t(d["created_at"])),
        ("مجموعة القواعد", f"إصدار {d['ruleset_version_id']}"),
    ]) + f'<div style="margin-top:10px">{rx_chip(d["display_status"])}</div>', ic="pill")


def doses_strip(ui: UI, doses: list[dict]) -> None:
    if not doses:
        st.caption("لا توجد جرعات مقررة بعد (تُولَّد عند اعتماد الصيدلي).")
        return
    cells = []
    for x in doses:
        fg, bg, bd = TONES[DOSE_TONE[x["status"]]]
        extra = ""
        if x.get("adm_id"):
            extra = f"<br>{e(x['nurse_name'])}"
            if x.get("late_documentation"):
                extra += " · توثيق متأخر"
        cells.append(f'<div class="hc-dose" style="--fg:{fg};--bg2:{bg};--bd:{bd}"><b>الجرعة {x["dose_number"]}</b>'
                     f'{e(ui.t(x["scheduled_at"]))}<br>{e(DOSE_STATUS[x["status"]])}{extra}</div>')
    st.markdown('<div class="hc-doses">' + "".join(cells) + "</div>", unsafe_allow_html=True)


def administrations_table(ui: UI, doses: list[dict]) -> None:
    rows = [x for x in doses if x.get("adm_id")]
    if not rows:
        return
    st.dataframe([{
        "الجرعة": x["dose_number"], "الموعد": ui.t(x["scheduled_at"]), "النتيجة": DOSE_STATUS[x["outcome"]],
        "الجرعة الفعلية": x["actual_dose"] or "—",
        "وقت الإعطاء (كما أدخله الممرض)": ui.t(x["administered_at_reported"]),
        "وقت التوثيق (الخادم)": ui.t(x["documented_at"]),
        "التوقيت": TIMING.get(x.get("timing"), "—"), "توثيق متأخر": "نعم" if x.get("late_documentation") else "لا",
        "سبب عدم الإعطاء": x["not_given_reason"] or "—", "سبب التأخير": x["late_reason"] or "—",
        "الممرض": x["nurse_name"], "تحذيرات": "؛ ".join(x["warnings"]) or "—",
    } for x in rows], hide_index=True, width="stretch")


def rx_detail(ui: UI, rx_id: int, *, show_audit: bool = True) -> dict | None:
    ok, d = attempt(RX.get_detail, ui.ctx, ui.session, rx_id)
    if not ok:
        return None
    from hc.ui.theme import patient_banner
    patient_banner(d["patient"], d["patient"]["allergies"])
    rx_summary(ui, d)
    section("التنبيهات", "alert")
    if not d["alerts"]:
        alert_box("info", "لم تُنتج القواعد المحمّلة أي تنبيه لهذه الوصفة.",
                  foot="غياب التنبيه لا يعني أن الدواء آمن؛ الفحص يقتصر على القواعد المحمّلة.", ic="info")
    for a in d["alerts"]:
        alert_card(a)
    for a in d["incoming_alerts"]:
        resolved = "سُوّي" if a["resolved"] else "غير محلول"
        alert_box("critical" if a["severity"] == "critical" and not a["resolved"] else "info",
                  f"تنبيه على وصفة أحدث يشير إلى هذه الوصفة: {a['code']} ({resolved})",
                  f"الوصفة رقم {a['prescription_id']} ({a['other_medication']}) — {a['alert_text']}",
                  f"أثره على جرعات هذه الوصفة: {EXISTING_RX_POLICY[a['existing_rx_policy']]}")
    section("قرار الصيدلي", "shield")
    if d["review"]:
        r = d["review"]
        tone = "success" if r["decision"] == "approved" else "critical"
        alert_box(tone, ("اعتُمدت" if r["decision"] == "approved" else "أُعيدت للطبيب") + f" — {r['pharmacist_name']}",
                  r["note"] or "", ui.t(r["created_at"]), ic="check" if tone == "success" else "block")
    else:
        st.caption("لم يُسجَّل قرار بعد.")
    if d["stop"]:
        s = d["stop"]
        alert_box("neutral", f"أُوقفت الوصفة — {s['stopped_by_name']}", s["reason"], ui.t(s["stopped_at"]), ic="block")
    section("الجرعات", "clock")
    doses_strip(ui, d["doses"])
    administrations_table(ui, d["doses"])
    if show_audit:
        with st.expander("سجل الوصفة (من سجل التدقيق)", icon=":material/history:"):
            ok, trail = attempt(RX.rx_audit_trail, ui.ctx, ui.session, rx_id)
            if ok and trail:
                st.dataframe([{"#": t["seq"], "الوقت": ui.t(t["occurred_at"]), "المستخدم": t["actor_username"],
                               "الدور": t["actor_role"] or "—", "العملية": t["action"], "النتيجة": t["outcome"]}
                              for t in trail], hide_index=True, width="stretch")
    return d


def referral_line(ui: UI, r: dict) -> str:
    base = (f"الوصفة {r['prescription_id']} · {r['medication']} · الجرعة {r['dose_number']} "
            f"({ui.t(r['scheduled_at'])}) · السبب: {r['reason']}")
    if r.get("closure_action"):
        base += f" · أُغلقت: {REFERRAL_ACTION[r['closure_action']]}"
    return base
