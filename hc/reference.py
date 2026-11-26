"""البيانات المرجعية (الأدوية، التكرارات، أسباب عدم الإعطاء) والإعدادات التشغيلية.

كل هذه القيم تأتي من الفريق (أو من ملفات اختبار وهمية في بيئة test فقط).
لا توجد أي قيمة افتراضية في الكود: إذا نقص إعداد، تتوقف الوظيفة التي تحتاجه فقط،
وتظهر رسالة تسمّي الإعداد الناقص.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from .audit import ActionResult, Actor, Ctx, run_action
from .errors import ValidationFailed

POLICY_KEYS = {
    "dose_window_minutes": "النافذة الزمنية لتسجيل الجرعة (بالدقائق، قبل الموعد وبعده)",
    "late_documentation_max_hours": "المهلة القصوى للتوثيق المتأخر بعد نهاية النافذة (ساعات، أو none بلا حد)",
    "missed_dose_sequence_policy": "سياسة الجرعة الفائتة: strict يمنع التالية حتى التوثيق، warn يحذّر فقط",
    "max_treatment_days": "أقصى مدة علاج مسموحة في الوصفة (أيام)",
}


class ConfigMissing(ValidationFailed):
    code = "config_missing"


def validate_policy(key: str, value: str) -> str:
    v = (value or "").strip()
    if key not in POLICY_KEYS:
        raise ValidationFailed(f"إعداد غير معروف: {key}")
    if key in ("dose_window_minutes", "max_treatment_days"):
        if not v.isdigit() or int(v) <= 0:
            raise ValidationFailed(f"{key}: يجب أن يكون عددًا صحيحًا موجبًا")
    elif key == "late_documentation_max_hours":
        if v != "none" and not v.isdigit():
            raise ValidationFailed(f"{key}: عدد صحيح من الساعات أو none")
    elif key == "missed_dose_sequence_policy":
        if v not in ("strict", "warn"):
            raise ValidationFailed(f"{key}: strict أو warn")
    return v


def get_policies(conn) -> dict[str, str]:
    rows = conn.execute(text(
        "SELECT key, value FROM policy_settings p WHERE id = (SELECT max(id) FROM policy_settings q"
        " WHERE q.key = p.key)")).all()
    return {k: v for k, v in rows}


def require_policies(conn, *keys: str) -> dict[str, str]:
    pol = get_policies(conn)
    missing = [k for k in keys if k not in pol]
    if missing:
        raise ConfigMissing("هذه العملية تحتاج إعدادات تشغيلية لم تُعتمد بعد: "
                            + "، ".join(POLICY_KEYS[k] for k in missing),
                            details={"missing_settings": missing})
    return pol


def set_policy(ctx: Ctx, *, operator: str, key: str, value: str, synthetic: bool) -> None:
    """يُستدعى من سكربت الإدارة فقط. كل تغيير سطر جديد (التاريخ محفوظ).
    synthetic=True: قيمة وهمية (test) أو توضيحية (demo مع الإعداد الصريح) — غير معتمدة."""
    if synthetic and not (ctx.env == "test" or (ctx.env == "demo" and ctx.allow_illustrative)):
        raise ValidationFailed("القيم غير المعتمدة مسموحة في بيئة test، أو في demo مع HC_DEMO_ALLOW_ILLUSTRATIVE_RULES=true")
    actor = Actor(type="script", operator=(operator or "").strip() or None, username="set_policy")
    if not actor.operator:
        raise ValidationFailed("يجب تحديد اسم المنفّذ")

    def fn(conn) -> ActionResult:
        v = validate_policy(key, value)
        conn.execute(text("INSERT INTO policy_settings (key, value, operator, is_synthetic)"
                          " VALUES (:k, :v, :o, :s)"), {"k": key, "v": v, "o": actor.operator, "s": synthetic})
        return ActionResult(entity_type="policy", entity_id=key, details={"key": key, "value": v,
                                                                        "synthetic": synthetic})
    run_action(ctx, actor, "admin.policy_set", fn)


def parse_dose(value) -> Decimal:
    """الجرعة رقم عشري موجب. تُخزَّن نصًا بصيغة ثابتة حتى تكون المقارنة دقيقة."""
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise ValidationFailed("الجرعة يجب أن تكون رقمًا", details={"field": "dose"})
    if not d.is_finite() or d <= 0:
        raise ValidationFailed("الجرعة يجب أن تكون رقمًا موجبًا", details={"field": "dose"})
    return d


def dose_text(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def medications(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(text(
        "SELECT id, name, unit, dose_min, dose_max, is_synthetic FROM medications ORDER BY name")).mappings()]


def medication_frequencies(conn, medication_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(text(
        "SELECT f.id, f.code, f.label, f.interval_hours FROM frequencies f"
        " JOIN medication_frequencies mf ON mf.frequency_id = f.id"
        " WHERE mf.medication_id = :m ORDER BY f.interval_hours DESC"), {"m": medication_id}).mappings()]


def not_given_reasons(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(text(
        "SELECT id, code, label, requires_text FROM not_given_reasons ORDER BY id")).mappings()]


def has_synthetic_reference(conn) -> bool:
    q = ("SELECT (SELECT count(*) FROM medications WHERE is_synthetic = :t)"
         " + (SELECT count(*) FROM ruleset_versions WHERE is_synthetic = :t)"
         " + (SELECT count(*) FROM policy_settings WHERE is_synthetic = :t)")
    return conn.execute(text(q), {"t": True}).scalar_one() > 0


# ---------- قراءة للواجهة (محمية بالصلاحيات) ----------

def list_medications(ctx, session) -> list[dict]:
    from .access import CLINICAL, read_as
    return read_as(ctx, session, CLINICAL, lambda conn, user: medications(conn), "reference.read")


def list_medication_frequencies(ctx, session, medication_id: int) -> list[dict]:
    from .access import CLINICAL, read_as
    return read_as(ctx, session, CLINICAL,
                   lambda conn, user: medication_frequencies(conn, medication_id), "reference.read")


def list_not_given_reasons(ctx, session) -> list[dict]:
    from .access import CLINICAL, read_as
    return read_as(ctx, session, CLINICAL, lambda conn, user: not_given_reasons(conn), "reference.read")


def status_summary(ctx) -> dict:
    """للشريط العلوي: هل توجد بيانات وهمية، وهل حُمّلت قواعد وإعدادات."""
    with ctx.engine.connect() as conn:
        from .rules import active_ruleset_id
        from .rules import ruleset_kind_of
        rs = active_ruleset_id(conn)
        return {"synthetic": has_synthetic_reference(conn), "ruleset": rs, "kind": ruleset_kind_of(conn, rs),
                "policies": sorted(get_policies(conn))}
