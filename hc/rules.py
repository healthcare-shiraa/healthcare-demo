"""محرك القواعد الثابتة: تحميل مجموعة قواعد، وفحص الوصفة بها.

- لا ذكاء اصطناعي ولا أي منطق احتمالي: مطابقة حرفية بين شروط القاعدة وبيانات المريض.
- القواعد تأتي من ملف يعدّه الفريق بعد المراجعة السريرية. ملف الاختبار الوهمي مسموح في بيئة test فقط.
- القاعدة الناقصة لا تُحمَّل في المجموعة الفعّالة؛ تُسجَّل «ناقصة» وتوقف العمليات الدوائية
  التي تمسّها فقط (أو كلها إن كانت شروطها نفسها مجهولة).
- كل وصفة تُثبَّت على إصدار مجموعة القواعد التي فُحصت بها.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text

from .audit import ActionResult, Actor, Ctx, run_action
from .errors import ValidationFailed
from .reference import dose_text, parse_dose
from .timefmt import parse_utc

RULE_FIELDS = ("code", "type", "severity", "alert_text", "resolution_policy",
               "existing_prescription_policy", "source_note", "conditions")
ENUMS = {
    "type": ("allergy", "interaction"),
    "severity": ("critical", "non_critical"),
    "resolution_policy": ("return_only", "conditional"),
    "existing_prescription_policy": ("block_until_resolved", "warn_only"),
}
SEVERITY_AR = {"critical": "حرج", "non_critical": "غير حرج"}


class RulesetError(ValidationFailed):
    code = "ruleset_invalid"


# ---------------------------------------------------------------- التحميل

def _get_or_create(conn, table: str, key_col: str, key, values: dict) -> int:
    row = conn.execute(text(f"SELECT * FROM {table} WHERE {key_col} = :k"), {"k": key}).mappings().first()
    if row:
        diff = {c: (row[c], v) for c, v in values.items() if str(row[c]) != str(v) and not
                (isinstance(v, bool) and bool(row[c]) == v)}
        if diff:
            raise RulesetError(f"{table} '{key}' موجود مسبقًا بقيم مختلفة؛ البيانات المرجعية لا تُعدَّل",
                               details={"diff": {k: [str(a), str(b)] for k, (a, b) in diff.items()}})
        return row["id"]
    cols = [key_col, *values]
    params = {key_col: key, **values}
    return conn.execute(text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                             f"({', '.join(':' + c for c in cols)}) RETURNING id"), params).scalar_one()


def _check_rule(rule: dict, meds: dict, allergens: dict) -> tuple[list[str], list[dict], bool]:
    """يعيد (الحقول الناقصة/غير الصالحة، الشروط المحلولة، هل الشروط معروفة)."""
    missing: list[str] = []
    for f in RULE_FIELDS:
        v = rule.get(f)
        if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
            missing.append(f)
        elif f in ENUMS and v not in ENUMS[f]:
            missing.append(f"{f} (قيمة غير صالحة: {v})")
    conds: list[dict] = []
    conditions_known = isinstance(rule.get("conditions"), list) and bool(rule.get("conditions"))
    for c in rule.get("conditions") or []:
        if rule.get("type") == "allergy" and c.get("allergen") in allergens and c.get("medication") in meds:
            conds.append({"allergen_id": allergens[c["allergen"]], "medication_a_id": meds[c["medication"]],
                          "medication_b_id": None})
        elif (rule.get("type") == "interaction" and c.get("medication_a") in meds
              and c.get("medication_b") in meds and c["medication_a"] != c["medication_b"]):
            conds.append({"allergen_id": None, "medication_a_id": meds[c["medication_a"]],
                          "medication_b_id": meds[c["medication_b"]]})
        else:
            conditions_known = False
            missing.append(f"conditions (شرط غير صالح أو يشير إلى عنصر غير معرّف: {c})")
    lb = rule.get("lookback_hours")
    if lb is not None and (not isinstance(lb, int) or isinstance(lb, bool) or lb < 0):
        missing.append("lookback_hours (عدد صحيح غير سالب أو null)")
    if rule.get("severity") == "critical" and rule.get("resolution_policy") == "conditional":
        reqs = rule.get("resolution_requirements") or []
        if not reqs:
            missing.append("resolution_requirements (مطلوبة للقاعدة الحرجة القابلة للتسوية)")
        for r in reqs:
            if not str(r.get("text", "")).strip() or r.get("evidence") not in ("confirm", "text"):
                missing.append(f"resolution_requirements (شرط غير صالح: {r})")
    return missing, conds, conditions_known


KINDS = ("clinical", "test_fixture", "illustrative")


def ruleset_kind(data: dict) -> str:
    kind = data.get("kind") or ("test_fixture" if data.get("synthetic") else "clinical")
    if kind not in KINDS:
        raise RulesetError(f"نوع مجموعة قواعد غير معروف: {kind}")
    if kind == "clinical" and data.get("synthetic"):
        raise RulesetError("ملف موسوم synthetic لا يمكن أن يكون clinical")
    return kind


def kind_allowed(kind: str, ctx: Ctx) -> bool:
    """أين يُسمح بكل نوع:
    - test_fixture (قواعد الاختبار الوهمية): بيئة test فقط.
    - illustrative (قواعد العرض التوضيحية): بيئة demo فقط، وبإعداد صريح.
    - clinical: أي بيئة (الاعتماد السريري مسؤولية الفريق قبل التحميل)."""
    if kind == "test_fixture":
        return ctx.env == "test"
    if kind == "illustrative":
        return ctx.env == "demo" and ctx.allow_illustrative
    return True


def load_ruleset(ctx: Ctx, data: dict, *, operator: str) -> dict:
    """يحمّل مجموعة قواعد جديدة (إصدار جديد). يُستدعى من سكربت المالك فقط."""
    kind = ruleset_kind(data)
    synthetic = kind != "clinical"
    operator = (operator or "").strip()
    if not operator:
        raise RulesetError("يجب تحديد اسم المنفّذ")
    if not kind_allowed(kind, ctx):
        if kind == "test_fixture":
            raise RulesetError("مجموعة القواعد الوهمية مسموحة في بيئة test فقط")
        raise RulesetError("القواعد التوضيحية مسموحة في بيئة demo فقط، مع HC_DEMO_ALLOW_ILLUSTRATIVE_RULES=true")
    if not (data.get("label") or "").strip():
        raise RulesetError("label مطلوب")
    actor = Actor(type="script", operator=operator, username="load_ruleset")

    def fn(conn) -> ActionResult:
        allergens = {n: _get_or_create(conn, "allergens", "name", n, {}) for n in data.get("allergens", [])}
        freqs = {}
        for f in data.get("frequencies", []):
            if not isinstance(f.get("interval_hours"), int) or f["interval_hours"] <= 0:
                raise RulesetError(f"تكرار غير صالح: {f}")
            freqs[f["code"]] = _get_or_create(conn, "frequencies", "code", f["code"],
                                              {"label": f["label"], "interval_hours": f["interval_hours"],
                                               "is_synthetic": synthetic})
        meds = {}
        for m in data.get("medications", []):
            lo, hi = parse_dose(m["dose_min"]), parse_dose(m["dose_max"])
            if lo > hi:
                raise RulesetError(f"نطاق جرعة غير صالح للدواء {m['name']}")
            mid = _get_or_create(conn, "medications", "name", m["name"],
                                 {"unit": m["unit"], "dose_min": dose_text(lo), "dose_max": dose_text(hi),
                                  "is_synthetic": synthetic})
            meds[m["name"]] = mid
            for code in m.get("frequencies", []):
                if code not in freqs:
                    raise RulesetError(f"تكرار غير معرّف {code} للدواء {m['name']}")
                if not conn.execute(text("SELECT 1 FROM medication_frequencies WHERE medication_id=:m"
                                         " AND frequency_id=:f"), {"m": mid, "f": freqs[code]}).first():
                    conn.execute(text("INSERT INTO medication_frequencies VALUES (:m, :f)"),
                                 {"m": mid, "f": freqs[code]})
        for r in data.get("not_given_reasons", []):
            _get_or_create(conn, "not_given_reasons", "code", r["code"],
                           {"label": r["label"], "requires_text": bool(r.get("requires_text")),
                            "is_synthetic": synthetic})
        # كل الأسماء المعروفة في القاعدة (ومنها ما حُمّل سابقًا)
        all_meds = {r[0]: r[1] for r in conn.execute(text("SELECT name, id FROM medications"))}
        all_allergens = {r[0]: r[1] for r in conn.execute(text("SELECT name, id FROM allergens"))}

        rs_id = conn.execute(text("INSERT INTO ruleset_versions (label, operator, is_synthetic, kind)"
                                  " VALUES (:l, :o, :s, :k) RETURNING id"),
                             {"l": data["label"].strip(), "o": operator, "s": synthetic, "k": kind}).scalar_one()
        loaded, incomplete = [], []
        codes = [r.get("code") for r in data.get("rules", [])]
        if len(set(codes)) != len(codes):
            raise RulesetError("رموز القواعد مكررة")
        for rule in data.get("rules", []):
            missing, conds, known = _check_rule(rule, all_meds, all_allergens)
            code = (rule.get("code") or "").strip() or "(بلا رمز)"
            if missing:
                med_ids = sorted({c["medication_a_id"] for c in conds} | {c["medication_b_id"] for c in conds
                                                                          if c["medication_b_id"]})
                conn.execute(text("INSERT INTO incomplete_rules (ruleset_version_id, code, missing,"
                                  " medication_ids, conditions_known) VALUES (:rs, :c, :m, :ids, :k)"),
                             {"rs": rs_id, "c": code, "m": json.dumps(missing, ensure_ascii=False),
                              "ids": json.dumps(med_ids), "k": known})
                incomplete.append({"code": code, "missing": missing})
                continue
            prev = conn.execute(text("SELECT max(version) FROM rule_versions WHERE code=:c"),
                                {"c": code}).scalar_one() or 0
            rv = conn.execute(text(
                "INSERT INTO rule_versions (ruleset_version_id, code, version, rule_type, severity, alert_text,"
                " resolution_policy, existing_rx_policy, lookback_hours, source_note) VALUES"
                " (:rs, :c, :v, :t, :s, :a, :rp, :ep, :lb, :src) RETURNING id"),
                {"rs": rs_id, "c": code, "v": prev + 1, "t": rule["type"], "s": rule["severity"],
                 "a": rule["alert_text"].strip(), "rp": rule["resolution_policy"],
                 "ep": rule["existing_prescription_policy"], "lb": rule.get("lookback_hours"),
                 "src": rule["source_note"].strip()}).scalar_one()
            for c in conds:
                conn.execute(text("INSERT INTO rule_conditions (rule_version_id, allergen_id, medication_a_id,"
                                  " medication_b_id) VALUES (:rv, :al, :a, :b)"),
                             {"rv": rv, "al": c["allergen_id"], "a": c["medication_a_id"], "b": c["medication_b_id"]})
            for i, req in enumerate(rule.get("resolution_requirements") or [], start=1):
                conn.execute(text("INSERT INTO rule_resolution_requirements (rule_version_id, seq, text, evidence)"
                                  " VALUES (:rv, :i, :t, :e)"),
                             {"rv": rv, "i": i, "t": req["text"].strip(), "e": req["evidence"]})
            loaded.append(code)
        summary = {"ruleset_version_id": rs_id, "loaded": loaded, "incomplete": incomplete,
                   "synthetic": synthetic, "kind": kind}
        return ActionResult(value=summary, entity_type="ruleset", entity_id=str(rs_id), details=summary)

    return run_action(ctx, actor, "admin.ruleset_load", fn)


# ---------------------------------------------------------------- الفحص

@dataclass
class Candidate:
    rule_version_id: int
    code: str
    severity: str
    alert_text: str
    related_prescription_id: int | None
    related_allergy_id: int | None
    detail: str

    @property
    def key(self) -> tuple:
        # المفتاح بالرمز لا بالإصدار، حتى تتطابق التنبيهات بين وصفات فُحصت بإصدارين مختلفين
        return (self.code, self.related_prescription_id, self.related_allergy_id)


def active_ruleset_id(conn) -> int | None:
    return conn.execute(text("SELECT max(id) FROM ruleset_versions")).scalar_one()


def ruleset_kind_of(conn, ruleset_id: int | None) -> str | None:
    if ruleset_id is None:
        return None
    return conn.execute(text("SELECT kind FROM ruleset_versions WHERE id = :r"), {"r": ruleset_id}).scalar_one()


def blocking_incomplete_rules(conn, ruleset_id: int, medication_id: int) -> list[dict]:
    rows = conn.execute(text("SELECT code, missing, medication_ids, conditions_known FROM incomplete_rules"
                             " WHERE ruleset_version_id = :rs"), {"rs": ruleset_id}).mappings().all()
    out = []
    for r in rows:
        if not r["conditions_known"] or medication_id in json.loads(r["medication_ids"]):
            out.append({"code": r["code"], "missing": json.loads(r["missing"])})
    return out


def _overlaps(s1, e1, s2, e2) -> bool:
    return s1 < e2 and s2 < e1


def candidates(conn, *, ruleset_id: int, patient_id: int, medication_id: int,
               start_at: str, end_at: str, exclude_rx_id: int | None = None) -> list[Candidate]:
    """كل التنبيهات التي تنتج عن القواعد لهذا الدواء لهذا المريض في هذه الفترة."""
    out: list[Candidate] = []
    rules = conn.execute(text(
        "SELECT rv.id, rv.code, rv.rule_type, rv.severity, rv.alert_text, rv.lookback_hours,"
        " c.allergen_id, c.medication_a_id, c.medication_b_id"
        " FROM rule_versions rv JOIN rule_conditions c ON c.rule_version_id = rv.id"
        " WHERE rv.ruleset_version_id = :rs AND (c.medication_a_id = :m OR c.medication_b_id = :m)"
        " ORDER BY rv.code, c.id"), {"rs": ruleset_id, "m": medication_id}).mappings().all()
    if not rules:
        return out
    allergies = conn.execute(text(
        "SELECT pa.id, pa.allergen_id, a.name FROM patient_allergies pa JOIN allergens a ON a.id = pa.allergen_id"
        " WHERE pa.patient_id = :p AND pa.removed_at IS NULL"), {"p": patient_id}).mappings().all()
    others = conn.execute(text(
        "SELECT rx.id, rx.medication_id, rx.start_at, rx.end_at, m.name FROM prescriptions rx"
        " JOIN medications m ON m.id = rx.medication_id"
        " WHERE rx.patient_id = :p AND rx.status IN ('awaiting_pharmacist','approved')"
        + (" AND rx.id <> :x" if exclude_rx_id else "")),
        {"p": patient_id, **({"x": exclude_rx_id} if exclude_rx_id else {})}).mappings().all()
    s, e = parse_utc(start_at), parse_utc(end_at)
    seen = set()
    for r in rules:
        if r["rule_type"] == "allergy":
            if r["medication_a_id"] != medication_id:
                continue
            for al in allergies:
                if al["allergen_id"] == r["allergen_id"]:
                    c = Candidate(r["id"], r["code"], r["severity"], r["alert_text"], None, al["id"],
                                  f"حساسية مسجلة: {al['name']}")
                    if c.key not in seen:
                        seen.add(c.key)
                        out.append(c)
        else:
            other_med = r["medication_b_id"] if r["medication_a_id"] == medication_id else r["medication_a_id"]
            lb = timedelta(hours=r["lookback_hours"] or 0)
            for o in others:
                if o["medication_id"] != other_med:
                    continue
                if _overlaps(s, e, parse_utc(o["start_at"]), parse_utc(o["end_at"]) + lb):
                    c = Candidate(r["id"], r["code"], r["severity"], r["alert_text"], o["id"], None,
                                  f"تداخل مع الوصفة رقم {o['id']} ({o['name']})")
                    if c.key not in seen:
                        seen.add(c.key)
                        out.append(c)
    return out


def insert_alerts(conn, rx_id: int, cands: list[Candidate]) -> list[int]:
    ids = []
    for c in cands:
        ids.append(conn.execute(text(
            "INSERT INTO alerts (prescription_id, rule_version_id, severity, alert_text,"
            " related_prescription_id, related_allergy_id) VALUES (:rx, :rv, :s, :t, :rp, :ra) RETURNING id"),
            {"rx": rx_id, "rv": c.rule_version_id, "s": c.severity, "t": c.alert_text,
             "rp": c.related_prescription_id, "ra": c.related_allergy_id}).scalar_one())
    return ids


def existing_alert_keys(conn, rx_id: int) -> set[tuple]:
    """مفاتيح التنبيهات الموجودة على الوصفة، وكذلك التنبيهات على وصفات أخرى تشير إليها
    (التداخل يُسجَّل مرة واحدة على الوصفة الأحدث)."""
    keys = set()
    for r in conn.execute(text(
            "SELECT rv.code, a.related_prescription_id, a.related_allergy_id FROM alerts a"
            " JOIN rule_versions rv ON rv.id = a.rule_version_id WHERE a.prescription_id = :x"), {"x": rx_id}):
        keys.add((r[0], r[1], r[2]))
    for r in conn.execute(text(
            "SELECT rv.code, a.prescription_id FROM alerts a JOIN rule_versions rv ON rv.id = a.rule_version_id"
            " WHERE a.related_prescription_id = :x"), {"x": rx_id}):
        keys.add((r[0], r[1], None))
    return keys
