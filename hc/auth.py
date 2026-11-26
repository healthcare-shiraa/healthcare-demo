"""تسجيل الدخول وفحص الصلاحيات من جهة الخادم.

- كل عملية حساسة تستدعي require_user داخل معاملتها. هذه الدالة تقرأ المستخدم
  من قاعدة البيانات في كل مرة (لا تثق بذاكرة الجلسة)، وتتأكد أنه نشط، وأن
  credential_version لم يتغير منذ الدخول (الإيقاف أو إعادة تعيين كلمة السر
  يُبطلان الجلسات المفتوحة فورًا)، وأن دوره مسموح له بالعملية.
- لا توجد في هذا الملف أي دالة لإنشاء مستخدم أو تغيير دوره. ذلك في
  admin_users.py ويُستدعى من سكربت خارج التطبيق فقط.
"""
from __future__ import annotations

from dataclasses import dataclass

import bcrypt
from sqlalchemy import text

from .audit import ActionResult, Actor, Ctx, run_action
from .errors import AuthenticationFailed, PermissionDenied, ValidationFailed

ROLES = {
    "registration": "موظف التسجيل",
    "doctor": "الطبيب",
    "pharmacist": "الصيدلي السريري",
    "nurse": "الممرض",
}
ALL_ROLES = frozenset(ROLES)

MIN_PASSWORD_LEN = 12
MAX_PASSWORD_BYTES = 72  # حد خوارزمية bcrypt
# بصمة وهمية تُستخدم عند عدم وجود المستخدم، حتى يستغرق الرفض الوقت نفسه
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer-not-a-password", bcrypt.gensalt()).decode()


@dataclass(frozen=True)
class Session:
    user_id: int
    username: str
    role: str
    full_name: str
    credential_version: int

    def actor(self) -> Actor:
        return Actor(type="user", user_id=self.user_id, username=self.username, role=self.role)


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValidationFailed(f"كلمة السر يجب ألا تقل عن {MIN_PASSWORD_LEN} حرفًا")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValidationFailed("كلمة السر أطول من الحد المسموح")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def _check_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")
    if len(pw) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(pw, password_hash.encode())


def login(ctx: Ctx, username: str, password: str) -> Session:
    username = (username or "").strip()
    actor = Actor(type="anonymous", username=username or None)

    def fn(conn) -> ActionResult:
        row = conn.execute(text(
            "SELECT id, username, password_hash, full_name, role, is_active, credential_version"
            " FROM users WHERE username = :u"), {"u": username}).mappings().first()
        ok = _check_password(password or "", row["password_hash"] if row else _DUMMY_HASH)
        if not row or not ok or not row["is_active"]:
            # رسالة واحدة عامة: لا نكشف هل الاسم موجود أو الحساب موقوف
            reason = "no_such_user" if not row else ("bad_password" if not ok else "inactive")
            raise AuthenticationFailed("اسم المستخدم أو كلمة السر غير صحيحة، أو الحساب موقوف.",
                                       details={"reason": reason})
        s = Session(user_id=row["id"], username=row["username"], role=row["role"],
                    full_name=row["full_name"], credential_version=row["credential_version"])
        return ActionResult(value=s, entity_type="user", entity_id=str(row["id"]))

    return run_action(ctx, actor, "auth.login", fn)


def logout(ctx: Ctx, session: Session) -> None:
    run_action(ctx, session.actor(), "auth.logout",
               lambda conn: ActionResult(entity_type="user", entity_id=str(session.user_id)))


def require_user(conn, session: Session | None, allowed_roles: frozenset[str] | set[str]) -> dict:
    """يُستدعى داخل معاملة العملية. يرفع PermissionDenied عند أي مخالفة."""
    if session is None:
        raise PermissionDenied("يجب تسجيل الدخول أولًا.")
    row = conn.execute(text(
        "SELECT id, username, role, is_active, credential_version FROM users WHERE id = :i"),
        {"i": session.user_id}).mappings().first()
    if row is None or not row["is_active"]:
        raise PermissionDenied("الحساب موقوف أو غير موجود. أعد تسجيل الدخول.",
                               code="inactive_or_missing", details={"user_id": session.user_id})
    if row["credential_version"] != session.credential_version:
        raise PermissionDenied("انتهت صلاحية الجلسة (تغيّرت بيانات الدخول). أعد تسجيل الدخول.",
                               code="stale_session", details={"user_id": session.user_id})
    if row["role"] not in allowed_roles:
        raise PermissionDenied("ليست لديك صلاحية لهذه العملية.",
                               code="role_not_allowed",
                               details={"role": row["role"], "allowed": sorted(allowed_roles)})
    return dict(row)
