"""إنشاء الاتصال بقاعدة البيانات، مع إعدادات خاصة بكل محرك.

SQLite:
  - معاملات الكتابة فقط (المفتوحة عبر write_tx) تبدأ بـ BEGIN IMMEDIATE: يُحجز قفل
    الكتابة من أول لحظة، فلا يدخل كاتبان معًا (SQLite لا يملك أقفالًا على مستوى السطر).
  - معاملات القراءة تبدأ بـ BEGIN العادي (المؤجل)، فلا تحجز قفل الكتابة، ومع WAL
    لا تعطل الكتّاب ولا القرّاء الآخرين.
  - WAL يسمح بالقراءة أثناء الكتابة، و busy_timeout يحدد مدة الانتظار.
  - foreign_keys يجب تفعيلها صراحة في SQLite.
PostgreSQL:
  - أقفال على مستوى السطر (SELECT ... FOR UPDATE) داخل معاملة عادية.
  - lock_timeout يمنع الانتظار إلى ما لا نهاية.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine

from .errors import EnvironmentMismatch

SQLITE_BUSY_TIMEOUT_MS = 5000
PG_LOCK_TIMEOUT_MS = 5000
WRITE_OPTION = "hc_write"


@contextmanager
def write_tx(engine: Engine) -> Iterator[Connection]:
    """معاملة كتابة. في SQLite تبدأ بـ BEGIN IMMEDIATE؛ في PostgreSQL معاملة عادية
    (الأقفال على مستوى السطر تؤخذ عند الحاجة بـ FOR UPDATE)."""
    with engine.connect() as conn:
        conn.execution_options(**{WRITE_OPTION: True})
        with conn.begin():
            yield conn


def normalize_url(url: str) -> str:
    """Neon يعطي العنوان بصيغة postgresql://؛ نحدد مشغّل psycopg صراحة."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"timeout": SQLITE_BUSY_TIMEOUT_MS / 1000})

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _rec):
            # نوقف إدارة المعاملات التلقائية في مكتبة sqlite3 لنتحكم بـ BEGIN بأنفسنا
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cur.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn):
            if conn.get_execution_options().get(WRITE_OPTION):
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.exec_driver_sql("BEGIN")

        return engine

    if url.startswith("postgresql"):
        return create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"options": f"-c lock_timeout={PG_LOCK_TIMEOUT_MS} -c timezone=UTC"},
        )
    raise ValueError("محرك قاعدة بيانات غير مدعوم")


def db_now_sql(dialect: str) -> str:
    """تعبير SQL يعطي الوقت الحالي بالتوقيت العالمي بصيغة نصية ثابتة."""
    if dialect == "sqlite":
        # SQLite يعطي ثلاث خانات للكسور؛ نكملها بست خانات لتطابق صيغة PostgreSQL
        return "(strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')"
    return "to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"


def db_now(conn) -> str:
    return conn.execute(text("SELECT " + db_now_sql(conn.dialect.name))).scalar_one()


def read_db_env(engine: Engine) -> str | None:
    with engine.connect() as conn:
        try:
            return conn.execute(text("SELECT value FROM meta WHERE key='env'")).scalar_one_or_none()
        except Exception:
            return None


def check_db_env(engine: Engine, expected_env: str) -> None:
    """يرفض العمل إذا كانت القاعدة تخص بيئة أخرى أو لم تُهيأ."""
    actual = read_db_env(engine)
    if actual is None:
        raise EnvironmentMismatch("قاعدة البيانات غير مهيأة (لا يوجد اسم بيئة محفوظ فيها)")
    if actual != expected_env:
        raise EnvironmentMismatch(f"الإعدادات تخص بيئة '{expected_env}' لكن القاعدة تخص بيئة '{actual}'")
