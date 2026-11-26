"""مراجعة الصيدلي السريري: تسوية التنبيهات، إعادة الفحص، والقرار.

قواعد الاعتماد التي يفرضها الخادم:
- كل وصفة تمر على الصيدلي، بتنبيهات أو بدونها.
- التنبيه الحرج الذي سياسة قاعدته «إعادة إلزامية» يمنع الاعتماد نهائيًا (القرار الوحيد: إعادة).
- التنبيه الحرج «القابل للتسوية بشروط» يحتاج تسوية تثبت كل شرط من شروط القاعدة. الملاحظة الحرة لا تكفي.
- التنبيه غير الحرج يحتاج إقرارًا صريحًا بالاطلاع.
- قبل الاعتماد يُعاد الفحص على بيانات المريض الحالية؛ أي تنبيه جديد يوقف الاعتماد حتى يُراجع.
- عند الاعتماد تُولَّد الجرعات المقررة في المعاملة نفسها.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from . import rules as R
from .audit import ActionResult, Ctx, run_action
from .auth import Session, require_user
from .errors import Conflict, NotFound, ValidationFailed
from .locking import lock_row
from .prescriptions import _rx_row, _text_required, alert_state, alerts_for
from .timefmt import fmt_utc, parse_utc

PHARMACIST = frozenset({"pharmacist"})
MAX_DOSES = 2000  # حد تقني لحماية النظام من وصفة تولّد عددًا هائلًا من الجرعات


def _awaiting(conn, rx_id: int) -> dict:
    lock_row(conn, "prescriptions", rx_id)
    rx = _rx_row(conn, rx_id)
    if rx["status"] != "awaiting_pharmacist":
        raise Conflict("الوصفة ليست بانتظار المراجعة (قد تكون رُوجعت أو أُوقفت).",
                       entity_type="prescription", entity_id=str(rx_id), details={"status": rx["status"]})
    return rx


def _alert_with_rx(conn, alert_id: int) -> dict:
    a = conn.execute(text("SELECT a.*, rv.resolution_policy FROM alerts a JOIN rule_versions rv"
                          " ON rv.id = a.rule_version_id WHERE a.id = :a"), {"a": alert_id}).mappings().first()
    if a is None:
        raise NotFound("التنبيه غير موجود", entity_type="alert", entity_id=str(alert_id))
    return dict(a)


def resolve_alert(ctx: Ctx, session: Session, alert_id: int, *, evidence: dict, note=None) -> None:
    """evidence: {requirement_id: True (للتأكيد) أو نص}."""
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, PHARMACIST)
        a = _alert_with_rx(conn, alert_id)
        _awaiting(conn, a["prescription_id"])
        if a["severity"] != "critical":
            raise ValidationFailed("التنبيه غير الحرج يُقرّ بالاطلاع عليه، ولا يحتاج تسوية.",
                                   entity_type="alert", entity_id=str(alert_id))
        if a["resolution_policy"] == "return_only":
            raise ValidationFailed("قاعدة هذا التنبيه لا تقبل التسوية: القرار الوحيد هو إعادة الوصفة للطبيب.",
                                   code="return_only", entity_type="alert", entity_id=str(alert_id))
        if conn.execute(text("SELECT 1 FROM alert_resolutions WHERE alert_id = :a"), {"a": alert_id}).first():
            raise Conflict("سُوّي هذا التنبيه مسبقًا.", entity_type="alert", entity_id=str(alert_id))
        reqs = conn.execute(text("SELECT id, seq, text, evidence FROM rule_resolution_requirements"
                                 " WHERE rule_version_id = :rv ORDER BY seq"),
                            {"rv": a["rule_version_id"]}).mappings().all()
        items, unmet = [], []
        for q in reqs:
            v = (evidence or {}).get(q["id"], (evidence or {}).get(str(q["id"])))
            if q["evidence"] == "confirm":
                if v is not True:
                    unmet.append(q["seq"])
                items.append((q["id"], True, None))
            else:
                t = " ".join(str(v or "").split())
                if not t:
                    unmet.append(q["seq"])
                items.append((q["id"], None, t))
        if unmet:
            raise ValidationFailed("لم تُستوفَ كل شروط تسوية القاعدة (الشروط: "
                                   + "، ".join(str(s) for s in unmet) + "). الملاحظة الحرة لا تحل محل أي شرط.",
                                   code="requirements_unmet", entity_type="alert", entity_id=str(alert_id),
                                   details={"unmet_requirements": unmet})
        clean_note = " ".join((note or "").split()) or None
        res_id = conn.execute(text("INSERT INTO alert_resolutions (alert_id, pharmacist_id, note)"
                                   " VALUES (:a, :u, :n) RETURNING id"),
                              {"a": alert_id, "u": user["id"], "n": clean_note}).scalar_one()
        for req_id, confirmed, tv in items:
            conn.execute(text("INSERT INTO alert_resolution_items (resolution_id, requirement_id, confirmed, text_value)"
                              " VALUES (:r, :q, :c, :t)"), {"r": res_id, "q": req_id, "c": confirmed, "t": tv})
        return ActionResult(entity_type="alert", entity_id=str(alert_id),
                            details={"prescription_id": a["prescription_id"], "requirements": len(items),
                                     "note": clean_note})

    run_action(ctx, session.actor(), "alert.resolve", fn)


def acknowledge_alert(ctx: Ctx, session: Session, alert_id: int) -> None:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, PHARMACIST)
        a = _alert_with_rx(conn, alert_id)
        _awaiting(conn, a["prescription_id"])
        if a["severity"] == "critical":
            raise ValidationFailed("التنبيه الحرج لا يكفيه الإقرار بالاطلاع؛ يحتاج تسوية بشروط القاعدة.",
                                   entity_type="alert", entity_id=str(alert_id))
        if conn.execute(text("SELECT 1 FROM alert_acknowledgments WHERE alert_id = :a"), {"a": alert_id}).first():
            raise Conflict("أُقرّ بهذا التنبيه مسبقًا.", entity_type="alert", entity_id=str(alert_id))
        conn.execute(text("INSERT INTO alert_acknowledgments (alert_id, pharmacist_id) VALUES (:a, :u)"),
                     {"a": alert_id, "u": user["id"]})
        return ActionResult(entity_type="alert", entity_id=str(alert_id),
                            details={"prescription_id": a["prescription_id"]})

    run_action(ctx, session.actor(), "alert.acknowledge", fn)


def _new_candidates(conn, rx: dict) -> list:
    cands = R.candidates(conn, ruleset_id=rx["ruleset_version_id"], patient_id=rx["patient_id"],
                         medication_id=rx["medication_id"], start_at=rx["start_at"], end_at=rx["end_at"],
                         exclude_rx_id=rx["id"])
    existing = R.existing_alert_keys(conn, rx["id"])
    return [c for c in cands if c.key not in existing]


def recheck(ctx: Ctx, session: Session, rx_id: int) -> int:
    """يعيد فحص الوصفة على بيانات المريض الحالية ويسجّل أي تنبيه جديد. يعيد عدد الجديد."""
    def fn(conn) -> ActionResult:
        require_user(conn, session, PHARMACIST)
        rx = _awaiting(conn, rx_id)
        new = _new_candidates(conn, rx)
        R.insert_alerts(conn, rx_id, new)
        return ActionResult(value=len(new), entity_type="prescription", entity_id=str(rx_id),
                            details={"new_alerts": [{"code": c.code, "severity": c.severity, "detail": c.detail}
                                                    for c in new]})

    return run_action(ctx, session.actor(), "rx.recheck", fn)


def approve(ctx: Ctx, session: Session, rx_id: int, *, note=None) -> int:
    """يعتمد الوصفة ويولّد الجرعات. يعيد عدد الجرعات المولّدة."""
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, PHARMACIST)
        rx = _awaiting(conn, rx_id)
        status = conn.execute(text("SELECT allergy_status FROM patients WHERE id = :p"),
                              {"p": rx["patient_id"]}).scalar_one()
        if status == "not_recorded":
            raise ValidationFailed("حالة حساسية المريض «لم تُسجَّل»؛ لا يمكن الاعتماد.",
                                   code="allergy_not_recorded", entity_type="prescription", entity_id=str(rx_id))
        if _new_candidates(conn, rx):
            raise Conflict("تغيّرت بيانات المريض أو أدويته منذ الفحص، وظهرت تنبيهات جديدة. "
                           "اضغط «إعادة الفحص» وراجعها قبل الاعتماد.",
                           code="stale_check", entity_type="prescription", entity_id=str(rx_id))
        blocking = []
        for a in alerts_for(conn, rx_id):
            st = alert_state(a)
            if st in ("return_only", "needs_resolution", "needs_ack"):
                blocking.append({"alert_id": a["id"], "code": a["code"], "state": st})
        if blocking:
            msgs = {"return_only": "قاعدة إعادة إلزامية", "needs_resolution": "تنبيه حرج غير مسوّى",
                    "needs_ack": "تنبيه غير حرج لم يُقرّ به"}
            raise ValidationFailed("لا يمكن الاعتماد: " + "، ".join(f"{b['code']} ({msgs[b['state']]})"
                                                                    for b in blocking),
                                   code="unresolved_alerts", entity_type="prescription", entity_id=str(rx_id),
                                   details={"blocking": blocking})
        clean_note = " ".join((note or "").split()) or None
        conn.execute(text("INSERT INTO pharmacist_reviews (prescription_id, pharmacist_id, decision, note)"
                          " VALUES (:x, :u, 'approved', :n)"), {"x": rx_id, "u": user["id"], "n": clean_note})
        conn.execute(text("UPDATE prescriptions SET status = 'approved' WHERE id = :x"), {"x": rx_id})
        interval = conn.execute(text("SELECT interval_hours FROM frequencies WHERE id = :f"),
                                {"f": rx["frequency_id"]}).scalar_one()
        t, end, n = parse_utc(rx["start_at"]), parse_utc(rx["end_at"]), 0
        while t < end:
            n += 1
            if n > MAX_DOSES:
                raise ValidationFailed("عدد الجرعات يتجاوز الحد التقني للنظام", entity_type="prescription",
                                       entity_id=str(rx_id))
            conn.execute(text("INSERT INTO scheduled_doses (prescription_id, dose_number, scheduled_at, planned_dose)"
                              " VALUES (:x, :n, :t, :d)"), {"x": rx_id, "n": n, "t": fmt_utc(t), "d": rx["dose"]})
            t += timedelta(hours=interval)
        return ActionResult(value=n, entity_type="prescription", entity_id=str(rx_id),
                            details={"decision": "approved", "note": clean_note, "doses_generated": n})

    return run_action(ctx, session.actor(), "rx.review", fn)


def return_to_doctor(ctx: Ctx, session: Session, rx_id: int, *, note) -> None:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, PHARMACIST)
        _awaiting(conn, rx_id)
        why = _text_required(note, "note", "سبب الإعادة")
        conn.execute(text("INSERT INTO pharmacist_reviews (prescription_id, pharmacist_id, decision, note)"
                          " VALUES (:x, :u, 'returned', :n)"), {"x": rx_id, "u": user["id"], "n": why})
        conn.execute(text("UPDATE prescriptions SET status = 'returned' WHERE id = :x"), {"x": rx_id})
        return ActionResult(entity_type="prescription", entity_id=str(rx_id),
                            details={"decision": "returned", "note": why})

    run_action(ctx, session.actor(), "rx.review", fn)
