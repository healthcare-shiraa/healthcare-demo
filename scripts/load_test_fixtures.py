"""تحميل بيانات اختبار وهمية — لبيئة test فقط.

طبقات الحماية من الوصول إلى قاعدة demo (أو dev) حتى مع خطأ في الإعدادات:
1. السكربت لا يقرأ أبدًا متغيرات HC_DEMO_* أو HC_DEV_*؛ يقرأ HC_TEST_DATABASE_URL فقط
   (اسم ثابت في الكود)، فلا يمكن توجيهه إلى قاعدة أخرى بتغيير HC_ENV.
2. يرفض إذا لم يكن HC_ENV=test.
3. يرفض إذا طابق عنوانه عنوان أي بيئة أخرى موجودًا في المتغيرات.
4. في PostgreSQL: يرفض إذا لم ينتهِ اسم القاعدة بـ _test.
5. بعد الاتصال وقبل أي كتابة: يقرأ اسم البيئة المحفوظ داخل القاعدة ويرفض إن لم يكن test.
6. (عند النشر) بيانات اعتماد كل بيئة مختلفة؛ حساب الاختبار لا يملك صلاحية على قاعدة demo أصلًا.

البيانات هنا وهمية بوضوح، وليست معلومات طبية.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from hc.db import check_db_env, make_engine  # noqa: E402

FAKE_ALLERGENS = ["حساسية-اختبار-أ", "حساسية-اختبار-ب", "حساسية-اختبار-ج"]


class FixtureGuardError(Exception):
    pass


def guarded_test_url(environ) -> str:
    if environ.get("HC_ENV") != "test":
        raise FixtureGuardError("بيانات الاختبار الوهمية مسموحة في بيئة test فقط")
    # حساب المالك لبيئة الاختبار إن وُجد (لإضافة القوائم)، وإلا عنوان الاختبار العادي.
    url = environ.get("HC_TEST_ADMIN_DATABASE_URL") or environ.get("HC_TEST_DATABASE_URL")
    if not url:
        raise FixtureGuardError("HC_TEST_DATABASE_URL غير موجود")
    for other in ("HC_DEMO_DATABASE_URL", "HC_DEV_DATABASE_URL",
                  "HC_DEMO_ADMIN_DATABASE_URL", "HC_DEV_ADMIN_DATABASE_URL"):
        if environ.get(other) and environ.get(other) == url:
            raise FixtureGuardError(f"عنوان قاعدة الاختبار مطابق لـ {other}")
    if url.startswith("postgresql"):
        db = make_url(url).database or ""
        if not db.endswith("_test"):
            raise FixtureGuardError("اسم قاعدة الاختبار في PostgreSQL يجب أن ينتهي بـ _test")
    return url


def load(environ=os.environ) -> int:
    url = guarded_test_url(environ)
    engine = make_engine(url)
    check_db_env(engine, "test")  # قبل أي كتابة
    with engine.begin() as conn:
        for name in FAKE_ALLERGENS:
            exists = conn.execute(text("SELECT 1 FROM allergens WHERE name=:n"), {"n": name}).first()
            if not exists:
                conn.execute(text("INSERT INTO allergens(name) VALUES (:n)"), {"n": name})
    return len(FAKE_ALLERGENS)


FIXTURES = ROOT / "fixtures"


def load_medication_cycle(environ=os.environ, *, operator: str = "load_test_fixtures",
                          policies: dict | None = None) -> dict:
    """يحمّل مجموعة القواعد الوهمية والإعدادات الوهمية لدورة الدواء (test فقط، بالحمايات نفسها)."""
    import json

    from hc.audit import Ctx
    from hc.reference import set_policy
    from hc.rules import load_ruleset

    url = guarded_test_url(environ)
    key = environ.get("HC_TEST_AUDIT_HMAC_KEY") or ""
    if len(key) < 32:
        raise FixtureGuardError("HC_TEST_AUDIT_HMAC_KEY مطلوب")
    engine = make_engine(url)
    check_db_env(engine, "test")  # قبل أي كتابة
    ctx = Ctx(engine=engine, hmac_key=key.encode("utf-8"), env="test")
    data = json.loads((FIXTURES / "test_ruleset.json").read_text("utf-8"))
    summary = load_ruleset(ctx, data, operator=operator)
    pol = {k: v for k, v in json.loads((FIXTURES / "test_policies.json").read_text("utf-8")).items()
           if not k.startswith("_")}
    pol.update(policies or {})
    for k, v in pol.items():
        set_policy(ctx, operator=operator, key=k, value=str(v), synthetic=True)
    return summary


if __name__ == "__main__":
    try:
        n = load()
        print(f"حُمّلت {n} حساسيات وهمية للاختبار.")
        if "--with-medication-cycle" in sys.argv:
            s = load_medication_cycle()
            print(f"حُمّلت مجموعة قواعد وهمية رقم {s['ruleset_version_id']}: {len(s['loaded'])} قاعدة، "
                  f"{len(s['incomplete'])} ناقصة. وضُبطت إعدادات تشغيلية وهمية.")
    except FixtureGuardError as e:
        sys.exit(f"مرفوض: {e}")
