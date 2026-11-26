"""تحميل الإعدادات وفصل البيئات.

لكل بيئة متغيرات باسم خاص بها: HC_TEST_*, HC_DEV_*, HC_DEMO_*.
التطبيق في بيئة ما لا يقرأ إلا متغيرات بيئته، فلا يمكنه استخدام بيانات اعتماد
بيئة أخرى بالخطأ. ويُتحقق أيضًا من اسم البيئة المحفوظ داخل قاعدة البيانات نفسها.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError
from .known_test_secrets import forbidden_here

VALID_ENVS = ("test", "dev", "demo")
MIN_KEY_LEN = 32


@dataclass(frozen=True)
class Config:
    env: str
    database_url: str
    audit_hmac_key: bytes
    display_tz: str
    admin_database_url: str | None = None
    allow_illustrative: bool = False


def _var(env: str, name: str) -> str:
    return f"HC_{env.upper()}_{name}"


def load_config(source: Mapping[str, str], *, for_app: bool = True) -> Config:
    env = (source.get("HC_ENV") or "").strip()
    if env not in VALID_ENVS:
        raise ConfigError(f"HC_ENV يجب أن يكون واحدًا من {VALID_ENVS}")

    url = source.get(_var(env, "DATABASE_URL"))
    if not url:
        raise ConfigError(f"المتغير {_var(env, 'DATABASE_URL')} غير موجود")

    key = source.get(_var(env, "AUDIT_HMAC_KEY")) or ""
    if len(key) < MIN_KEY_LEN:
        raise ConfigError(f"{_var(env, 'AUDIT_HMAC_KEY')} مفقود أو أقصر من {MIN_KEY_LEN} حرفًا")

    if forbidden_here(key, env):
        raise ConfigError(f"{_var(env, 'AUDIT_HMAC_KEY')} يساوي مفتاحًا من ملفات الاختبار المنشورة؛ "
                          "استخدم مفتاحًا عشوائيًا خاصًا بهذه البيئة")

    tz = source.get("HC_DISPLAY_TZ")
    if not tz:
        raise ConfigError("HC_DISPLAY_TZ غير محدد (مثال: Asia/Aden)")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ConfigError(f"منطقة زمنية غير معروفة: {tz}") from e

    if env == "demo" and not url.startswith(("postgresql", "postgres://")):
        # SQLite على الاستضافة لا يضمن بقاء البيانات؛ لا نسمح بادعاء الحفظ الدائم.
        raise ConfigError("بيئة demo تتطلب قاعدة PostgreSQL")

    # لا يجوز أن تتشارك بيئتان قاعدة البيانات نفسها.
    for other in VALID_ENVS:
        if other != env:
            other_url = source.get(_var(other, "DATABASE_URL"))
            if other_url and other_url == url:
                raise ConfigError(f"عنوان قاعدة {env} مطابق لعنوان قاعدة {other}")

    if for_app:
        # مفتاح البصمة المرجعية الخارجية يجب ألا يكون في متناول التطبيق.
        leaked = [k for k in source.keys() if "ANCHOR" in k.upper()]
        if leaked:
            raise ConfigError("مفتاح البصمة المرجعية لا يجوز أن يكون ضمن إعدادات التطبيق: " + ", ".join(leaked))

    admin_url = source.get(_var(env, "ADMIN_DATABASE_URL"))
    if for_app:
        admin_url = None  # التطبيق لا يستخدم حساب المالك أبدًا

    # القواعد التوضيحية: بيئة demo فقط، وبالقيمة "true" حرفيًا. أي قيمة أخرى ترفض صراحة.
    flag = source.get("HC_DEMO_ALLOW_ILLUSTRATIVE_RULES")
    if flag is not None and env != "demo":
        raise ConfigError("HC_DEMO_ALLOW_ILLUSTRATIVE_RULES مسموح في بيئة demo فقط")
    if flag is not None and flag not in ("true", "false"):
        raise ConfigError("HC_DEMO_ALLOW_ILLUSTRATIVE_RULES يجب أن يكون true أو false")
    return Config(env=env, database_url=url, audit_hmac_key=key.encode("utf-8"),
                  display_tz=tz, admin_database_url=admin_url, allow_illustrative=(flag == "true"))
