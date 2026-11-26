"""اختبارات إصلاحات مراجعة المرحلة الأولى:
R: فصل معاملات القراءة عن الكتابة في SQLite.
T27: تطابق بيئة البصمة المرجعية مع بيئة القاعدة.
X: رفض تصدير بصمة فوق سلسلة غير سليمة إلا بتجاوز موثّق.
H: الاحتفاظ بتاريخ الحساسيات.
"""
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

import tamper
from conftest import AUDIT_KEY, ROOT, make_sqlite_db
from hc import patients as P
from hc.audit import AnchorRefused, check_anchor, export_anchor, make_anchor, verify_chain
from hc.db import write_tx

ANCHOR_KEY = b"separate-anchor-key-held-by-team-0123456789"


def _sqlite_path(tdb):
    return tdb.app_url.replace("sqlite:///", "")


def _try_write_lock_now(path) -> bool:
    """اتصال خام مستقل يحاول حجز قفل الكتابة فورًا (مهلة صفر). True = نجح."""
    c = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError as e:
        assert "locked" in str(e)
        return False
    finally:
        c.close()


# ---------------- R: القراءة لا تحجز قفل الكتابة ----------------

def test_R1_open_read_transaction_does_not_hold_write_lock(tdb):
    if tdb.kind != "sqlite":
        pytest.skip("خاص بـ SQLite؛ PostgreSQL لا يقفل القاعدة عند القراءة أصلًا")
    reg = tdb.session("reg1", "registration")
    P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    with tdb.app.engine.connect() as conn:  # معاملة قراءة مفتوحة
        conn.execute(text("SELECT * FROM patients")).all()
        assert conn.in_transaction()
        assert _try_write_lock_now(_sqlite_path(tdb)) is True


def test_R2_write_transaction_still_reserves_lock(tdb):
    if tdb.kind != "sqlite":
        pytest.skip("خاص بـ SQLite")
    with write_tx(tdb.app.engine) as conn:
        conn.execute(text("SELECT 1")).all()
        assert _try_write_lock_now(_sqlite_path(tdb)) is False  # الكتابة تحجز القفل كما يجب
    assert _try_write_lock_now(_sqlite_path(tdb)) is True       # ويُحرَّر بعد انتهاء المعاملة


def test_R3_concurrent_reads_and_a_write_while_reads_are_open(tdb):
    reg = tdb.session("reg1", "registration")
    P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    holders, release = 3, threading.Event()
    opened = threading.Barrier(holders + 1)
    errors = []

    def hold_read():
        try:
            with tdb.app.engine.connect() as conn:
                conn.execute(text("SELECT * FROM patients")).all()
                opened.wait(timeout=10)
                release.wait(timeout=20)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=hold_read) for _ in range(holders)]
    [t.start() for t in ts]
    opened.wait(timeout=10)  # ثلاث معاملات قراءة مفتوحة في الوقت نفسه
    t0 = time.monotonic()
    P.list_patients(tdb.app, reg)  # قراءة رابعة
    P.create_patient(tdb.app, reg, full_name="أثناء القراءة", age=40, allergy_status="none_known")
    elapsed = time.monotonic() - t0
    release.set()
    [t.join() for t in ts]
    assert not errors, errors
    assert elapsed < 2.0, f"الكتابة انتظرت {elapsed:.2f}ث خلف القراءات"
    assert tdb.count("patients") == 2


# ---------------- T27: بيئة البصمة ----------------

def test_T27_anchor_env_must_match_db_env(tdb):
    reg = tdb.session("reg1", "registration")
    P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    r = verify_chain(tdb.admin.engine, AUDIT_KEY)
    for wrong_env in ("dev", "demo"):
        # بصمة موقعة توقيعًا صحيحًا لكنها لبيئة أخرى
        anchor = make_anchor(r, wrong_env, "2026-11-26T00:00:00Z", ANCHOR_KEY)
        problems = check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY)
        assert len(problems) == 1 and "رُفض الفحص" in problems[0] and wrong_env in problems[0]
    ok = make_anchor(r, "test", "2026-11-26T00:00:00Z", ANCHOR_KEY)
    assert check_anchor(tdb.admin.engine, AUDIT_KEY, ok, ANCHOR_KEY) == []


def test_T27b_real_anchor_from_dev_db_rejected_on_test_db(tdb, tmp_path):
    dev = make_sqlite_db(tmp_path, name="dev.db", env="dev")
    dev.user("devreg", "registration")
    anchor, _ = export_anchor(dev.admin.engine, AUDIT_KEY, ANCHOR_KEY, exported_at="t", operator="pytest")
    assert anchor["env"] == "dev"
    problems = check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY)
    assert problems and "رُفض الفحص" in problems[0]


# ---------------- X: التصدير فوق سلسلة غير سليمة ----------------

