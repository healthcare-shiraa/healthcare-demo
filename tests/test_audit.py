"""A: سجل التدقيق — المعاملات، الرفض، الأخطاء، عدم القابلية للتعديل."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import hc.audit as audit_mod
import tamper
from conftest import AUDIT_KEY
from hc import patients as P
from hc.audit import ActionResult, Actor, Ctx, run_action, verify_chain
from hc.db import make_engine
from hc.errors import OperationFailed


@pytest.fixture
def reg(tdb):
    return tdb.session("reg1", "registration")


def test_A1_success_saves_data_and_audit_together(tdb, reg):
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    row = tdb.audit_rows(action="patient.create")[0]
    assert row["outcome"] == "success" and row["entity_id"] == str(p["id"])
    assert row["actor_username"] == "reg1" and row["actor_role"] == "registration"
    assert verify_chain(tdb.admin.engine, AUDIT_KEY).ok


def test_A3_audit_failure_on_success_path_rolls_back_operation(tdb, reg, monkeypatch):
    real_append = audit_mod.append
    calls = {"n": 0}

    def flaky_append(conn, key, **kw):
        calls["n"] += 1
        if calls["n"] == 1:  # أول استدعاء = قيد النجاح داخل معاملة العملية
            raise RuntimeError("عطل مصطنع أثناء كتابة السجل")
        return real_append(conn, key, **kw)

    monkeypatch.setattr(audit_mod, "append", flaky_append)
    with pytest.raises(OperationFailed) as ei:
        P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    assert ei.value.audit_persisted is True and ei.value.connection_failure is False
    assert tdb.count("patients") == 0  # العملية لم تُحفظ بلا قيدها
    assert tdb.count("audit_log", "action='patient.create' AND outcome='error'") == 1


def test_A7_operation_error_with_live_connection_audited_separately(tdb, reg):
    def fn(conn):
        conn.execute(text("UPDATE counters SET value = value + 100 WHERE name='patient_mrn'"))
        raise RuntimeError("خطأ في منتصف العملية")

    with pytest.raises(OperationFailed) as ei:
        run_action(tdb.app, reg.actor(), "test.midway_error", fn)
    assert ei.value.audit_persisted is True
    with tdb.admin.engine.connect() as c:
        assert c.execute(text("SELECT value FROM counters WHERE name='patient_mrn'")).scalar_one() == 0
    r = tdb.audit_rows(action="test.midway_error")[0]
    assert r["outcome"] == "error" and json.loads(r["details"])["error_type"] == "RuntimeError"


def test_A8_if_separate_audit_also_fails_we_do_not_claim_it(tdb, reg, monkeypatch, tmp_path):
    oplog = tmp_path / "oplog.jsonl"
    monkeypatch.setenv("HC_OPLOG_PATH", str(oplog))

    def always_fail(conn, key, **kw):
        raise RuntimeError("السجل معطل")

    monkeypatch.setattr(audit_mod, "append", always_fail)
    with pytest.raises(OperationFailed) as ei:
        P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    assert ei.value.audit_persisted is False
    assert "تعذر تسجيل الخطأ في قاعدة البيانات" in ei.value.message
    events = [json.loads(l)["event"] for l in oplog.read_text("utf-8").splitlines()]
    assert "audit_write_failed" in events and "operation_failed" in events


def test_A6_connection_failure_goes_to_external_log_only(tdb, tmp_path, monkeypatch):
    oplog = tmp_path / "oplog.jsonl"
    monkeypatch.setenv("HC_OPLOG_PATH", str(oplog))
    if tdb.kind == "sqlite":
        bad_url = f"sqlite:///{tmp_path}/no/such/dir/x.db"
    else:
        bad_url = "postgresql+psycopg://hc_app@/nodb?host=/tmp&port=1"  # لا خادم على هذا المنفذ
    broken = Ctx(engine=make_engine(bad_url), hmac_key=AUDIT_KEY, env="test")
    with pytest.raises(OperationFailed) as ei:
        run_action(broken, Actor(type="anonymous"), "test.conn_fail", lambda c: ActionResult())
    assert ei.value.connection_failure is True and ei.value.audit_persisted is False
    assert "تعذر الاتصال بقاعدة البيانات" in ei.value.message
    ev = [json.loads(l) for l in oplog.read_text("utf-8").splitlines()]
    assert any(e["event"] == "operation_failed_connection" and e["audit_persisted"] is False for e in ev)
    assert tdb.count("audit_log", "action='test.conn_fail'") == 0


@pytest.mark.parametrize("sql", ["UPDATE audit_log SET details='{}' WHERE seq=1",
                                 "DELETE FROM audit_log WHERE seq=1"])
def test_A4_audit_log_append_only_even_for_owner(tdb, reg, sql):
    with pytest.raises(DBAPIError):
        with tdb.admin.engine.begin() as c:
            c.execute(text(sql))
    assert verify_chain(tdb.admin.engine, AUDIT_KEY).ok


def test_A4b_truncate_blocked_postgres(tdb, reg):
    if tdb.kind != "postgresql":
        pytest.skip("TRUNCATE غير موجود في SQLite")
    with pytest.raises(DBAPIError):
        with tdb.admin.engine.begin() as c:
            c.exec_driver_sql("TRUNCATE audit_log")


def test_A5_middle_edit_and_middle_delete_detected(tdb, reg):
    for i in range(4):
        P.create_patient(tdb.app, reg, full_name=f"م{i}", age=30, allergy_status="none_known")
    tamper.disable_audit_protection(tdb)
    tamper.edit_details(tdb, 3, '{"forged":true}')
    r = verify_chain(tdb.admin.engine, AUDIT_KEY)
    assert not r.ok and any("السطر 3" in p for p in r.problems)
    tamper.edit_details(tdb, 3, tamper.rows(tdb)[2]["details"])  # (يبقى مكسورًا) ثم حذف من الوسط
    tamper.delete_seq(tdb, "seq = 4")
    r = verify_chain(tdb.admin.engine, AUDIT_KEY)
    assert any("فجوة" in p for p in r.problems)


def test_A9_rejections_never_save_data(tdb, reg):
    s = tdb.session("doc1", "doctor")
    with pytest.raises(Exception):
        P.create_patient(tdb.app, s, full_name="م", age=30, allergy_status="none_known")
    with tdb.admin.engine.connect() as c:
        assert c.execute(text("SELECT value FROM counters WHERE name='patient_mrn'")).scalar_one() == 0
    assert tdb.count("patients") == 0
