"""المرضى والحساسيات.

- رقم المريض HC-0001 يولّده النظام داخل المعاملة من عدّاد ذري، مع قيد فريد.
- row_version يمنع ضياع التعديلات: من يحفظ بنسخة قديمة يُرفض.
- حالة الحساسية إلزامية، وثلاث قيم: not_recorded / none_known / has_allergies.
  «لم تُسجَّل» لا تُفسَّر أبدًا على أنها «لا حساسية».
- تاريخ الحساسيات محفوظ: الإزالة لا تحذف السطر، بل توثّق من أزالها ومتى ولماذا
  (السبب إلزامي عند الإزالة). الحساسية الحالية = سطر لم تُسجَّل له إزالة.
"""
from __future__ import annotations

from sqlalchemy import text

from .audit import ActionResult, Actor, Ctx, record_rejection, run_action
from .auth import ALL_ROLES, Session, require_user
from .db import db_now
from .errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from .locking import lock_row

ALLERGY_STATUSES = {
    "not_recorded": "لم تُسجَّل بيانات الحساسية",
    "none_known": "لا توجد حساسية معروفة",
    "has_allergies": "توجد حساسية",
}
WRITE_ROLES = frozenset({"registration"})
READ_ROLES = ALL_ROLES
NAME_MAX = 100
REASON_MAX = 500


def _clean_name(full_name) -> str:
    name = " ".join((full_name or "").split())
    if not name:
        raise ValidationFailed("الاسم الافتراضي مطلوب", details={"field": "full_name"})
    if len(name) > NAME_MAX:
        raise ValidationFailed(f"الاسم أطول من {NAME_MAX} حرفًا", details={"field": "full_name"})
    return name


def _clean_age(age) -> int:
    bad = ValidationFailed("العمر يجب أن يكون عددًا صحيحًا", details={"field": "age"})
    if isinstance(age, bool):
        raise bad
    if isinstance(age, int):
        value = age
    else:
        s = str(age if age is not None else "").strip()
        if not s.isdigit():
            raise bad
        value = int(s)
    if value < 18:
        raise ValidationFailed("النموذج مخصص للمرضى البالغين (18 سنة فأكثر)", details={"field": "age"})
    return value


def _clean_allergies(conn, status, allergen_ids) -> list[int]:
    if status not in ALLERGY_STATUSES:
        raise ValidationFailed("حالة الحساسية مطلوبة", details={"field": "allergy_status"})
    ids = sorted({int(a) for a in (allergen_ids or [])})
    if status == "has_allergies" and not ids:
        raise ValidationFailed("اختر حساسية واحدة على الأقل، أو غيّر حالة الحساسية",
                               details={"field": "allergens"})
    if status != "has_allergies" and ids:
        raise ValidationFailed("لا يمكن اختيار حساسيات مع هذه الحالة", details={"field": "allergens"})
    if ids:
        found = {r[0] for r in conn.execute(
            text("SELECT id FROM allergens WHERE id IN (" + ",".join(str(i) for i in ids) + ")"))}
        missing = [i for i in ids if i not in found]
        if missing:
            raise ValidationFailed("حساسية غير موجودة في القائمة المعتمدة", details={"missing": missing})
    return ids


def _snapshot(conn, patient_id: int) -> dict:
    p = conn.execute(text(
        "SELECT id, mrn, full_name, age, allergy_status, row_version FROM patients WHERE id=:i"),
        {"i": patient_id}).mappings().first()
    if p is None:
        raise NotFound("المريض غير موجود", entity_type="patient", entity_id=str(patient_id))
    allergies = [r[0] for r in conn.execute(text(
        "SELECT allergen_id FROM patient_allergies WHERE patient_id=:i AND removed_at IS NULL"
        " ORDER BY allergen_id"), {"i": patient_id})]
    return {**dict(p), "allergen_ids": allergies}