@pytest.fixture
def broken_chain(tdb):
    reg = tdb.session("reg1", "registration")
    for i in range(3):
        P.create_patient(tdb.app, reg, full_name=f"م{i}", age=30, allergy_status="none_known")
    tamper.disable_audit_protection(tdb)
    tamper.edit_details(tdb, 2, '{"forged":true}')
    assert not verify_chain(tdb.admin.engine, AUDIT_KEY).ok
    return tdb


def test_X1_export_refused_when_chain_broken(broken_chain):
    tdb = broken_chain
    n = tdb.count("audit_log")
    with pytest.raises(AnchorRefused, match="غير سليمة"):
        export_anchor(tdb.admin.engine, AUDIT_KEY, ANCHOR_KEY, exported_at="t", operator="pytest")
    with pytest.raises(AnchorRefused, match="مبررًا"):  # تجاوز بلا مبرر كافٍ
        export_anchor(tdb.admin.engine, AUDIT_KEY, ANCHOR_KEY, exported_at="t", operator="pytest",
                      allow_broken_chain=True, justification="قصير")
    with pytest.raises(AnchorRefused, match="المنفّذ"):
        export_anchor(tdb.admin.engine, AUDIT_KEY, ANCHOR_KEY, exported_at="t", operator=" ",
                      allow_broken_chain=True, justification="مبرر طويل بما يكفي لأغراض الاختبار")
    assert tdb.count("audit_log") == n  # الرفض لا يكتب شيئًا


def test_X2_explicit_override_is_signed_and_audited_and_never_clean(broken_chain):
    tdb = broken_chain
    why = "فحص جنائي للنسخة الحالية بعد اكتشاف التعديل في السطر 2"
    anchor, report = export_anchor(tdb.admin.engine, AUDIT_KEY, ANCHOR_KEY, exported_at="t",
                                   operator="سارة", allow_broken_chain=True, justification=why)
    assert anchor["chain_ok"] is False
    assert anchor["override"]["operator"] == "سارة" and anchor["override"]["justification"] == why
    row = tdb.audit_rows(action="audit.anchor_export_override")[0]
    assert row["actor_type"] == "script" and row["operator_name"] == "سارة"
    assert json.loads(row["details"])["override"]["justification"] == why
    problems = check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY)
    assert any(p.startswith("تحذير") for p in problems)  # لا تُعامل أبدًا كمرجع نظيف
    # لا يمكن إخفاء التجاوز بتعديل الملف: التوقيع يشمل chain_ok و override
    hidden = {**anchor, "chain_ok": True, "override": None}
    assert "توقيع" in check_anchor(tdb.admin.engine, AUDIT_KEY, hidden, ANCHOR_KEY)[0]


def test_X3_clean_export_is_audited(tdb):
    tdb.user("reg1", "registration")
    anchor, _ = export_anchor(tdb.admin.engine, AUDIT_KEY, ANCHOR_KEY, exported_at="t", operator="داليا")
    assert anchor["chain_ok"] is True and anchor["override"] is None
    assert tdb.audit_rows(action="audit.anchor_export")[0]["operator_name"] == "داليا"
    assert check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY) == []


def test_X4_cli_refuses_then_accepts_documented_override(tmp_path):
    db = make_sqlite_db(tmp_path)
    db.user("reg1", "registration")
    env = {k: v for k, v in os.environ.items() if not k.startswith("HC_")}
    env.update({"HC_ENV": "test", "HC_TEST_DATABASE_URL": db.app_url, "HC_DISPLAY_TZ": "Asia/Aden",
                "HC_TEST_AUDIT_HMAC_KEY": AUDIT_KEY.decode(), "HC_ANCHOR_KEY": ANCHOR_KEY.decode()})
    tamper.disable_audit_protection(db)
    tamper.edit_details(db, 1, '{"forged":true}')
    out_dir = tmp_path / "team_anchors"
    out_dir.mkdir()

    def run(*args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_audit.py"), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    r1 = run("export-anchor", "--out", str(out_dir / "a1.json"), "--operator", "داليا")
    assert r1.returncode == 3 and "غير سليمة" in r1.stderr
    assert not (out_dir / "a1.json").exists()
    r2 = run("export-anchor", "--out", str(out_dir / "a2.json"), "--operator", "داليا",
             "--allow-broken-chain", "--justification", "توثيق حالة السجل قبل التحقيق في التعديل")
    assert r2.returncode == 0 and "تجاوز استثنائي" in r2.stderr
    saved = json.loads((out_dir / "a2.json").read_text("utf-8"))
    assert saved["chain_ok"] is False and saved["override"]["operator"] == "داليا"
    r3 = run("export-anchor", "--out", str(out_dir / "a2.json"), "--operator", "داليا",
             "--allow-broken-chain", "--justification", "محاولة استبدال ملف بصمة موجود مسبقًا")
    assert r3.returncode != 0 and "موجود مسبقًا" in r3.stderr


# ---------------- H: تاريخ الحساسيات ----------------

@pytest.fixture
def with_allergens(tdb):
    return tdb, tdb.add_fake_allergens(), tdb.session("reg1", "registration")


def test_H1_removal_keeps_history_with_who_when_why(with_allergens):
    tdb, ids, reg = with_allergens
    a, b = ids[0], ids[1]
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=[a, b])
    g = P.set_allergies(tdb.app, reg, p["id"], expected_version=1, allergy_status="has_allergies",
                        allergen_ids=[b], removal_reason="أُدخلت بالخطأ عند التسجيل")
    assert g["allergen_ids"] == [b]
    hist = P.allergy_history(tdb.app, reg, p["id"])
    assert len(hist) == 2
    ha = next(h for h in hist if h["allergen_id"] == a)
    assert ha["removed_at"] and ha["removed_by"] == "reg1" and ha["removal_reason"] == "أُدخلت بالخطأ عند التسجيل"
    hb = next(h for h in hist if h["allergen_id"] == b)
    assert hb["removed_at"] is None
    d = json.loads(tdb.audit_rows(action="patient.set_allergies")[-1]["details"])
    assert d["removed_allergen_ids"] == [a] and d["removal_reason"] == "أُدخلت بالخطأ عند التسجيل"
    assert d["before"]["allergen_ids"] == [a, b] and d["after"]["allergen_ids"] == [b]


