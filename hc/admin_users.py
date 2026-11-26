"""إدارة الحسابات — للسكربت الخارجي فقط (scripts/manage_users.py).

لا يستورد التطبيق (app.py) هذا الملف. في PostgreSQL يتطلب حساب المالك (admin)
لأن حساب التطبيق لا يملك INSERT/UPDATE على جدول users أصلًا.
لا توجد كلمة سر افتراضية في أي مكان: كل كلمة سر تُدخل يدويًا عند التشغيل.
"""
from __future__ import annotations

import re

from sqlalchemy import text

from .audit import ActionResult, Actor, Ctx, run_action
from .auth import ROLES, hash_password
from .db import db_now
from .errors import Conflict, NotFound, ValidationFailed
from .known_test_secrets import forbidden_here

_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")


def _reject_test_password(ctx: Ctx, password: str) -> None:
    if forbidden_here(password, ctx.env):
        raise ValidationFailed("كلمة السر هذه من ملفات الاختبار المنشورة في المستودع، ولا يجوز استخدامها "
                               "في بيئة العرض (demo). اختر كلمة سر أخرى.", code="known_test_secret")


def _script_actor(operator: str) -> Actor:
    operator = (operator or "").strip()
    if not operator:
        raise ValidationFailed("يجب تحديد اسم المنفّذ (--operator)")
    return Actor(type="script", operator=operator, username="manage_users")


def create_user(ctx: Ctx, *, operator: str, username: str, full_name: str, role: str, password: str) -> int:
    actor = _script_actor(operator)
    username = (username or "").strip().lower()

    def fn(conn) -> ActionResult:
        if not _USERNAME_RE.match(username):
            raise ValidationFailed("اسم المستخدم: حروف إنجليزية صغيرة وأرقام، من 3 إلى 32 حرفًا، ويبدأ بحرف")
        if role not in ROLES:
            raise ValidationFailed(f"دور غير معروف: {role}")
        if not (full_name or "").strip():
            raise ValidationFailed("الاسم مطلوب")
        _reject_test_password(ctx, password)
        pw_hash = hash_password(password)
        exists = conn.execute(text("SELECT 1 FROM users WHERE username=:u"), {"u": username}).first()
        if exists:
            raise Conflict("اسم المستخدم موجود مسبقًا")
        uid = conn.execute(text(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (:u, :h, :n, :r)"
            " RETURNING id"), {"u": username, "h": pw_hash, "n": full_name.strip(), "r": role}).scalar_one()
        return ActionResult(value=uid, entity_type="user", entity_id=str(uid),
                            details={"username": username, "role": role})

    return run_action(ctx, actor, "admin.user_create", fn)


def deactivate_user(ctx: Ctx, *, operator: str, username: str) -> None:
    actor = _script_actor(operator)

    def fn(conn) -> ActionResult:
        row = conn.execute(text("SELECT id, is_active FROM users WHERE username=:u"),
                           {"u": username}).mappings().first()
        if not row:
            raise NotFound("المستخدم غير موجود")
        if not row["is_active"]:
            raise Conflict("الحساب موقوف مسبقًا")
        conn.execute(text(
            "UPDATE users SET is_active = :f, deactivated_at = :t,"
            " credential_version = credential_version + 1 WHERE id = :i"),
            {"f": False, "t": db_now(conn), "i": row["id"]})
        return ActionResult(entity_type="user", entity_id=str(row["id"]), details={"username": username})

    run_action(ctx, actor, "admin.user_deactivate", fn)


def reset_password(ctx: Ctx, *, operator: str, username: str, new_password: str) -> None:
    actor = _script_actor(operator)

    def fn(conn) -> ActionResult:
        row = conn.execute(text("SELECT id FROM users WHERE username=:u"), {"u": username}).first()
        if not row:
            raise NotFound("المستخدم غير موجود")
        _reject_test_password(ctx, new_password)
        pw_hash = hash_password(new_password)
        conn.execute(text(
            "UPDATE users SET password_hash = :h, credential_version = credential_version + 1 WHERE id = :i"),
            {"h": pw_hash, "i": row[0]})
        # لا نسجل كلمة السر ولا بصمتها في السجل
        return ActionResult(entity_type="user", entity_id=str(row[0]), details={"username": username})

    run_action(ctx, actor, "admin.user_reset_password", fn)