def create_patient(ctx: Ctx, session: Session, *, full_name, age, allergy_status,
                   allergen_ids=None) -> dict:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, WRITE_ROLES)
        name = _clean_name(full_name)
        age_v = _clean_age(age)
        ids = _clean_allergies(conn, allergy_status, allergen_ids)
        n = conn.execute(text(
            "UPDATE counters SET value = value + 1 WHERE name = 'patient_mrn' RETURNING value")).scalar_one()
        mrn = f"HC-{n:04d}"
        pid = conn.execute(text(
            "INSERT INTO patients (mrn, full_name, age, allergy_status, created_by)"
            " VALUES (:m, :n, :a, :s, :u) RETURNING id"),
            {"m": mrn, "n": name, "a": age_v, "s": allergy_status, "u": user["id"]}).scalar_one()
        for a in ids:
            conn.execute(text("INSERT INTO patient_allergies (patient_id, allergen_id, recorded_by)"
                              " VALUES (:p, :a, :u)"), {"p": pid, "a": a, "u": user["id"]})
        after = _snapshot(conn, pid)
        return ActionResult(value=after, entity_type="patient", entity_id=str(pid),
                            details={"after": after})

    return run_action(ctx, session.actor(), "patient.create", fn)


def update_patient(ctx: Ctx, session: Session, patient_id: int, *, expected_version: int,
                   full_name, age) -> dict:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, WRITE_ROLES)
        lock_row(conn, "patients", patient_id)
        before = _snapshot(conn, patient_id)
        if before["row_version"] != expected_version:
            raise Conflict("عدّل مستخدم آخر بيانات هذا المريض بعد أن فتحتها. أعد فتح السجل ثم عدّل.",
                           entity_type="patient", entity_id=str(patient_id),
                           details={"expected_version": expected_version, "current_version": before["row_version"]})
        name = _clean_name(full_name)
        age_v = _clean_age(age)
        res = conn.execute(text(
            "UPDATE patients SET full_name=:n, age=:a, row_version=row_version+1, updated_by=:u, updated_at=:t"
            " WHERE id=:i AND row_version=:v"),
            {"n": name, "a": age_v, "u": user["id"], "t": db_now(conn), "i": patient_id, "v": expected_version})
        if res.rowcount != 1:  # حماية إضافية إن لم يكن القفل كافيًا
            raise Conflict("تعارض في التعديل. أعد المحاولة.", entity_type="patient", entity_id=str(patient_id))
        after = _snapshot(conn, patient_id)
        return ActionResult(value=after, entity_type="patient", entity_id=str(patient_id),
                            details={"before": before, "after": after})

    return run_action(ctx, session.actor(), "patient.update", fn)


def set_allergies(ctx: Ctx, session: Session, patient_id: int, *, expected_version: int,
                  allergy_status, allergen_ids=None, removal_reason: str | None = None) -> dict:
    def fn(conn) -> ActionResult:
        user = require_user(conn, session, WRITE_ROLES)
        lock_row(conn, "patients", patient_id)
        before = _snapshot(conn, patient_id)
        if before["row_version"] != expected_version:
            raise Conflict("عدّل مستخدم آخر بيانات هذا المريض بعد أن فتحتها. أعد فتح السجل ثم عدّل.",
                           entity_type="patient", entity_id=str(patient_id),
                           details={"expected_version": expected_version, "current_version": before["row_version"]})
        ids = _clean_allergies(conn, allergy_status, allergen_ids)
        reason = " ".join((removal_reason or "").split()) or None
        if reason and len(reason) > REASON_MAX:
            raise ValidationFailed(f"سبب الإزالة أطول من {REASON_MAX} حرفًا", details={"field": "removal_reason"})
        old = set(before["allergen_ids"])
        new = set(ids)
        removed = sorted(old - new)
        if removed and not reason:
            # قرار معتمد: سبب الإزالة إلزامي، ولا تُقبل قيمة فارغة أو مسافات فقط
            raise ValidationFailed("سبب إزالة الحساسية إلزامي عند إزالة حساسية مسجلة",
                                   entity_type="patient", entity_id=str(patient_id),
                                   details={"field": "removal_reason", "removed_allergen_ids": removed})
        now = db_now(conn)
        for a in removed:
            # لا حذف: توثيق الإزالة من الحالة الحالية مع بقاء السطر في التاريخ
            res = conn.execute(text(
                "UPDATE patient_allergies SET removed_by=:u, removed_at=:t, removal_reason=:r"
                " WHERE patient_id=:p AND allergen_id=:a AND removed_at IS NULL"),
                {"u": user["id"], "t": now, "r": reason, "p": patient_id, "a": a})
            if res.rowcount != 1:
                raise Conflict("تعذر توثيق إزالة الحساسية؛ أعد فتح السجل.",
                               entity_type="patient", entity_id=str(patient_id))
        for a in sorted(new - old):
            conn.execute(text("INSERT INTO patient_allergies (patient_id, allergen_id, recorded_by)"
                              " VALUES (:p, :a, :u)"), {"p": patient_id, "a": a, "u": user["id"]})
        conn.execute(text(
            "UPDATE patients SET allergy_status=:s, row_version=row_version+1, updated_by=:u, updated_at=:t"
            " WHERE id=:i"), {"s": allergy_status, "u": user["id"], "t": now, "i": patient_id})
        after = _snapshot(conn, patient_id)
        return ActionResult(value=after, entity_type="patient", entity_id=str(patient_id),
                            details={"before": before, "after": after, "removed_allergen_ids": removed,
                                     "added_allergen_ids": sorted(new - old), "removal_reason": reason})

    return run_action(ctx, session.actor(), "patient.set_allergies", fn)


