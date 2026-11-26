"""تحميل مجموعة قواعد (إصدار جديد) من ملف JSON. يُشغَّل بحساب المالك.

    python scripts/load_ruleset.py --file rules.json --operator "اسم المنفّذ"

القاعدة الناقصة لا تدخل المجموعة الفعّالة؛ تُسجَّل «ناقصة» وتوقف العمليات الدوائية التي تمسّها فقط.
الملف الوهمي ("synthetic": true) مرفوض خارج بيئة test.
لا يعني التحميل أن القواعد معتمدة سريريًا؛ الاعتماد مسؤولية المراجعة السريرية للفريق.
"""
import argparse
import json
import sys
from pathlib import Path

from _common import admin_ctx

from hc.errors import DomainError
from hc.rules import load_ruleset


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--operator", required=True)
    args = p.parse_args(argv)
    ctx = admin_ctx()
    data = json.loads(Path(args.file).read_text("utf-8"))
    try:
        s = load_ruleset(ctx, data, operator=args.operator)
    except DomainError as e:
        print(f"مرفوض: {e.message} {e.details or ''}", file=sys.stderr)
        return 2
    print(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
