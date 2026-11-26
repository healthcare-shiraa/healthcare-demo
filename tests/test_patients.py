"""P: المرضى والحساسيات."""
import json
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hc import patients as P
from hc.errors import Conflict, ValidationFailed


@pytest.fixture
def reg(tdb):
    return tdb.session("reg1", "registration")


@pytest.mark.parametrize("kwargs", [
    dict(full_name="", age=30, allergy_status="none_known"),
    dict(full_name="   ", age=30, allergy_status="none_known"),
    dict(full_name="س" * 101, age=30, allergy_status="none_known"),
    dict(full_name="مريض", age=17, allergy_status="none_known"),
    dict(full_name="مريض", age="abc", allergy_status="none_known"),
    dict(full_name="مريض", age="30.5", allergy_status="none_known"),
    dict(full_name="مريض", age=True, allergy_status="none_known"),
    dict(full_name="مريض", age=30, allergy_status=None),
    dict(full_name="مريض", age=30, allergy_status="unknown"),
    dict(full_name="مريض", age=30, allergy_status="has_allergies", allergen_ids=[]),
])
def test_P1_validation_rejected_nothing_saved(tdb, reg, kwargs):
    with pytest.raises(ValidationFailed) as ei:
        P.create_patient(tdb.app, reg, **kwargs)
    assert ei.value.audit_persisted is True
    assert tdb.count("patients") == 0
    assert tdb.count("audit_log", "action='patient.create' AND outcome='validation_error'") == 1


def test_P1b_allergen_consistency(tdb, reg):
    ids = tdb.add_fake_allergens()
    with pytest.raises(ValidationFailed):
        P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known", allergen_ids=ids[:1])
    with pytest.raises(ValidationFailed):
        P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=[99999])
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="has_allergies", allergen_ids=ids[:2])
    assert p["allergen_ids"] == ids[:2] and p["mrn"] == "HC-0001"


def test_P2_concurrent_creates_get_unique_mrns(tdb, reg):
    n = 10
    results, errors = [], []
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        try:
            results.append(P.create_patient(tdb.app, reg, full_name=f"مريض {i}", age=30,
                                            allergy_status="none_known")["mrn"])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    assert sorted(results) == [f"HC-{i:04d}" for i in range(1, n + 1)]
    assert tdb.count("patients") == n


def test_P3_stale_version_rejected(tdb, reg):
    p = P.create_patient(tdb.app, reg, full_name="أصل", age=30, allergy_status="none_known")
    reg2 = tdb.session("reg2", "registration")
    P.update_patient(tdb.app, reg, p["id"], expected_version=1, full_name="تعديل أول", age=31)
    with pytest.raises(Conflict) as ei:
        P.update_patient(tdb.app, reg2, p["id"], expected_version=1, full_name="تعديل ثانٍ", age=32)
    assert ei.value.audit_persisted is True
    cur = P.get_patient(tdb.app, reg, p["id"])
    assert (cur["full_name"], cur["age"], cur["row_version"]) == ("تعديل أول", 31, 2)
    row = tdb.audit_rows(action="patient.update", outcome="success")[0]
    d = json.loads(row["details"])
    assert d["before"]["full_name"] == "أصل" and d["after"]["full_name"] == "تعديل أول"


def test_P3b_truly_simultaneous_updates_one_wins(tdb, reg):
    p = P.create_patient(tdb.app, reg, full_name="أصل", age=30, allergy_status="none_known")
    outcomes = []
    barrier = threading.Barrier(2)

    def worker(name):
        barrier.wait()
        try:
            P.update_patient(tdb.app, reg, p["id"], expected_version=1, full_name=name, age=40)
            outcomes.append("ok")
        except Conflict:
            outcomes.append("conflict")

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("أ", "ب")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(outcomes) == ["conflict", "ok"]
    assert P.get_patient(tdb.app, reg, p["id"])["row_version"] == 2


def test_P4_not_recorded_is_kept_distinct(tdb, reg):
    ids = tdb.add_fake_allergens()
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="not_recorded")
    g = P.get_patient(tdb.app, reg, p["id"])
    assert g["allergy_status"] == "not_recorded" and g["allergen_ids"] == []
    g = P.set_allergies(tdb.app, reg, p["id"], expected_version=1, allergy_status="has_allergies",
                        allergen_ids=[ids[0], ids[2]])
    assert g["allergen_ids"] == [ids[0], ids[2]] and g["row_version"] == 2
    g = P.set_allergies(tdb.app, reg, p["id"], expected_version=2, allergy_status="none_known",
                        removal_reason="سبب اختبار")  # أُضيف بعد جعل السبب إلزاميًا (المرحلة الثانية)
    assert g["allergen_ids"] == [] and g["allergy_status"] == "none_known"
    d = json.loads(tdb.audit_rows(action="patient.set_allergies")[-1]["details"])
    assert d["before"]["allergen_ids"] == [ids[0], ids[2]] and d["after"]["allergen_ids"] == []


def test_P5_mrn_immutable_and_no_delete(tdb, reg):
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    for sql in ("UPDATE patients SET mrn='HC-9999' WHERE id=:i", "DELETE FROM patients WHERE id=:i"):
        with pytest.raises(DBAPIError):
            with tdb.admin.engine.begin() as c:
                c.execute(text(sql), {"i": p["id"]})
    assert P.get_patient(tdb.app, reg, p["id"])["mrn"] == "HC-0001"
