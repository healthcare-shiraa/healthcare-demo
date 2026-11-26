"""قراءة محمية بالصلاحيات: القراءة الناجحة لا تُسجَّل، والمرفوضة تُسجَّل."""
from __future__ import annotations

from .audit import Actor, Ctx, record_rejection
from .auth import Session, require_user
from .errors import PermissionDenied

CLINICAL = frozenset({"doctor", "pharmacist", "nurse"})


def read_as(ctx: Ctx, session: Session | None, roles, fn, action: str):
    try:
        with ctx.engine.connect() as conn:
            user = require_user(conn, session, roles)
            return fn(conn, user)
    except PermissionDenied as e:
        actor = session.actor() if session else Actor(type="anonymous")
        e.audit_persisted = record_rejection(ctx, actor, action, e)
        raise
