"""أدوات «المهاجم» في الاختبارات: تعطيل الحماية وتعديل السجل مباشرة.
تُستخدم لإثبات ما تكشفه سلسلة البصمات وما لا تكشفه. لا يستوردها التطبيق.
"""
from sqlalchemy import text

from hc.audit import compute_hash

SQLITE_TRIGGERS = ("audit_no_update", "audit_no_delete")


def disable_audit_protection(tdb):
    with tdb.admin.engine.begin() as c:
        if tdb.kind == "sqlite":
            for t in SQLITE_TRIGGERS:
                c.exec_driver_sql(f"DROP TRIGGER IF EXISTS {t}")
        else:  # مالك الجدول يستطيع تعطيل مشغّلاته — هذا حد معروف وموثّق
            c.exec_driver_sql("ALTER TABLE audit_log DISABLE TRIGGER USER")


def rows(tdb):
    with tdb.admin.engine.connect() as c:
        return [dict(r) for r in c.execute(text("SELECT * FROM audit_log ORDER BY seq")).mappings()]


def edit_details(tdb, seq, new_details):
    with tdb.admin.engine.begin() as c:
        c.execute(text("UPDATE audit_log SET details=:d WHERE seq=:s"), {"d": new_details, "s": seq})


def delete_seq(tdb, where, **p):
    with tdb.admin.engine.begin() as c:
        c.execute(text(f"DELETE FROM audit_log WHERE {where}"), p)


def recompute_chain(tdb, key: bytes, from_seq: int = 1):
    """يعيد حساب البصمات ابتداءً من سطر معين بالمفتاح المعطى (مهاجم يملك/لا يملك المفتاح)."""
    rs = rows(tdb)
    prev = None
    with tdb.admin.engine.begin() as c:
        for r in rs:
            if r["seq"] < from_seq:
                prev = r["entry_hash"]
                continue
            if prev is not None:
                r["prev_hash"] = prev
            r["entry_hash"] = compute_hash(key, r)
            c.execute(text("UPDATE audit_log SET prev_hash=:p, entry_hash=:h WHERE seq=:s"),
                      {"p": r["prev_hash"], "h": r["entry_hash"], "s": r["seq"]})
            prev = r["entry_hash"]