def test_H2_readding_creates_new_row_old_row_untouched(with_allergens):
    tdb, ids, reg = with_allergens
    a = ids[0]
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=[a])
    P.set_allergies(tdb.app, reg, p["id"], expected_version=1, allergy_status="none_known",
                    removal_reason="سبب اختبار")  # أُضيف بعد جعل السبب إلزاميًا (المرحلة الثانية)
    P.set_allergies(tdb.app, reg, p["id"], expected_version=2, allergy_status="has_allergies", allergen_ids=[a])
    hist = P.allergy_history(tdb.app, reg, p["id"])
    assert [h["allergen_id"] for h in hist] == [a, a]
    assert hist[0]["removed_at"] is not None and hist[1]["removed_at"] is None
    assert P.get_patient(tdb.app, reg, p["id"])["allergen_ids"] == [a]


def test_H3_history_cannot_be_deleted_or_rewritten(with_allergens):
    tdb, ids, reg = with_allergens
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=ids[:1])
    P.set_allergies(tdb.app, reg, p["id"], expected_version=1, allergy_status="none_known", removal_reason="سبب")
    attacks = [
        "DELETE FROM patient_allergies",
        "UPDATE patient_allergies SET removed_at=NULL, removed_by=NULL, removal_reason=NULL",  # إلغاء الإزالة
        "UPDATE patient_allergies SET removal_reason='سبب آخر'",                              # إعادة كتابة السبب
        "UPDATE patient_allergies SET recorded_by=recorded_by, removed_at='2000-01-01T00:00:00Z'",
    ]
    for sql in attacks:
        with pytest.raises(DBAPIError):
            with tdb.admin.engine.begin() as c:
                c.execute(text(sql))
    h = P.allergy_history(tdb.app, reg, p["id"])[0]
    assert h["removal_reason"] == "سبب"


def test_H4_only_one_current_row_per_allergen(with_allergens):
    tdb, ids, reg = with_allergens
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=ids[:1])
    with pytest.raises(IntegrityError):
        with tdb.admin.engine.begin() as c:
            c.execute(text("INSERT INTO patient_allergies (patient_id, allergen_id, recorded_by)"
                           " SELECT :p, :a, id FROM users LIMIT 1"), {"p": p["id"], "a": ids[0]})


def test_H5_app_db_account_cannot_delete_allergy_history(with_allergens):
    tdb, ids, reg = with_allergens
    if tdb.kind != "postgresql":
        pytest.skip("صلاحيات الحسابات خاصة بـ PostgreSQL؛ في SQLite يحمي المشغّل فقط (H3)")
    P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=ids[:1])
    with pytest.raises(DBAPIError, match="permission denied"):
        with tdb.app.engine.begin() as c:
            c.execute(text("DELETE FROM patient_allergies"))
    with pytest.raises(DBAPIError, match="permission denied"):
        with tdb.app.engine.begin() as c:
            c.execute(text("UPDATE patient_allergies SET allergen_id = allergen_id"))


def test_H6_removal_reason_too_long_rejected(with_allergens):
    tdb, ids, reg = with_allergens
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=ids[:1])
    from hc.errors import ValidationFailed
    with pytest.raises(ValidationFailed):
        P.set_allergies(tdb.app, reg, p["id"], expected_version=1, allergy_status="none_known",
                        removal_reason="س" * 501)
    assert P.get_patient(tdb.app, reg, p["id"])["allergen_ids"] == ids[:1]
    assert P.allergy_history(tdb.app, reg, p["id"])[0]["removed_at"] is None
