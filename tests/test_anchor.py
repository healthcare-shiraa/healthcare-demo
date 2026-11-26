"""T21–T26: سلسلة HMAC والبصمة المرجعية الخارجية — ما تكشفه وما لا تكشفه."""
import shutil
import uuid

import pytest
from sqlalchemy import create_engine

import tamper
from conftest import AUDIT_KEY, PG_SUPER, _pg_url
from hc import patients as P
from hc.audit import check_anchor, make_anchor, verify_chain
from hc.db import make_engine

ANCHOR_KEY = b"separate-anchor-key-held-by-team-0123456789"
WRONG_KEY = b"attacker-guess-key-not-the-real-one-000000"


@pytest.fixture
def seeded(tdb):
    reg = tdb.session("reg1", "registration")
    for i in range(5):
        P.create_patient(tdb.app, reg, full_name=f"م{i}", age=30, allergy_status="none_known")
    return tdb, reg


def anchor_now(tdb):
    r = verify_chain(tdb.admin.engine, AUDIT_KEY)
    assert r.ok
    return make_anchor(r, "test", "2026-11-26T00:00:00Z", ANCHOR_KEY)


def test_T21_tail_deletion_chain_blind_anchor_detects(seeded):
    tdb, _ = seeded
    anchor = anchor_now(tdb)
    tamper.disable_audit_protection(tdb)
    tamper.delete_seq(tdb, "seq > :n", n=anchor["last_seq"] - 3)
    assert verify_chain(tdb.admin.engine, AUDIT_KEY).ok          # السلسلة وحدها لا تكتشف
    assert check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY)  # المقارنة تكتشف


def test_T22_restore_older_copy_chain_blind_anchor_detects(seeded, tmp_path):
    tdb, reg = seeded
    if tdb.kind == "sqlite":
        src = tdb.app_url.replace("sqlite:///", "")
        tdb.admin.engine.dispose()
        old_copy = tmp_path / "old_copy.db"
        shutil.copy(src, old_copy)
        for ext in ("-wal", "-shm"):
            try:
                shutil.copy(src + ext, str(old_copy) + ext)
            except FileNotFoundError:
                pass
        old_engine = make_engine(f"sqlite:///{old_copy}")
    else:
        tdb.app.engine.dispose()
        tdb.admin.engine.dispose()
        old_name = f"hc_{uuid.uuid4().hex[:10]}_test"
        sup = create_engine(PG_SUPER, isolation_level="AUTOCOMMIT")
        with sup.connect() as c:
            c.exec_driver_sql(f'CREATE DATABASE "{old_name}" TEMPLATE "{tdb.db_name}" OWNER hc_owner')
        sup.dispose()
        old_engine = make_engine(_pg_url("hc_owner", old_name))
    # العمل يستمر بعد أخذ النسخة القديمة، ثم تُصدَّر البصمة
    for i in range(3):
        P.create_patient(tdb.app, reg, full_name=f"لاحق{i}", age=30, allergy_status="none_known")
    anchor = anchor_now(tdb)
    # «الاستبدال»: التحقق يجري على النسخة القديمة
    assert verify_chain(old_engine, AUDIT_KEY).ok
    problems = check_anchor(old_engine, AUDIT_KEY, anchor, ANCHOR_KEY)
    assert problems
    old_engine.dispose()
    if tdb.kind == "postgresql":
        from conftest import drop_pg_db
        drop_pg_db(old_name)


def test_T23_recompute_with_wrong_key_detected(seeded):
    tdb, _ = seeded
    tamper.disable_audit_protection(tdb)
    tamper.edit_details(tdb, 4, '{"forged":true}')
    tamper.recompute_chain(tdb, WRONG_KEY, from_seq=4)
    assert not verify_chain(tdb.admin.engine, AUDIT_KEY).ok


def test_T24_correct_key_hides_from_chain_but_anchor_detects(seeded):
    tdb, _ = seeded
    anchor = anchor_now(tdb)
    tamper.disable_audit_protection(tdb)
    tamper.edit_details(tdb, 4, '{"forged":true}')
    tamper.recompute_chain(tdb, AUDIT_KEY, from_seq=4)
    assert verify_chain(tdb.admin.engine, AUDIT_KEY).ok    # حد: من يملك المفتاح يخفي التعديل عن السلسلة
    problems = check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY)
    assert any("تغيّرت" in p for p in problems)            # البصمة الخارجية تكشفه (السطر قبل وقت التصدير)


def test_T25_correct_key_after_anchor_NOT_detected(seeded):
    """إثبات حد: تلاعب بالمفتاح الصحيح في أسطر أُضيفت بعد تصدير البصمة لا يُكتشف."""
    tdb, reg = seeded
    anchor = anchor_now(tdb)
    for i in range(3):
        P.create_patient(tdb.app, reg, full_name=f"بعد{i}", age=30, allergy_status="none_known")
    target = anchor["last_seq"] + 2
    tamper.disable_audit_protection(tdb)
    tamper.edit_details(tdb, target, '{"forged":true}')
    tamper.recompute_chain(tdb, AUDIT_KEY, from_seq=target)
    assert verify_chain(tdb.admin.engine, AUDIT_KEY).ok
    assert check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY) == []  # لم يُكتشف


def test_T26_anchor_file_tamper_or_wrong_key_rejected(seeded):
    tdb, _ = seeded
    anchor = anchor_now(tdb)
    forged = {**anchor, "last_seq": anchor["last_seq"] - 2}
    assert "توقيع" in check_anchor(tdb.admin.engine, AUDIT_KEY, forged, ANCHOR_KEY)[0]
    assert "توقيع" in check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, WRONG_KEY)[0]
    assert check_anchor(tdb.admin.engine, AUDIT_KEY, anchor, ANCHOR_KEY) == []
