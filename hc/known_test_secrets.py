"""قيم الاختبار المعروفة (كلمات سر ومفاتيح ثابتة في ملفات tests/) — ممنوعة في بيئة العرض (demo).

هذه القيم منشورة في المستودع داخل الاختبارات. لو نسخها أحد يدويًا كسرّ لبيئة العرض أو الإنتاج،
لأصبح السر معروفًا لكل من يقرأ الكود. لذلك يرفض النظام استخدامها في بيئة demo (المنشورة) كمفتاح سجل،
أو مفتاح بصمة مرجعية، أو كلمة سر حساب مستخدم، أو كلمة سر حساب التطبيق في قاعدة البيانات.
بيئتا test و dev (المحليتان) غير مشمولتين: الاختبارات نفسها تستخدم هذه القيم.

تُحفظ هنا بصمات SHA-256 فقط، لا القيم نفسها. الاختبار K6 يتحقق أن كل ثابت سرّي في tests/ مدرج هنا.
"""
from __future__ import annotations

import hashlib

_KNOWN_TEST_SECRET_SHA256 = frozenset({
    "cdea9fb46a7f1d8fb5c6b45ee3ebf8f02a76ed9d7df4540ba281552a87b4e3ab",
    "35559c13b6d7167cb053b83b48d60e008baaa4f7f4cc055fcd25dd306f8b3efa",
    "7c96b4fb7dd9eb2a1ed69a3f8e973459037e23749999ad418bd97171cc9b6deb",
    "50c2d42fbf9b6bc8017f9257c68a88eb80686bde0401e555e9acfd2a13af4f07",
    "a9f6c84998dc8f631638645ba65eeeb64af182fe71e856913c316cfdc285bbd7",
    "fbf086d1407c1c343f4e8bce69e8907cda79b9185dda7372f8c0b0efd5825bb6",
    "1a344df86d3db32a6e3d4115048dacb19cbef3472ad2a999a32e2f6308cbc129",
    "73875cf9907a2e108ce9cddf3d935e8548fddf97fc74b863ca269efe0370c473",
    "394f073b382e0a80189c851d6a120c05fe374d1a64a0f862a83ab6b6311ae65c",
    "dc4c5d17d972b66638dd360cf701ca3d0d7ef3b06c5156cd4de5da931555d567",
    "bb1d2f9bd88205be352616d003c9bbe929fb0af76aacaa8af4356551d851f9cf",
})


def is_known_test_secret(value: str | bytes | None) -> bool:
    if value is None:
        return False
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest() in _KNOWN_TEST_SECRET_SHA256


PROTECTED_ENVS = frozenset({"demo"})


def forbidden_here(value: str | bytes | None, env: str | None) -> bool:
    """True إذا كانت القيمة سرّ اختبار معروفًا والبيئة محمية (demo)."""
    return env in PROTECTED_ENVS and is_known_test_secret(value)
