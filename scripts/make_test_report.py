"""يولّد تقرير الاختبارات من ملف JUnit XML الذي يُخرجه pytest (نتائج فعلية، لا كتابة يدوية).

    python -m pytest --junitxml=results.xml
    python scripts/make_test_report.py results.xml TEST_REPORT.md
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

STATUS_AR = {"passed": "نجح", "failed": "فشل", "skipped": "لم يُنفَّذ (تخطٍّ)", "error": "خطأ"}


def main(src: str, dst: str) -> None:
    root = ET.parse(src).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    rows, tally = [], Counter()
    for tc in suite.iter("testcase"):
        name = tc.get("name")
        m = re.match(r"(test_\w+?)(?:\[(.+)\])?$", name)
        base, param = (m.group(1), m.group(2)) if m else (name, None)
        engine = "—"
        if param:
            for eng in ("sqlite", "postgresql"):
                if eng in param.split("-"):
                    engine = eng
        status, note = "passed", ""
        for tag in ("failure", "error", "skipped"):
            el = tc.find(tag)
            if el is not None:
                status = {"failure": "failed"}.get(tag, tag)
                note = (el.get("message") or "").strip().splitlines()[0][:120]
        tally[status] += 1
        file_ = tc.get("classname", "").split(".")[-1]
        rows.append((file_, base, param or "", engine, STATUS_AR[status], note, tc.get("time")))

    out = ["# تقرير الاختبارات — مولّد آليًا من مخرجات pytest", "",
           f"وقت التشغيل (من الملف): {suite.get('timestamp')} · المضيف: {suite.get('hostname')}", "",
           f"**المجموع:** {sum(tally.values())} · نجح {tally['passed']} · فشل {tally['failed']} · "
           f"خطأ {tally['error']} · لم يُنفَّذ {tally['skipped']}", "",
           "| الملف | الاختبار | المعامل | المحرك | النتيجة | ملاحظة | الزمن (ث) |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{dst}: {dict(tally)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
