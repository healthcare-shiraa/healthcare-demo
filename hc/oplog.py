"""سجل التشغيل الخارجي.

يُستخدم عندما يتعذر الكتابة في قاعدة البيانات (مثل انقطاع الاتصال).
يكتب أسطر JSON إلى مخرجات الأخطاء القياسية (تظهر في سجلات الاستضافة)،
وإلى ملف إذا حُدد المسار في HC_OPLOG_PATH.
هذا السجل ليس سجل التدقيق، ولا يتمتع بحمايته (لا سلسلة بصمات ولا مشغّلات).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_logger = logging.getLogger("hc.oplog")
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def oplog_event(event: str, **fields) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    line = json.dumps(record, ensure_ascii=False, default=str)
    _logger.error(line)
    path = os.environ.get("HC_OPLOG_PATH")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass  # إذا فشل حتى الملف، يبقى السطر في stderr
