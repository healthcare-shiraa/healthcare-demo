"""تحميل القواعد والإعدادات التوضيحية لنسخة العرض (demo فقط، مع HC_DEMO_ALLOW_ILLUSTRATIVE_RULES=true).

    python scripts/load_demo_illustrative.py --operator "الاسم"

الملفات في demo/ منفصلة تمامًا عن قواعد الاختبار في fixtures/ (أسماء ورموز مختلفة).
كل ما يُحمَّل هنا موسوم «توضيحي غير معتمد سريريًا»، ويظهر تحذير بذلك في كل صفحات الموقع.
"""
import argparse
import json
import sys
from pathlib import Path

from _common import ROOT, admin_ctx

from hc.errors import DomainError
from hc.reference import set_policy
from hc.rules import load_ruleset


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--operator", required=True)
    args = p.parse_args(argv)
    ctx = admin_ctx()
    if ctx.env != "demo" or not ctx.allow_illustrative:
        print("مرفوض: هذا السكربت لبيئة demo فقط مع HC_DEMO_ALLOW_ILLUSTRATIVE_RULES=true", file=sys.stderr)
        return 2
    try:
        rules = json.loads((ROOT / "demo" / "illustrative_ruleset.json").read_text("utf-8"))
        s = load_ruleset(ctx, rules, operator=args.operator)
        pol = json.loads((ROOT / "demo" / "illustrative_policies.json").read_text("utf-8"))
        for k, v in pol.items():
            if not k.startswith("_"):
                set_policy(ctx, operator=args.operator, key=k, value=str(v), synthetic=True)
    except DomainError as e:
        print(f"مرفوض: {e.message} {e.details or ''}", file=sys.stderr)
        return 2
    print(f"حُمّلت مجموعة قواعد توضيحية رقم {s['ruleset_version_id']} ({len(s['loaded'])} قاعدة، "
          f"{len(s['incomplete'])} ناقصة) وإعدادات توضيحية.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
