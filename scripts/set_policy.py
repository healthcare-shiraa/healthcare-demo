"""ضبط إعداد تشغيلي (كل تغيير سطر جديد ومسجّل في السجل). يُشغَّل بحساب المالك.

    python scripts/set_policy.py --key dose_window_minutes --value 60 --operator "الاسم"

المفاتيح: dose_window_minutes, late_documentation_max_hours (رقم أو none),
          missed_dose_sequence_policy (strict|warn), max_treatment_days
القيم يعتمدها الفريق؛ لا توجد قيم افتراضية في النظام.
"""
import argparse
import sys

from _common import admin_ctx

from hc.errors import DomainError
from hc.reference import POLICY_KEYS, set_policy


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, choices=sorted(POLICY_KEYS))
    p.add_argument("--value", required=True)
    p.add_argument("--operator", required=True)
    p.add_argument("--illustrative", action="store_true",
                   help="قيمة توضيحية غير معتمدة (demo مع HC_DEMO_ALLOW_ILLUSTRATIVE_RULES=true فقط)")
    args = p.parse_args(argv)
    try:
        set_policy(admin_ctx(), operator=args.operator, key=args.key, value=args.value, synthetic=args.illustrative)
    except DomainError as e:
        print(f"مرفوض: {e.message}", file=sys.stderr)
        return 2
    print(f"ضُبط {args.key} = {args.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
