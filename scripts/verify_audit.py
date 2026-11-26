"""التحقق من سلسلة سجل التدقيق، وتصدير/مقارنة البصمة المرجعية الخارجية.

    python scripts/verify_audit.py verify
    python scripts/verify_audit.py export-anchor --out /مسار/خارج/المشروع/anchor.json --operator "الاسم"
    (إذا كانت السلسلة غير سليمة يُرفض التصدير، إلا بتجاوز استثنائي موثّق:
     --allow-broken-chain --justification "مبرر مكتوب لا يقل عن 20 حرفًا")
    python scripts/verify_audit.py check-anchor  --anchor /مسار/anchor.json

مفتاح توقيع البصمة المرجعية (HC_ANCHOR_KEY) يختلف عن مفتاح السجل، ويُمرَّر في
جلسة المنفّذ فقط. التطبيق يرفض العمل إذا وُجد هذا المفتاح ضمن إعداداته.
ملف البصمة يُحفظ خارج المشروع وخارج الاستضافة، في مكان لا يملك التطبيق الكتابة عليه.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import ROOT, admin_ctx

from hc.known_test_secrets import forbidden_here
from hc.audit import AnchorRefused, check_anchor, export_anchor, verify_chain


def _anchor_key(ctx) -> bytes:
    k = os.environ.get("HC_ANCHOR_KEY", "")
    if len(k) < 32:
        sys.exit("HC_ANCHOR_KEY مفقود أو أقصر من 32 حرفًا")
    kb = k.encode("utf-8")
    if forbidden_here(kb, ctx.env):
        sys.exit("HC_ANCHOR_KEY يساوي مفتاحًا من ملفات الاختبار المنشورة؛ مرفوض في بيئة العرض (demo)")
    if kb == ctx.hmac_key:
        sys.exit("مفتاح البصمة المرجعية يجب أن يختلف عن مفتاح سجل التدقيق")
    return kb


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    e = sub.add_parser("export-anchor")
    e.add_argument("--out", required=True)
    e.add_argument("--operator", required=True)
    e.add_argument("--allow-broken-chain", action="store_true",
                   help="تجاوز استثنائي: تصدير رغم وجود مشكلات في السلسلة (يُوثَّق في البصمة والسجل)")
    e.add_argument("--justification", help="مبرر مكتوب للتجاوز الاستثنائي")
    c = sub.add_parser("check-anchor")
    c.add_argument("--anchor", required=True)
    args = p.parse_args(argv)
    ctx = admin_ctx()

    if args.cmd == "verify":
        r = verify_chain(ctx.engine, ctx.hmac_key)
        print(json.dumps({"ok": r.ok, "count": r.count, "last_seq": r.last_seq, "problems": r.problems},
                         ensure_ascii=False, indent=2))
        return 0 if r.ok else 1

    if args.cmd == "export-anchor":
        out = Path(args.out).resolve()
        if ROOT in out.parents:
            sys.exit("لا يجوز حفظ البصمة المرجعية داخل مجلد المشروع")
        if out.exists():
            sys.exit("الملف موجود مسبقًا؛ لا يُستبدل ملف بصمة مرجعية سابق")
        try:
            anchor, r = export_anchor(ctx.engine, ctx.hmac_key, _anchor_key(ctx),
                                      exported_at=datetime.now(timezone.utc).isoformat(),
                                      operator=args.operator, allow_broken_chain=args.allow_broken_chain,
                                      justification=args.justification)
        except AnchorRefused as ex:
            print(f"مرفوض: {ex}", file=sys.stderr)
            return 3
        if anchor["override"]:
            print("تحذير: صُدّرت البصمة بتجاوز استثنائي فوق سلسلة غير سليمة، ووُثّق ذلك.", file=sys.stderr)
        out.write_text(json.dumps(anchor, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(out, 0o400)  # قراءة فقط لمالك الملف
        print(f"صُدّرت البصمة المرجعية حتى السطر {r.last_seq} إلى {out}")
        return 0

    anchor = json.loads(Path(args.anchor).read_text("utf-8"))
    problems = check_anchor(ctx.engine, ctx.hmac_key, anchor, _anchor_key(ctx))
    print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
