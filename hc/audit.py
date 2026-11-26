"""سجل التدقيق.

المبادئ:
1. العملية الناجحة وقيدها في السجل يُحفظان في المعاملة نفسها (كلاهما أو لا شيء).
2. العملية المرفوضة: تُلغى معاملتها بالكامل، ثم يُكتب قيد الرفض في معاملة مستقلة.
3. الخطأ غير المتوقع:
   - إذا بقي الاتصال بقاعدة البيانات سليمًا: نحاول كتابة قيد الخطأ بمعاملة مستقلة.
   - إذا كان الخطأ في الاتصال نفسه: لا نحاول ولا ندّعي أن القيد حُفظ؛ نكتب في سجل التشغيل الخارجي.
   - إذا فشلت المحاولة المستقلة: نكتب في سجل التشغيل الخارجي ونصرّح بأن القيد لم يُحفظ في القاعدة.
4. كل سطر يحمل بصمة HMAC لمحتواه ولبصمة السطر السابق (سلسلة).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError

from .db import db_now, read_db_env, write_tx
from .errors import Busy, Conflict, DomainError, OperationFailed
from .oplog import oplog_event

GENESIS_HASH = "0" * 64
PG_AUDIT_CHAIN_LOCK = 727001  # قفل استشاري يرتب كتابة أسطر السلسلة في PostgreSQL

HASHED_FIELDS = ("seq", "occurred_at", "actor_type", "actor_user_id", "actor_username",
                 "actor_role", "operator_name", "action", "entity_type", "entity_id",
                 "outcome", "details", "prev_hash")


@dataclass(frozen=True)
class Actor:
    type: str  # user | script | anonymous
    user_id: int | None = None
    username: str | None = None
    role: str | None = None
    operator: str | None = None


@dataclass
class Ctx:
    engine: Engine
    hmac_key: bytes
    env: str
    # يسمح بالقواعد التوضيحية في بيئة demo فقط، بإعداد صريح (HC_DEMO_ALLOW_ILLUSTRATIVE_RULES=true)
    allow_illustrative: bool = False


@dataclass
class ActionResult:
    value: Any = None
    entity_type: str | None = None
    entity_id: str | None = None
    details: dict = field(default_factory=dict)


def canonical(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(key: bytes, row: dict) -> str:
    payload = canonical({k: (None if row.get(k) is None else str(row.get(k))) for k in HASHED_FIELDS})
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _lock_chain(conn) -> None:
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": PG_AUDIT_CHAIN_LOCK})
    # SQLite: المعاملة بدأت بـ BEGIN IMMEDIATE، فقفل الكتابة محجوز أصلًا.


def append(conn, key: bytes, *, actor: Actor, action: str, outcome: str,
           entity_type: str | None = None, entity_id: str | None = None,
           details: dict | None = None) -> int:
    _lock_chain(conn)
    last = conn.execute(text("SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1")).first()
    prev_seq, prev_hash = (last[0], last[1]) if last else (0, GENESIS_HASH)
    row = {
        "seq": prev_seq + 1,
        "occurred_at": db_now(conn),
        "actor_type": actor.type,
        "actor_user_id": actor.user_id,
        "actor_username": actor.username,
        "actor_role": actor.role,
        "operator_name": actor.operator,
        "action": action,
        "entity_type": entity_type,
        "entity_id": None if entity_id is None else str(entity_id),
        "outcome": outcome,
        "details": canonical(details or {}),
        "prev_hash": prev_hash,
    }
    row["entry_hash"] = compute_hash(key, row)
    conn.execute(text(
        "INSERT INTO audit_log (seq, occurred_at, actor_type, actor_user_id, actor_username, actor_role,"
        " operator_name, action, entity_type, entity_id, outcome, details, prev_hash, entry_hash)"
        " VALUES (:seq, :occurred_at, :actor_type, :actor_user_id, :actor_username, :actor_role,"
        " :operator_name, :action, :entity_type, :entity_id, :outcome, :details, :prev_hash, :entry_hash)"
    ), row)
    return row["seq"]


# ---------- تصنيف الأخطاء ----------

def classify_db_error(e: BaseException) -> str:
    """'connection' | 'busy' | 'integrity' | 'other'"""
    if isinstance(e, IntegrityError):
        return "integrity"
    if isinstance(e, DBAPIError):
        if e.connection_invalidated:
            return "connection"
        orig = e.orig
        sqlstate = getattr(orig, "sqlstate", None)
        msg = str(orig).lower()
        if sqlstate == "55P03" or "database is locked" in msg:
            return "busy"
        if sqlstate and sqlstate.startswith("08"):
            return "connection"
        if isinstance(e, InterfaceError):
            return "connection"
        if isinstance(e, OperationalError):
            if sqlstate is None and ("connection" in msg or "connect" in msg or "server closed" in msg
                                     or "unable to open database" in msg):
                return "connection"
    if isinstance(e, (ConnectionError, TimeoutError)):
        return "connection"
    return "other"


def _record_separately(ctx: Ctx, *, actor: Actor, action: str, outcome: str,
                       entity_type, entity_id, details: dict) -> bool:
    """يكتب قيدًا في معاملة مستقلة. يعيد True فقط إذا حُفظ فعلًا."""
    try:
        with write_tx(ctx.engine) as conn:
            append(conn, ctx.hmac_key, actor=actor, action=action, outcome=outcome,
                   entity_type=entity_type, entity_id=entity_id, details=details)
        return True
    except Exception as e2:  # noqa: BLE001
        oplog_event("audit_write_failed", action=action, outcome=outcome, actor=actor.username,
                    entity_type=entity_type, entity_id=entity_id, details=details,
                    error_type=type(e2).__name__, error_class=classify_db_error(e2))
        return False


def record_rejection(ctx: Ctx, actor: Actor, action: str, e: DomainError) -> bool:
    return _record_separately(ctx, actor=actor, action=action, outcome=e.outcome,
                              entity_type=e.entity_type, entity_id=e.entity_id,
                              details={"code": e.code, "message": e.message, **e.details})


def run_action(ctx: Ctx, actor: Actor, action: str, fn: Callable[[Any], ActionResult]) -> Any:
    """ينفذ عملية كتابة مع ضمانات السجل الموضحة في رأس الملف."""
    try:
        with write_tx(ctx.engine) as conn:
            result = fn(conn)
            append(conn, ctx.hmac_key, actor=actor, action=action, outcome="success",
                   entity_type=result.entity_type, entity_id=result.entity_id, details=result.details)
        return result.value

    except DomainError as e:
        details = {"code": e.code, "message": e.message, **e.details}
        e.audit_persisted = _record_separately(ctx, actor=actor, action=action, outcome=e.outcome,
                                               entity_type=e.entity_type, entity_id=e.entity_id,
                                               details=details)
        raise

    except Exception as e:  # noqa: BLE001
        kind = classify_db_error(e)
        if kind in ("busy", "integrity"):
            # تحويل إلى خطأ متوقع: لا شيء حُفظ، والمستخدم يتلقى رسالة واضحة
            if kind == "busy":
                de: DomainError = Busy("النظام مشغول بعملية أخرى على السجل نفسه. حاول مرة أخرى.")
            else:
                de = Conflict("تعارض مع بيانات محفوظة مسبقًا (قيد فريد). لم يُحفظ أي شيء.",
                              code="unique_violation")
            de.audit_persisted = _record_separately(ctx, actor=actor, action=action, outcome=de.outcome,
                                                    entity_type=None, entity_id=None,
                                                    details={"code": de.code, "db_error": type(e).__name__})
            raise de from e

        if kind == "connection":
            oplog_event("operation_failed_connection", action=action, actor=actor.username,
                        error_type=type(e).__name__, audit_persisted=False)
            raise OperationFailed(audit_persisted=False, connection_failure=True) from e

        persisted = _record_separately(ctx, actor=actor, action=action, outcome="error",
                                       entity_type=None, entity_id=None,
                                       details={"error_type": type(e).__name__})
        if not persisted:
            oplog_event("operation_failed", action=action, actor=actor.username,
                        error_type=type(e).__name__, audit_persisted=False)
        raise OperationFailed(audit_persisted=persisted, connection_failure=False) from e


# ---------- التحقق من السلسلة والبصمة المرجعية الخارجية ----------

@dataclass
class VerifyReport:
    ok: bool
    count: int
    last_seq: int
    last_hash: str
    problems: list[str] = field(default_factory=list)


def verify_chain(engine: Engine, key: bytes) -> VerifyReport:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM audit_log ORDER BY seq")).mappings().all()
    problems: list[str] = []
    expected_prev = GENESIS_HASH
    expected_seq = 1
    for r in rows:
        r = dict(r)
        if r["seq"] != expected_seq:
            problems.append(f"فجوة في الترقيم: متوقع {expected_seq} ووُجد {r['seq']}")
            expected_seq = r["seq"]
        if r["prev_hash"] != expected_prev:
            problems.append(f"السطر {r['seq']}: بصمة السطر السابق لا تطابق")
        if compute_hash(key, r) != r["entry_hash"]:
            problems.append(f"السطر {r['seq']}: البصمة لا تطابق المحتوى")
        expected_prev = r["entry_hash"]
        expected_seq += 1
    last_seq = rows[-1]["seq"] if rows else 0
    last_hash = rows[-1]["entry_hash"] if rows else GENESIS_HASH
    return VerifyReport(ok=not problems, count=len(rows), last_seq=last_seq,
                        last_hash=last_hash, problems=problems)


ANCHOR_FIELDS = ("env", "last_seq", "last_hash", "count", "exported_at", "chain_ok", "override")
MIN_OVERRIDE_JUSTIFICATION = 20


class AnchorRefused(Exception):
    pass


def make_anchor(report: VerifyReport, env: str, exported_at: str, anchor_key: bytes,
                override: dict | None = None) -> dict:
    """بصمة مرجعية موقعة بمفتاح مستقل لا يملكه التطبيق.
    chain_ok و override جزء من المحتوى الموقّع، فلا يمكن إخفاؤهما لاحقًا."""
    body = {"env": env, "last_seq": report.last_seq, "last_hash": report.last_hash,
            "count": report.count, "exported_at": exported_at,
            "chain_ok": report.ok, "override": override}
    sig = hmac.new(anchor_key, canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()
    return {**body, "signature": sig}


def export_anchor(engine: Engine, audit_key: bytes, anchor_key: bytes, *, exported_at: str,
                  operator: str, allow_broken_chain: bool = False,
                  justification: str | None = None) -> tuple[dict, VerifyReport]:
    """يصدّر بصمة مرجعية لبيئة القاعدة نفسها.

    إذا كانت السلسلة غير سليمة: يُرفض التصدير، إلا بتجاوز استثنائي صريح مع اسم المنفّذ
    ومبرر مكتوب. التجاوز يُسجَّل داخل البصمة الموقعة نفسها، وفي سجل التدقيق.
    """
    operator = (operator or "").strip()
    if not operator:
        raise AnchorRefused("يجب تحديد اسم المنفّذ")
    env = read_db_env(engine)
    if env is None:
        raise AnchorRefused("قاعدة البيانات غير مهيأة (لا يوجد اسم بيئة)")
    report = verify_chain(engine, audit_key)
    override = None
    if not report.ok:
        if not allow_broken_chain:
            raise AnchorRefused("سلسلة التدقيق غير سليمة؛ رُفض تصدير بصمة مرجعية جديدة:\n- "
                                + "\n- ".join(report.problems))
        justification = (justification or "").strip()
        if len(justification) < MIN_OVERRIDE_JUSTIFICATION:
            raise AnchorRefused(f"التجاوز الاستثنائي يتطلب مبررًا مكتوبًا لا يقل عن "
                                f"{MIN_OVERRIDE_JUSTIFICATION} حرفًا")
        override = {"operator": operator, "justification": justification,
                    "problems_at_export": report.problems}
    anchor = make_anchor(report, env, exported_at, anchor_key, override)
    # توثيق التصدير في السجل نفسه (بعد حساب البصمة؛ فالقيد يأتي بعد آخر سطر مغطى)
    with write_tx(engine) as conn:
        append(conn, audit_key, actor=Actor(type="script", operator=operator, username="verify_audit"),
               action="audit.anchor_export_override" if override else "audit.anchor_export",
               outcome="success", entity_type="audit_log", entity_id=str(report.last_seq),
               details={"last_seq": report.last_seq, "chain_ok": report.ok, "override": override})
    return anchor, report


def check_anchor(engine: Engine, audit_key: bytes, anchor: dict, anchor_key: bytes) -> list[str]:
    """يقارن القاعدة الحالية ببصمة مرجعية محفوظة خارجها. يعيد قائمة المشكلات (فارغة = مطابق)."""
    problems: list[str] = []
    missing = [k for k in ANCHOR_FIELDS if k not in anchor]
    if missing:
        return [f"ملف البصمة المرجعية ناقص الحقول: {', '.join(missing)}"]
    body = {k: anchor[k] for k in ANCHOR_FIELDS}
    sig = hmac.new(anchor_key, canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, anchor.get("signature", "")):
        return ["توقيع البصمة المرجعية غير صحيح (الملف معدّل أو المفتاح خاطئ)"]
    db_env = read_db_env(engine)
    if db_env != anchor["env"]:
        return [f"البصمة المرجعية تخص بيئة '{anchor['env']}' لكن القاعدة المفحوصة تخص بيئة '{db_env}'؛ رُفض الفحص"]
    if not anchor["chain_ok"]:
        problems.append("تحذير: هذه البصمة صُدّرت فوق سلسلة غير سليمة بتجاوز استثنائي "
                        f"(المنفّذ: {anchor['override']['operator']})؛ لا تصلح مرجعًا نظيفًا")
    report = verify_chain(engine, audit_key)
    problems.extend(report.problems)
    with engine.connect() as conn:
        h = conn.execute(text("SELECT entry_hash FROM audit_log WHERE seq = :s"),
                         {"s": anchor["last_seq"]}).scalar_one_or_none()
    if h is None:
        problems.append(f"السطر {anchor['last_seq']} المسجل في البصمة المرجعية غير موجود "
                        f"(حذف من نهاية السجل أو استبدال بنسخة أقدم)")
    elif h != anchor["last_hash"]:
        problems.append(f"بصمة السطر {anchor['last_seq']} تغيّرت منذ تصدير البصمة المرجعية")
    if report.count < anchor["count"]:
        problems.append(f"عدد الأسطر الحالي {report.count} أقل من {anchor['count']} وقت التصدير")
    return problems
