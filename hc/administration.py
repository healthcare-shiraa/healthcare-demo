"""توثيق الممرض لإعطاء الجرعة أو عدم إعطائها.

ما يفرضه الخادم:
- تحقق الممرض: رقم المريض المُدخل يطابق المريض، وتأكيد الدواء وقرار الصيدلي.
- تسجيل واحد لكل جرعة مقررة (قفل السطر + إعادة الفحص + قيد فريد).
- «أُعطيت» يُرفض إذا وُجد تنبيه حرج غير محلول يمنع الإعطاء، أو تداخل/حساسية جديدة غير موثقة
  بمجموعة القواعد المثبتة على الوصفة. أما «لم تُعطَ» فيُقبل دائمًا (توثيق واقعة عدم الإعطاء).
- الجرعة الفعلية يجب أن تساوي المقررة لتُسجَّل «أُعطيت» (تعديل الجرعات خارج النطاق).
- وقت الإعطاء قيمة يدخلها الممرض، ووقت التوثيق يضعه الخادم/قاعدة البيانات؛ يُحفظان منفصلين.
- التوثيق بعد نهاية النافذة مقبول بسبب مكتوب، ويُوسم «توثيق متأخر»، ضمن المهلة المعتمدة.
- سياسة الجرعة الفائتة (strict/warn) والنافذة والمهلة إعدادات يعتمدها الفريق؛ بدونها تُرفض العملية.
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
from .doses import compute_status, is_late_documentation
from .errors import Conflict, DomainError, NotFound, ValidationFailed
from .labels import SEVERITY
from .locking import lock_row
from .reference import dose_text, get_policies, parse_dose, require_policies
from .timefmt import UTC, fmt_utc, parse_utc

NURSE = frozenset({"nurse"})
TEXT_MAX = 500


class Blocked(DomainError):
    outcome = "denied"
    code = "blocked_critical_alert"


def _clean(v) -> str | None:
    t = " ".join((v or "").split())
    if t and len(t) > TEXT_MAX:
        raise ValidationFailed(f"النص أطول من {TEXT_MAX} حرفًا")
    return t or None


def safety_check(conn, rx: dict) -> tuple[list[str], list[str]]:
    """يعيد (موانع، تحذيرات) لإعطاء جرعة من هذه الوصفة الآن."""
    blocks, warns = [], []
    # 1) تنبيهات الوصفة نفسها (يُفترض أنها سُوّيت عند الاعتماد؛ فحص دفاعي)
    for a in conn.execute(text(
            "SELECT a.id, rv.code, rv.resolution_policy FROM alerts a JOIN rule_versions rv ON rv.id = a.rule_version_id"
            " WHERE a.prescription_id = :x AND a.severity = 'critical'"
            " AND NOT EXISTS (SELECT 1 FROM alert_resolutions r WHERE r.alert_id = a.id)"), {"x": rx["id"]}).mappings():
        blocks.append(f"تنبيه حرج غير محلول على هذه الوصفة ({a['code']})")
    # 2) تنبيهات على وصفات أحدث تشير إلى هذه الوصفة — حسب سياسة القاعدة للوصفة القائمة
    for a in conn.execute(text(
            "SELECT a.id, a.prescription_id, rv.code, rv.existing_rx_policy, m.name AS med FROM alerts a"
            " JOIN rule_versions rv ON rv.id = a.rule_version_id JOIN prescriptions o ON o.id = a.prescription_id"
            " JOIN medications m ON m.id = o.medication_id"
            " WHERE a.related_prescription_id = :x AND a.severity = 'critical'"
            " AND o.status IN ('awaiting_pharmacist','approved')"
            " AND NOT EXISTS (SELECT 1 FROM alert_resolutions r WHERE r.alert_id = a.id)"), {"x": rx["id"]}).mappings():
        msg = (f"تنبيه حرج غير محلول ({a['code']}) على الوصفة رقم {a['prescription_id']} ({a['med']}) "
               f"يشير إلى هذه الوصفة")
        (blocks if a["existing_rx_policy"] == "block_until_resolved" else warns).append(msg)
    # 3) إعادة الفحص بمجموعة القواعد المثبتة على الوصفة، على بيانات المريض الحالية
    cands = R.candidates(conn, ruleset_id=rx["ruleset_version_id"], patient_id=rx["patient_id"],
                         medication_id=rx["medication_id"], start_at=rx["start_at"], end_at=rx["end_at"],
                         exclude_rx_id=rx["id"])
    existing = R.existing_alert_keys(conn, rx["id"])
    for c in cands:
        if c.key not in existing:
            msg = f"{SEVERITY[c.severity]}: {c.code} — {c.detail} (غير موثّق؛ يلزم تواصل مع الطبيب الواصف)"
            (blocks if c.severity == "critical" else warns).append(msg)
    return blocks, warns


def record_administration(ctx: Ctx, session: Session, dose_id: int, *, verified_mrn, verified_medication: bool,
                          verified_pharmacist_decision: bool, outcome: str, actual_dose=None,
                          administered_at: datetime | None = None, not_given_reason_id: int | None = None,
                          reason_text=None, late_reason=None, create_referral: bool = False,
                          referral_note=None) -> dict:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, NURSE)
        pol = require_policies(conn, "dose_window_minutes", "late_documentation_max_hours",
                               "missed_dose_sequence_policy")
        window = timedelta(minutes=int(pol["dose_window_minutes"]))
        lock_row(conn, "scheduled_doses", dose_id)
        dose = dict(conn.execute(text("SELECT * FROM scheduled_doses WHERE id = :d"), {"d": dose_id}).mappings().one())
        prior = conn.execute(text(
            "SELECT ad.documented_at, u.full_name FROM administrations ad JOIN users u ON u.id = ad.nurse_id"
            " WHERE ad.scheduled_dose_id = :d"), {"d": dose_id}).mappings().first()
        if prior:
            raise Conflict(f"وُثّقت هذه الجرعة مسبقًا بواسطة {prior['full_name']}.", code="already_documented",
                           entity_type="dose", entity_id=str(dose_id), details={"documented_at": prior["documented_at"]})
        rx = dict(conn.execute(text("SELECT * FROM prescriptions WHERE id = :x"),
                               {"x": dose["prescription_id"]}).mappings().one())
        patient = conn.execute(text("SELECT mrn FROM patients WHERE id = :p"), {"p": rx["patient_id"]}).scalar_one()
        stop = conn.execute(text("SELECT stopped_at FROM prescription_stops WHERE prescription_id = :x"),
                            {"x": rx["id"]}).scalar_one_or_none()
        if rx["status"] not in ("approved", "stopped") or (rx["status"] == "stopped" and not conn.execute(
                text("SELECT 1 FROM pharmacist_reviews WHERE prescription_id = :x AND decision = 'approved'"),
                {"x": rx["id"]}).first()):
            raise ValidationFailed("لا يمكن توثيق جرعة لوصفة لم يعتمدها الصيدلي.", code="not_approved",
                                   entity_type="dose", entity_id=str(dose_id))
        sched = parse_utc(dose["scheduled_at"])
        if stop and sched > parse_utc(stop):
            raise ValidationFailed("هذه الجرعة ملغاة لأن الوصفة أُوقفت قبل موعدها.", code="cancelled_by_stop",
                                   entity_type="dose", entity_id=str(dose_id))
        # تحقق الممرض
        if (verified_mrn or "").strip().upper() != patient.upper():
            raise ValidationFailed("رقم المريض المُدخل لا يطابق المريض صاحب الوصفة. تحقق من هوية المريض.",
                                   code="patient_mismatch", entity_type="dose", entity_id=str(dose_id))
        if verified_medication is not True or verified_pharmacist_decision is not True:
            raise ValidationFailed("يجب تأكيد التحقق من الدواء ومن قرار الصيدلي قبل التوثيق.",
                                   code="verification_missing", entity_type="dose", entity_id=str(dose_id))
        now = parse_utc(db_now(conn))
        if now < sched - window:
            raise ValidationFailed("لم يحن موعد هذه الجرعة بعد.", code="not_due", entity_type="dose",
                                   entity_id=str(dose_id))
        warnings: list[str] = []
        # تسلسل الجرعات
        if dose["dose_number"] > 1:
            prev = conn.execute(text(
                "SELECT d.id, d.dose_number, d.scheduled_at, ad.id AS adm FROM scheduled_doses d"
                " LEFT JOIN administrations ad ON ad.scheduled_dose_id = d.id"
                " WHERE d.prescription_id = :x AND d.dose_number < :n AND ad.id IS NULL ORDER BY d.dose_number"),
                {"x": rx["id"], "n": dose["dose_number"]}).mappings().all()
            undocumented = [p["dose_number"] for p in prev
                            if not (stop and parse_utc(p["scheduled_at"]) > parse_utc(stop))]
            if undocumented:
                msg = "جرعات سابقة غير موثقة: " + "، ".join(str(n) for n in undocumented)
                if pol["missed_dose_sequence_policy"] == "strict":
                    raise ValidationFailed(msg + ". السياسة المعتمدة تمنع توثيق الجرعة التالية قبل توثيقها.",
                                           code="previous_dose_undocumented", entity_type="dose",
                                           entity_id=str(dose_id), details={"undocumented": undocumented})
                warnings.append(msg)
        params = {"d": dose_id, "u": user["id"], "o": outcome, "mrn": verified_mrn.strip().upper(),
                  "vm": True, "vp": True, "ad": None, "at": None, "r": None, "rt": None}
        if outcome == "given":
            blocks, warns = safety_check(conn, rx)
            if blocks:
                raise Blocked("يُمنع توثيق الإعطاء: " + " | ".join(blocks), entity_type="dose",
                              entity_id=str(dose_id), details={"blocks": blocks})
            warnings.extend(warns)
            actual = parse_dose(actual_dose)
            if actual != parse_dose(dose["planned_dose"]):
                raise ValidationFailed("الجرعة الفعلية تختلف عن المقررة. لا تُسجَّل «أُعطيت»؛ "
                                       "استخدم «لم تُعطَ» مع السبب، ويمكن إحالة الحالة للطبيب.",
                                       code="dose_mismatch", entity_type="dose", entity_id=str(dose_id),
                                       details={"planned": dose["planned_dose"], "actual": dose_text(actual)})
            if not isinstance(administered_at, datetime) or administered_at.tzinfo is None:
                raise ValidationFailed("وقت الإعطاء الفعلي مطلوب", details={"field": "administered_at"})
            at = administered_at.astimezone(UTC)
            if at > now:
                raise ValidationFailed("وقت الإعطاء لا يمكن أن يكون في المستقبل", details={"field": "administered_at"})
            if at < parse_utc(rx["start_at"]) - window:
                raise ValidationFailed("وقت الإعطاء قبل بداية الوصفة", details={"field": "administered_at"})
            if stop and at >= parse_utc(stop):
                raise ValidationFailed("وقت الإعطاء بعد إيقاف الوصفة", details={"field": "administered_at"})
            params.update(ad=dose_text(actual), at=fmt_utc(at))
        elif outcome == "not_given":
            reason = conn.execute(text("SELECT * FROM not_given_reasons WHERE id = :r"),
                                  {"r": not_given_reason_id}).mappings().first()
            if reason is None:
                raise ValidationFailed("سبب عدم الإعطاء مطلوب من القائمة", details={"field": "reason"})
            rt = _clean(reason_text)
            if reason["requires_text"] and not rt:
                raise ValidationFailed("هذا السبب يتطلب توضيحًا مكتوبًا", details={"field": "reason_text"})
            params.update(r=reason["id"], rt=rt)
        else:
            raise ValidationFailed("نتيجة غير معروفة", details={"field": "outcome"})
        params["lr"] = _clean(late_reason)
        params["w"] = json.dumps(warnings, ensure_ascii=False)
        # documented_at لا يُرسل من التطبيق: تضعه قاعدة البيانات
        adm_id = conn.execute(text(
            "INSERT INTO administrations (scheduled_dose_id, nurse_id, outcome, actual_dose, administered_at_reported,"
            " not_given_reason_id, reason_text, late_reason, verified_patient_mrn, verified_medication,"
            " verified_pharmacist_decision, warnings) VALUES (:d, :u, :o, :ad, :at, :r, :rt, :lr, :mrn, :vm, :vp, :w)"
            " RETURNING id"), params).scalar_one()
        documented = conn.execute(text("SELECT documented_at FROM administrations WHERE id = :a"),
                                  {"a": adm_id}).scalar_one()
        late = is_late_documentation(dose["scheduled_at"], documented, int(pol["dose_window_minutes"]))
        if late:
            if not params["lr"]:
                raise ValidationFailed("التوثيق بعد نهاية النافذة الزمنية يتطلب ذكر سبب التأخير.",
                                       code="late_reason_required", details={"field": "late_reason"})
            mx = pol["late_documentation_max_hours"]
            if mx != "none" and parse_utc(documented) > sched + window + timedelta(hours=int(mx)):
                raise ValidationFailed(f"تجاوز المهلة المعتمدة للتوثيق المتأخر ({mx} ساعة).",
                                       code="late_limit_exceeded", entity_type="dose", entity_id=str(dose_id))
        ref_id = None
        if create_referral:
            if outcome != "not_given":
                raise ValidationFailed("الإحالة تُنشأ مع «لم تُعطَ» فقط")
            ref_id = conn.execute(text("INSERT INTO referrals (administration_id, created_by, note)"
                                       " VALUES (:a, :u, :n) RETURNING id"),
                                  {"a": adm_id, "u": user["id"], "n": _clean(referral_note)}).scalar_one()
        summary = {"prescription_id": rx["id"], "dose_number": dose["dose_number"], "outcome": outcome,
                   "administration_id": adm_id, "late_documentation": late, "warnings": warnings,
                   "referral_id": ref_id, "administered_at_reported": params["at"], "documented_at": documented}
        return ActionResult(value=summary, entity_type="dose", entity_id=str(dose_id), details=summary)

    return run_action(ctx, session.actor(), "dose.document", fn)


def dose_worklist(ctx: Ctx, session: Session, *, include_upcoming_hours: int | None = None) -> list[dict]:
    """جدول الإعطاء: جرعات الوصفات المعتمدة/الموقوفة غير الموثقة، مع حالتها المحسوبة."""
    def fn(conn, user):
        pol = get_policies(conn)
        window = int(pol["dose_window_minutes"]) if "dose_window_minutes" in pol else None
        now = parse_utc(db_now(conn))
        rows = conn.execute(text(
            "SELECT d.id, d.prescription_id, d.dose_number, d.scheduled_at, d.planned_dose,"
            " rx.status AS rx_status, rx.patient_id, p.mrn, p.full_name AS patient_name, p.allergy_status,"
            " m.name AS medication, m.unit, f.label AS frequency, s.stopped_at"
            " FROM scheduled_doses d JOIN prescriptions rx ON rx.id = d.prescription_id"
            " JOIN patients p ON p.id = rx.patient_id JOIN medications m ON m.id = rx.medication_id"
            " JOIN frequencies f ON f.id = rx.frequency_id"
            " LEFT JOIN prescription_stops s ON s.prescription_id = rx.id"
            " WHERE NOT EXISTS (SELECT 1 FROM administrations ad WHERE ad.scheduled_dose_id = d.id)"
            " ORDER BY d.scheduled_at, d.id")).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["status"] = compute_status(d, stopped_at=d["stopped_at"], window_minutes=window, now=now)
            if d["status"] == "cancelled":
                continue
            if d["status"] == "upcoming" and include_upcoming_hours is not None:
                if parse_utc(d["scheduled_at"]) > now + timedelta(hours=include_upcoming_hours):
                    continue
            out.append(d)
        return out
    return read_as(ctx, session, CLINICAL, fn, "dose.read")


def dose_context(ctx: Ctx, session: Session, dose_id: int) -> dict:
    """كل ما يحتاجه الممرض للتحقق قبل التوثيق، مع الموانع والتحذيرات الحالية."""
    def fn(conn, user):
        dose = conn.execute(text("SELECT * FROM scheduled_doses WHERE id = :d"), {"d": dose_id}).mappings().first()
        if dose is None:
            raise NotFound("الجرعة غير موجودة")
        rx = dict(conn.execute(text("SELECT * FROM prescriptions WHERE id = :x"),
                               {"x": dose["prescription_id"]}).mappings().one())
        blocks, warns = safety_check(conn, rx)
        return {"dose": dict(dose), "rx": rx, "blocks": blocks, "warnings": warns}
    return read_as(ctx, session, CLINICAL, fn, "dose.read")
