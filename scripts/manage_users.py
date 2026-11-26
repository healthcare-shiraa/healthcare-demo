"""إدارة الحسابات من خارج التطبيق.

    python scripts/manage_users.py create --username sara.doc --full-name "..." --role doctor --operator "اسم المنفّذ"
    python scripts/manage_users.py deactivate --username sara.doc --operator "..."
    python scripts/manage_users.py reset-password --username sara.doc --operator "..."

كلمة السر تُطلب بإدخال مخفي (لا تظهر على الشاشة ولا في سجل الأوامر)،
أو تُقرأ من الإدخال القياسي مع --password-stdin (للأتمتة). لا توجد كلمة سر افتراضية.
"""
import argparse
import getpass
import sys

from _common import admin_ctx

from hc import admin_users
from hc.errors import DomainError


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    pw1 = getpass.getpass("كلمة السر الجديدة: ")
    pw2 = getpass.getpass("أعد كتابة كلمة السر: ")
    if pw1 != pw2:
        sys.exit("كلمتا السر غير متطابقتين.")
    return pw1


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--username", required=True)
    c.add_argument("--full-name", required=True)
    c.add_argument("--role", required=True, choices=["registration", "doctor", "pharmacist", "nurse"])
    c.add_argument("--operator", required=True)
    c.add_argument("--password-stdin", action="store_true")
    d = sub.add_parser("deactivate")
    d.add_argument("--username", required=True)
    d.add_argument("--operator", required=True)
    r = sub.add_parser("reset-password")
    r.add_argument("--username", required=True)
    r.add_argument("--operator", required=True)
    r.add_argument("--password-stdin", action="store_true")
    args = p.parse_args(argv)

    ctx = admin_ctx()
    try:
        if args.cmd == "create":
            uid = admin_users.create_user(ctx, operator=args.operator, username=args.username,
                                          full_name=args.full_name, role=args.role,
                                          password=_read_password(args.password_stdin))
            print(f"أُنشئ الحساب {args.username} (رقم {uid}).")
        elif args.cmd == "deactivate":
            admin_users.deactivate_user(ctx, operator=args.operator, username=args.username)
            print(f"أُوقف الحساب {args.username}.")
        else:
            admin_users.reset_password(ctx, operator=args.operator, username=args.username,
                                       new_password=_read_password(args.password_stdin))
            print(f"أُعيد تعيين كلمة سر {args.username}.")
    except DomainError as e:
        print(f"مرفوض: {e.message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
