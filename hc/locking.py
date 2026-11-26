"""قفل سطر قبل فحصه وتعديله، بآلية مناسبة لكل محرك.

PostgreSQL: SELECT ... FOR UPDATE يقفل السطر وحده حتى نهاية المعاملة.
            المعاملة الثانية تنتظر (حتى lock_timeout)، ثم تُعيد الفحص
            فترى ما أكّدته الأولى (مستوى العزل READ COMMITTED).
SQLite:     لا أقفال أسطر. المعاملة بدأت بـ BEGIN IMMEDIATE فقفل الكتابة على
            القاعدة كلها محجوز أصلًا؛ هنا نتحقق فقط من وجود السطر.
في الحالتين: بعد القفل يجب إعادة فحص الحالة، ثم يبقى القيد الفريد خط الدفاع الأخير.
"""
from __future__ import annotations

from sqlalchemy import text

from .errors import NotFound

# أسماء الجداول تأتي من قائمة ثابتة فقط (لا من مدخلات المستخدم)
LOCKABLE = {
    "patients": "id",
    "prescriptions": "id",
    "scheduled_doses": "id",
    "probe_items": "id",       # جدول اختبار فقط (يُنشأ في بيئة الاختبار)
}


def lock_row(conn, table: str, key) -> None:
    col = LOCKABLE[table]
    sql = f"SELECT 1 FROM {table} WHERE {col} = :k"
    if conn.dialect.name == "postgresql":
        sql += " FOR UPDATE"
    if conn.execute(text(sql), {"k": key}).first() is None:
        raise NotFound("السجل غير موجود", entity_type=table, entity_id=str(key))
