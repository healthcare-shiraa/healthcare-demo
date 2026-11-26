"""الوصفة الدوائية: الإنشاء والفحص بالقواعد، الإيقاف، العرض، والإحالات.

- الوصفة الواحدة = دواء واحد.
- إنشاء الوصفة = إرسالها للصيدلي (الحالة الأولى «بانتظار الصيدلي» دائمًا).
- يُرفض الإنشاء إذا كانت حالة حساسية المريض «لم تُسجَّل».
- الإيقاف والإحالات من صلاحية الطبيب الواصف فقط.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from . import rules as R
from .access import CLINICAL, read_as
from .audit import ActionResult, Ctx, run_action
from .auth import Session, require_user
from .db import db_now
from .doses import compute_status, dose_rows, is_late_documentation, timing_flag
from .errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from .locking import lock_row
from .reference import ConfigMissing, dose_text, get_policies, parse_dose, require_policies
from .timefmt import UTC, fmt_utc, parse_utc

DOCTOR = frozenset({"doctor"})
REASON_MAX = 500


def _text_required(value, field: str, label: str) -> str:
    v = " ".join((value or "").split())
    if not v:
        raise ValidationFailed(f"{label} مطلوب", details={"field": field})
    if len(v) > REASON_MAX:
        raise ValidationFailed(f"{label} أطول من {REASON_MAX} حرفًا", details={"field": field})
    return v


def _rx_row(conn, rx_id: int) -> dict:
    r = conn.execute(text("SELECT * FROM prescriptions WHERE id = :x"), {"x": rx_id}).mappings().first()
    if r is None:
        raise NotFound("الوصفة غير موجودة", entity_type="prescription", entity_id=str(rx_id))
    return dict(r)


# ---------------------------------------------------------------- الإنشاء

def create_prescription(ctx: Ctx, session: Session, *, patient_id: int, medication_id: int, dose,
                        frequency_id: int, start_at: datetime, duration_days) -> dict:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, DOCTOR)
        pol = require_policies(conn, "max_treatment_days")
        patient = conn.execute(text("SELECT id, mrn, allergy_status FROM patients WHERE id = :p"),
                               {"p": patient_id}).mappings().first()
        if patient is None:
            raise NotFound("المريض غير موجود", entity_type="patient", entity_id=str(patient_id))
        if patient["allergy_status"] == "not_recorded":
            raise ValidationFailed("لا يمكن إرسال الوصفة: حالة حساسية المريض «لم تُسجَّل». "
                                   "يجب أن يستكملها موظف التسجيل أولًا.",
                                   code="allergy_not_recorded", entity_type="patient", entity_id=str(patient_id))
        rs = R.active_ruleset_id(conn)
        if rs is None:
            raise ConfigMissing("لا توجد مجموعة قواعد محمّلة؛ لا يمكن فحص الوصفة. "
                                "تُحمَّل القواعد بعد اعتمادها سريريًا.", details={"missing": "ruleset"})
        kind = R.ruleset_kind_of(conn, rs)
        if not R.kind_allowed(kind, ctx):
            raise ConfigMissing("مجموعة القواعد المحمّلة من نوع لا يُسمح باستخدامه في هذه البيئة "
                                f"({kind}). لا يمكن فحص الوصفة.", code="ruleset_kind_not_allowed",
                                details={"kind": kind, "env": ctx.env})
        med = conn.execute(text("SELECT * FROM medications WHERE id = :m"), {"m": medication_id}).mappings().first()
        if med is None:
            raise ValidationFailed("الدواء غير موجود في القائمة المعتمدة للاختبار", details={"field": "medication"})
        blockers = R.blocking_incomplete_rules(conn, rs, medication_id)
        if blockers:
            raise ConfigMissing("لا يمكن فحص هذا الدواء: توجد قواعد ناقصة تمسّه ولم تُعتمد بعد ("
                                + "، ".join(b["code"] for b in blockers) + ")",
                                code="rule_incomplete", details={"incomplete_rules": blockers})
        freq = conn.execute(text(
            "SELECT f.* FROM frequencies f JOIN medication_frequencies mf ON mf.frequency_id = f.id"
            " WHERE f.id = :f AND mf.medication_id = :m"), {"f": frequency_id, "m": medication_id}).mappings().first()
        if freq is None:
            raise ValidationFailed("التكرار غير مسموح لهذا الدواء", details={"field": "frequency"})
        d = parse_dose(dose)
        lo, hi = parse_dose(med["dose_min"]), parse_dose(med["dose_max"])
        if not (lo <= d <= hi):
            raise ValidationFailed(f"الجرعة خارج نطاق الاختبار المعتمد لهذا الدواء ({med['dose_min']}–"
                                   f"{med['dose_max']} {med['unit']})", details={"field": "dose"})
        try:
            days = int(str(duration_days).strip())
        except ValueError:
            raise ValidationFailed("مدة العلاج يجب أن تكون عددًا صحيحًا من الأيام", details={"field": "duration"})
        max_days = int(pol["max_treatment_days"])
        if not (1 <= days <= max_days):
            raise ValidationFailed(f"مدة العلاج يجب أن تكون بين 1 و{max_days} يومًا", details={"field": "duration"})
        if not isinstance(start_at, datetime) or start_at.tzinfo is None:
            raise ValidationFailed("وقت بداية العلاج غير صالح", details={"field": "start_at"})
        now = parse_utc(db_now(conn)).replace(second=0, microsecond=0)
        if start_at.astimezone(UTC) < now:
            raise ValidationFailed("بداية العلاج لا يمكن أن تكون في الماضي", details={"field": "start_at"})
        start_s = fmt_utc(start_at)
        end_s = fmt_utc(start_at + timedelta(days=days))
        rx_id = conn.execute(text(
            "INSERT INTO prescriptions (patient_id, medication_id, dose, frequency_id, start_at, end_at,"
            " prescriber_id, ruleset_version_id) VALUES (:p, :m, :d, :f, :s, :e, :u, :rs) RETURNING id"),
            {"p": patient_id, "m": medication_id, "d": dose_text(d), "f": frequency_id, "s": start_s,
             "e": end_s, "u": user["id"], "rs": rs}).scalar_one()
        cands = R.candidates(conn, ruleset_id=rs, patient_id=patient_id, medication_id=medication_id,
                             start_at=start_s, end_at=end_s, exclude_rx_id=rx_id)
        R.insert_alerts(conn, rx_id, cands)
        summary = {"prescription_id": rx_id, "patient_mrn": patient["mrn"], "medication": med["name"],
                   "dose": dose_text(d), "frequency": freq["code"], "start_at": start_s, "end_at": end_s,
                   "ruleset_version_id": rs,
                   "alerts": [{"code": c.code, "severity": c.severity, "detail": c.detail} for c in cands]}
        return ActionResult(value=summary, entity_type="prescription", entity_id=str(rx_id), details=summary)

    return run_action(ctx, session.actor(), "rx.create", fn)


# ---------------------------------------------------------------- الإيقاف

def stop_prescription(ctx: Ctx, session: Session, rx_id: int, *, reason) -> None:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, DOCTOR)
        lock_row(conn, "prescriptions", rx_id)
        rx = _rx_row(conn, rx_id)
        if rx["prescriber_id"] != user["id"]:
            raise PermissionDenied("إيقاف الوصفة من صلاحية الطبيب الواصف فقط.", code="not_prescriber",
                                   entity_type="prescription", entity_id=str(rx_id))
        if rx["status"] not in ("awaiting_pharmacist", "approved"):
            raise Conflict("لا يمكن إيقاف وصفة حالتها نهائية.", entity_type="prescription", entity_id=str(rx_id))
        why = _text_required(reason, "reason", "سبب الإيقاف")
        conn.execute(text("INSERT INTO prescription_stops (prescription_id, stopped_by, reason)"
                          " VALUES (:x, :u, :r)"), {"x": rx_id, "u": user["id"], "r": why})
        conn.execute(text("UPDATE prescriptions SET status = 'stopped' WHERE id = :x"), {"x": rx_id})
        return ActionResult(entity_type="prescription", entity_id=str(rx_id),
                            details={"from_status": rx["status"], "reason": why})

    run_action(ctx, session.actor(), "rx.stop", fn)


# ---------------------------------------------------------------- العرض

RX_LIST_SQL = (
    "SELECT rx.id, rx.status, rx.dose, rx.start_at, rx.end_at, rx.created_at, rx.prescriber_id,"
    " p.id AS patient_id, p.mrn, p.full_name AS patient_name,"
    " m.name AS medication, m.unit, f.label AS frequency, u.full_name AS prescriber_name,"
    " (SELECT count(*) FROM alerts a WHERE a.prescription_id = rx.id) AS alert_count,"
    " (SELECT count(*) FROM alerts a WHERE a.prescription_id = rx.id AND a.severity = 'critical') AS critical_count"
    " FROM prescriptions rx JOIN patients p ON p.id = rx.patient_id JOIN medications m ON m.id = rx.medication_id"
    " JOIN frequencies f ON f.id = rx.frequency_id JOIN users u ON u.id = rx.prescriber_id")


def display_status(rx: dict, now: datetime) -> str:
    if rx["status"] == "approved" and parse_utc(rx["end_at"]) <= now:
        return "ended"
    return rx["status"]


def list_prescriptions(ctx: Ctx, session: Session, *, mine: bool = False, status: str | None = None,
                       patient_id: int | None = None) -> list[dict]:
    def fn(conn, user):
        where, params = [], {}
        if mine:
            where.append("rx.prescriber_id = :u")
            params["u"] = user["id"]
        if status:
            where.append("rx.status = :s")
            params["s"] = status
        if patient_id:
            where.append("rx.patient_id = :p")
            params["p"] = patient_id
        sql = RX_LIST_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY rx.id DESC"
        now = parse_utc(db_now(conn))
        rows = [dict(r) for r in conn.execute(text(sql), params).mappings()]
        for r in rows:
            r["display_status"] = display_status(r, now)
        return rows
    return read_as(ctx, session, CLINICAL, fn, "rx.read")


def detail(conn, rx_id: int) -> dict:
    rx = _rx_row(conn, rx_id)
    now = parse_utc(db_now(conn))
    out = dict(rx)
    out["patient"] = dict(conn.execute(text("SELECT id, mrn, full_name, age, allergy_status FROM patients"
                                            " WHERE id = :p"), {"p": rx["patient_id"]}).mappings().one())
    out["patient"]["allergies"] = [r[0] for r in conn.execute(text(
        "SELECT a.name FROM patient_allergies pa JOIN allergens a ON a.id = pa.allergen_id"
        " WHERE pa.patient_id = :p AND pa.removed_at IS NULL ORDER BY a.name"), {"p": rx["patient_id"]})]
    out["medication"] = dict(conn.execute(text("SELECT * FROM medications WHERE id = :m"),
                                          {"m": rx["medication_id"]}).mappings().one())
    out["frequency"] = dict(conn.execute(text("SELECT * FROM frequencies WHERE id = :f"),
                                         {"f": rx["frequency_id"]}).mappings().one())
    out["prescriber"] = dict(conn.execute(text("SELECT id, username, full_name FROM users WHERE id = :u"),
                                          {"u": rx["prescriber_id"]}).mappings().one())
    out["display_status"] = display_status(rx, now)
    out["alerts"] = alerts_for(conn, rx_id)
    out["incoming_alerts"] = incoming_alerts(conn, rx_id)
    rev = conn.execute(text("SELECT r.*, u.full_name AS pharmacist_name FROM pharmacist_reviews r"
                            " JOIN users u ON u.id = r.pharmacist_id WHERE r.prescription_id = :x"),
                       {"x": rx_id}).mappings().first()
    out["review"] = dict(rev) if rev else None
    stop = conn.execute(text("SELECT s.*, u.full_name AS stopped_by_name FROM prescription_stops s"
                             " JOIN users u ON u.id = s.stopped_by WHERE s.prescription_id = :x"),
                        {"x": rx_id}).mappings().first()
    out["stop"] = dict(stop) if stop else None
    pol = get_policies(conn)
    window = int(pol["dose_window_minutes"]) if "dose_window_minutes" in pol else None
    doses = dose_rows(conn, rx_id)
    for d in doses:
        d["status"] = compute_status(d, stopped_at=stop["stopped_at"] if stop else None,
                                     window_minutes=window, now=now)
        if d.get("adm_id") and window is not None:
            d["late_documentation"] = is_late_documentation(d["scheduled_at"], d["documented_at"], window)
            if d["outcome"] == "given":
                d["timing"] = timing_flag(d["scheduled_at"], d["administered_at_reported"], window)
    out["doses"] = doses
    out["window_minutes"] = window
    return out


def alerts_for(conn, rx_id: int) -> list[dict]:
    rows = conn.execute(text(
        "SELECT a.*, rv.code, rv.version, rv.rule_type, rv.resolution_policy, rv.existing_rx_policy,"
        " rv.source_note, rs.is_synthetic, rs.kind AS ruleset_kind,"
        " rr.id AS resolution_id, rr.note AS resolution_note, rr.created_at AS resolved_at,"
        " ru.full_name AS resolved_by, ak.created_at AS acknowledged_at, au.full_name AS acknowledged_by,"
        " al.name AS allergen_name, orx_m.name AS related_medication"
        " FROM alerts a JOIN rule_versions rv ON rv.id = a.rule_version_id"
        " JOIN ruleset_versions rs ON rs.id = rv.ruleset_version_id"
        " LEFT JOIN alert_resolutions rr ON rr.alert_id = a.id LEFT JOIN users ru ON ru.id = rr.pharmacist_id"
        " LEFT JOIN alert_acknowledgments ak ON ak.alert_id = a.id LEFT JOIN users au ON au.id = ak.pharmacist_id"
        " LEFT JOIN patient_allergies pa ON pa.id = a.related_allergy_id LEFT JOIN allergens al ON al.id = pa.allergen_id"
        " LEFT JOIN prescriptions orx ON orx.id = a.related_prescription_id"
        " LEFT JOIN medications orx_m ON orx_m.id = orx.medication_id"
        " WHERE a.prescription_id = :x ORDER BY CASE a.severity WHEN 'critical' THEN 0 ELSE 1 END, a.id"),
        {"x": rx_id}).mappings().all()
    out = []
    for r in rows:
        a = dict(r)
        a["requirements"] = [dict(q) for q in conn.execute(text(
            "SELECT q.id, q.seq, q.text, q.evidence, i.confirmed, i.text_value"
            " FROM rule_resolution_requirements q LEFT JOIN alert_resolution_items i"
            " ON i.requirement_id = q.id AND i.resolution_id = :res WHERE q.rule_version_id = :rv ORDER BY q.seq"),
            {"rv": a["rule_version_id"], "res": a["resolution_id"] or -1}).mappings()]
        a["state"] = alert_state(a)
        out.append(a)
    return out


def alert_state(a: dict) -> str:
    """resolved | acknowledged | needs_resolution | return_only | needs_ack"""
    if a["severity"] == "critical":
        if a["resolution_policy"] == "return_only":
            return "return_only"
        return "resolved" if a["resolution_id"] else "needs_resolution"
    return "acknowledged" if a["acknowledged_at"] else "needs_ack"


def incoming_alerts(conn, rx_id: int) -> list[dict]:
    """تنبيهات على وصفات أحدث تشير إلى هذه الوصفة (تؤثر في جرعاتها حسب سياسة القاعدة)."""
    rows = conn.execute(text(
        "SELECT a.id, a.prescription_id, a.severity, a.alert_text, rv.code, rv.existing_rx_policy,"
        " rv.resolution_policy, rx.status AS other_status, m.name AS other_medication,"
        " (SELECT count(*) FROM alert_resolutions rr WHERE rr.alert_id = a.id) AS resolved"
        " FROM alerts a JOIN rule_versions rv ON rv.id = a.rule_version_id"
        " JOIN prescriptions rx ON rx.id = a.prescription_id JOIN medications m ON m.id = rx.medication_id"
        " WHERE a.related_prescription_id = :x ORDER BY a.id"), {"x": rx_id}).mappings().all()
    return [dict(r) for r in rows]


def get_detail(ctx: Ctx, session: Session, rx_id: int) -> dict:
    return read_as(ctx, session, CLINICAL, lambda conn, user: detail(conn, rx_id), "rx.read")


def rx_audit_trail(ctx: Ctx, session: Session, rx_id: int) -> list[dict]:
    """سجل الوصفة: قيود السجل المرتبطة بها وبجرعاتها وتنبيهاتها."""
    def fn(conn, user):
        alert_ids = [str(r[0]) for r in conn.execute(text("SELECT id FROM alerts WHERE prescription_id=:x"),
                                                     {"x": rx_id})]
        dose_ids = [str(r[0]) for r in conn.execute(text("SELECT id FROM scheduled_doses WHERE prescription_id=:x"),
                                                    {"x": rx_id})]
        conds = ["(entity_type = 'prescription' AND entity_id = :rx)"]
        params = {"rx": str(rx_id)}
        if alert_ids:
            conds.append("(entity_type = 'alert' AND entity_id IN (" + ",".join(f"'{i}'" for i in alert_ids) + "))")
        if dose_ids:
            conds.append("(entity_type = 'dose' AND entity_id IN (" + ",".join(f"'{i}'" for i in dose_ids) + "))")
        rows = conn.execute(text("SELECT seq, occurred_at, actor_username, actor_role, action, outcome, details"
                                 " FROM audit_log WHERE " + " OR ".join(conds) + " ORDER BY seq"), params).mappings()
        return [dict(r) | {"details": json.loads(r["details"])} for r in rows]
    return read_as(ctx, session, CLINICAL, fn, "rx.audit_read")


# ---------------------------------------------------------------- الإحالات

def list_referrals(ctx: Ctx, session: Session, *, open_only: bool = True) -> list[dict]:
    def fn(conn, user):
        sql = ("SELECT rf.id, rf.created_at, rf.note, ad.reason_text, ad.documented_at, r.label AS reason,"
               " d.dose_number, d.scheduled_at, d.planned_dose, rx.id AS prescription_id, rx.prescriber_id,"
               " rx.status AS rx_status, p.mrn, p.full_name AS patient_name, m.name AS medication, m.unit,"
               " nu.full_name AS nurse_name, rc.action AS closure_action, rc.note AS closure_note,"
               " rc.created_at AS closed_at, rc.new_prescription_id"
               " FROM referrals rf JOIN administrations ad ON ad.id = rf.administration_id"
               " JOIN not_given_reasons r ON r.id = ad.not_given_reason_id"
               " JOIN scheduled_doses d ON d.id = ad.scheduled_dose_id"
               " JOIN prescriptions rx ON rx.id = d.prescription_id JOIN patients p ON p.id = rx.patient_id"
               " JOIN medications m ON m.id = rx.medication_id JOIN users nu ON nu.id = rf.created_by"
               " LEFT JOIN referral_closures rc ON rc.referral_id = rf.id")
        where, params = [], {}
        if user["role"] == "doctor":
            where.append("rx.prescriber_id = :u")
            params["u"] = user["id"]
        if open_only:
            where.append("rc.id IS NULL")
        sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY rf.id DESC"
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]
    return read_as(ctx, session, CLINICAL, fn, "referral.read")


def close_referral(ctx: Ctx, session: Session, referral_id: int, *, action: str,
                   new_prescription_id: int | None = None, note=None) -> None:
    """إغلاق الإحالة يوثّق اطلاع الطبيب وقراره فقط: لا يغيّر حالة الجرعة (تبقى «لم تُعطَ»)."""
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, DOCTOR)
        ref = conn.execute(text(
            "SELECT rf.id, rx.id AS rx_id, rx.prescriber_id, rx.patient_id, rx.status"
            " FROM referrals rf JOIN administrations ad ON ad.id = rf.administration_id"
            " JOIN scheduled_doses d ON d.id = ad.scheduled_dose_id JOIN prescriptions rx ON rx.id = d.prescription_id"
            " WHERE rf.id = :r"), {"r": referral_id}).mappings().first()
        if ref is None:
            raise NotFound("الإحالة غير موجودة", entity_type="referral", entity_id=str(referral_id))
        if ref["prescriber_id"] != user["id"]:
            raise PermissionDenied("إغلاق الإحالة من صلاحية الطبيب الواصف فقط.", code="not_prescriber",
                                   entity_type="referral", entity_id=str(referral_id))
        if conn.execute(text("SELECT 1 FROM referral_closures WHERE referral_id = :r"), {"r": referral_id}).first():
            raise Conflict("أُغلقت هذه الإحالة مسبقًا", entity_type="referral", entity_id=str(referral_id))
        if action not in ("stopped", "new_prescription", "no_action"):
            raise ValidationFailed("إجراء غير معروف", details={"field": "action"})
        clean_note = " ".join((note or "").split()) or None
        if action == "no_action":
            clean_note = _text_required(note, "note", "سبب عدم اتخاذ إجراء")
        if action == "stopped" and ref["status"] != "stopped":
            raise ValidationFailed("الوصفة لم تُوقف بعد. أوقفها أولًا ثم أغلق الإحالة.", details={"field": "action"})
        if action == "new_prescription":
            new = conn.execute(text("SELECT patient_id, created_at FROM prescriptions WHERE id = :n"),
                               {"n": new_prescription_id}).mappings().first()
            if new is None or new["patient_id"] != ref["patient_id"] or new_prescription_id == ref["rx_id"]:
                raise ValidationFailed("رقم الوصفة الجديدة غير صالح لهذا المريض", details={"field": "new_prescription_id"})
        else:
            new_prescription_id = None
        conn.execute(text("INSERT INTO referral_closures (referral_id, doctor_id, action, new_prescription_id, note)"
                          " VALUES (:r, :u, :a, :n, :t)"),
                     {"r": referral_id, "u": user["id"], "a": action, "n": new_prescription_id, "t": clean_note})
        return ActionResult(entity_type="referral", entity_id=str(referral_id),
                            details={"action": action, "new_prescription_id": new_prescription_id,
                                     "note": clean_note, "prescription_id": ref["rx_id"]})

    run_action(ctx, session.actor(), "referral.close", fn)