# ---------- قراءة (بدون كتابة؛ لا تُسجَّل في السجل) ----------

def _read(ctx: Ctx, session: Session, fn, action: str = "patient.read"):
    try:
        with ctx.engine.connect() as conn:
            require_user(conn, session, READ_ROLES)
            return fn(conn)
    except PermissionDenied as e:
        # القراءة الناجحة لا تُسجَّل، لكن محاولة القراءة المرفوضة تُسجَّل
        actor = session.actor() if session else Actor(type="anonymous")
        e.audit_persisted = record_rejection(ctx, actor, action, e)
        raise


def list_patients(ctx: Ctx, session: Session) -> list[dict]:
    def fn(conn):
        rows = conn.execute(text(
            "SELECT id, mrn, full_name, age, allergy_status, row_version, created_at, updated_at"
            " FROM patients ORDER BY id")).mappings().all()
        return [dict(r) for r in rows]
    return _read(ctx, session, fn)


def get_patient(ctx: Ctx, session: Session, patient_id: int) -> dict:
    def fn(conn):
        snap = _snapshot(conn, patient_id)
        names = {r[0]: r[1] for r in conn.execute(text("SELECT id, name FROM allergens"))}
        snap["allergen_names"] = [names[a] for a in snap["allergen_ids"]]
        return snap
    return _read(ctx, session, fn)


def allergy_history(ctx: Ctx, session: Session, patient_id: int) -> list[dict]:
    """كل سطور الحساسية للمريض، الحالية والمُزالة، بالترتيب الزمني."""
    def fn(conn):
        _snapshot(conn, patient_id)  # يرفع NotFound إن لم يوجد المريض
        rows = conn.execute(text(
            "SELECT pa.id, pa.allergen_id, a.name AS allergen_name,"
            " pa.recorded_at, ru.username AS recorded_by,"
            " pa.removed_at, xu.username AS removed_by, pa.removal_reason"
            " FROM patient_allergies pa"
            " JOIN allergens a ON a.id = pa.allergen_id"
            " JOIN users ru ON ru.id = pa.recorded_by"
            " LEFT JOIN users xu ON xu.id = pa.removed_by"
            " WHERE pa.patient_id = :p ORDER BY pa.id"), {"p": patient_id}).mappings().all()
        return [dict(r) for r in rows]
    return _read(ctx, session, fn)


def list_allergens(ctx: Ctx, session: Session) -> list[dict]:
    return _read(ctx, session, lambda conn: [dict(r) for r in conn.execute(
        text("SELECT id, name FROM allergens ORDER BY name")).mappings().all()])
