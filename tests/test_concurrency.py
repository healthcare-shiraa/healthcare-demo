"""C: منع التكرار والتزامن على جدول اختبار (probe) بالبنية نفسها المقررة للجرعات:
سطر يُقفل، ثم إعادة فحص، ثم تسجيل واحد فريد. الاختبار النهائي على جداول الجرعات لاحقًا.
"""
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hc.audit import ActionResult, run_action
from hc.auth import require_user
from hc.errors import Conflict
from hc.locking import lock_row

ROUNDS = 50


def claim(tdb, session, item_id, *, use_lock=True):
    def fn(conn):
        user = require_user(conn, session, {"nurse"})
        if use_lock:
            lock_row(conn, "probe_items", item_id)
            existing = conn.execute(text("SELECT claimed_by FROM probe_claims WHERE item_id=:i"),
                                    {"i": item_id}).scalar_one_or_none()
            if existing is not None:
                raise Conflict("سُجّل هذا العنصر مسبقًا", entity_type="probe_item", entity_id=str(item_id),
                               details={"claimed_by": existing})
        conn.execute(text("INSERT INTO probe_claims(item_id, claimed_by) VALUES (:i, :u)"),
                     {"i": item_id, "u": user["id"]})
        return ActionResult(entity_type="probe_item", entity_id=str(item_id))
    return run_action(tdb.app, session.actor(), "probe.claim", fn)


def add_items(tdb, n):
    with tdb.admin.engine.begin() as c:
        for i in range(1, n + 1):
            c.execute(text("INSERT INTO probe_items(id) VALUES (:i)"), {"i": i})


def race(tdb, sessions, item_id, **kw):
    out = []
    barrier = threading.Barrier(len(sessions))

    def worker(s):
        barrier.wait()
        try:
            claim(tdb, s, item_id, **kw)
            out.append("ok")
        except Conflict:
            out.append("conflict")
        except Exception as e:  # noqa: BLE001
            out.append(f"other:{type(e).__name__}:{e}")

    ts = [threading.Thread(target=worker, args=(s,)) for s in sessions]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def test_C1_C2_two_nurses_same_item_exactly_one_wins(tdb):
    n1, n2 = tdb.session("nurse1", "nurse"), tdb.session("nurse2", "nurse")
    add_items(tdb, ROUNDS)
    tally = {"ok": 0, "conflict": 0, "other": []}
    for item in range(1, ROUNDS + 1):
        res = race(tdb, [n1, n2], item)
        assert sorted(res) == ["conflict", "ok"], (item, res)
        tally["ok"] += 1
        tally["conflict"] += 1
    assert tdb.count("probe_claims") == ROUNDS
    assert tdb.count("audit_log", "action='probe.claim' AND outcome='success'") == ROUNDS
    assert tdb.count("audit_log", "action='probe.claim' AND outcome='conflict'") == ROUNDS


def test_C3_unique_constraint_is_last_line_of_defence(tdb):
    n1 = tdb.session("nurse1", "nurse")
    add_items(tdb, 1)
    claim(tdb, n1, 1)
    with pytest.raises(IntegrityError):
        with tdb.admin.engine.begin() as c:
            c.execute(text("INSERT INTO probe_claims(item_id, claimed_by) VALUES (1, 999)"))
    assert tdb.count("probe_claims") == 1


def test_C4_unique_violation_handled_and_connection_stays_usable(tdb):
    """بدون قفل: يصطدم الثاني بالقيد الفريد. يجب أن يتحول ذلك إلى Conflict موثّق،
    وألا تبقى المعاملة في حالة فاشلة (في PostgreSQL: current transaction is aborted)."""
    n1 = tdb.session("nurse1", "nurse")
    add_items(tdb, 2)
    claim(tdb, n1, 1, use_lock=False)
    with pytest.raises(Conflict) as ei:
        claim(tdb, n1, 1, use_lock=False)
    assert ei.value.code == "unique_violation" and ei.value.audit_persisted is True
    claim(tdb, n1, 2, use_lock=False)  # الاتصال صالح للعملية التالية
    assert tdb.count("probe_claims") == 2


def test_C5_only_nurse_role_can_claim(tdb):
    d = tdb.session("doc1", "doctor")
    add_items(tdb, 1)
    from hc.errors import PermissionDenied
    with pytest.raises(PermissionDenied):
        claim(tdb, d, 1)
    assert tdb.count("probe_claims") == 0
