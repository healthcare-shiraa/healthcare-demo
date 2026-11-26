"""M: دورة الدواء — كل القواعد والأدوية هنا وهمية (بيئة test) لاختبار آليات النظام فقط."""
import json
import threading
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from conftest import AUDIT_KEY
from hc import administration as AD
from hc import patients as P
from hc import prescriptions as RX
from hc import review as RV
from hc.audit import Ctx, verify_chain
from hc.db import db_now
from hc.errors import Conflict, PermissionDenied, ValidationFailed
from hc.reference import ConfigMissing
from hc.rules import RulesetError, load_ruleset
from hc.timefmt import fmt_utc, parse_utc

A_ALLERGY, B_ALLERGY = "حساسية-اختبار-أ", "حساسية-اختبار-ب"
MA, MB, MC, MD, ME = (f"دواء-اختبار-{k}" for k in ("أ", "ب", "ج", "د", "هـ"))


def now_of(tdb):
    with tdb.admin.engine.connect() as c:
        return parse_utc(db_now(c))


class World:
    def __init__(self, tdb, **policies):
        self.tdb = tdb
        tdb.setup_cycle(**policies)
        self.ref = tdb.ref()
        self.reg = tdb.session("reg1", "registration")
        self.doc = tdb.session("doc1", "doctor")
        self.doc2 = tdb.session("doc2", "doctor")
        self.ph = tdb.session("ph1", "pharmacist")
        self.nu = tdb.session("nu1", "nurse")
        self.nu2 = tdb.session("nu2", "nurse")

    def patient(self, allergies=(), status=None):
        ids = [self.ref[a] for a in allergies]
        st = status or ("has_allergies" if ids else "none_known")
        return P.create_patient(self.tdb.app, self.reg, full_name="مريض اصطناعي", age=40,
                                allergy_status=st, allergen_ids=ids)

    def start(self, minutes=1):
        return now_of(self.tdb).replace(second=0, microsecond=0) + timedelta(minutes=minutes)

    def rx(self, patient, med, *, dose="10", freq="test-q8h", days=1, doctor=None, start=None):
        return RX.create_prescription(self.tdb.app, doctor or self.doc, patient_id=patient["id"],
                                      medication_id=self.ref[med], dose=dose, frequency_id=self.ref[freq],
                                      start_at=start or self.start(), duration_days=days)["prescription_id"]

    def approve(self, rx_id):
        return RV.approve(self.tdb.app, self.ph, rx_id)

    def alerts(self, rx_id):
        return RX.get_detail(self.tdb.app, self.ph, rx_id)["alerts"]

    def doses(self, rx_id):
        return RX.get_detail(self.tdb.app, self.nu, rx_id)["doses"]

    def give(self, dose_id, patient, *, nurse=None, dose="10", at=None, **kw):
        return AD.record_administration(self.tdb.app, nurse or self.nu, dose_id, verified_mrn=patient["mrn"],
                                        verified_medication=True, verified_pharmacist_decision=True,
                                        outcome="given", actual_dose=dose,
                                        administered_at=at or now_of(self.tdb), **kw)

    def not_given(self, dose_id, patient, reason="patient_unavailable", **kw):
        return AD.record_administration(self.tdb.app, self.nu, dose_id, verified_mrn=patient["mrn"],
                                        verified_medication=True, verified_pharmacist_decision=True,
                                        outcome="not_given", not_given_reason_id=self.ref[reason], **kw)

    def past_approved_rx(self, patient, med, *, hours_ago: float, interval_h=1, days=1, dose="10"):
        """إعداد اختبار: وصفة معتمدة بدأت في الماضي (لا يمكن إنشاؤها من الواجهة؛ تُدرج مباشرة بحساب المالك)."""
        start = now_of(self.tdb) - timedelta(hours=hours_ago)
        end = start + timedelta(days=days)
        with self.tdb.admin.engine.begin() as c:
            freq = c.execute(text("SELECT id FROM frequencies WHERE interval_hours = :h"),
                             {"h": interval_h}).scalar_one_or_none()
            if freq is None:
                freq = c.execute(text("INSERT INTO frequencies (code, label, interval_hours, is_synthetic)"
                                      " VALUES (:c, :c, :h, :t) RETURNING id"),
                                 {"c": f"test-q{interval_h}h-x", "h": interval_h, "t": True}).scalar_one()
                c.execute(text("INSERT INTO medication_frequencies VALUES (:m, :f)"), {"m": self.ref[med], "f": freq})
            uid = lambda u: c.execute(text("SELECT id FROM users WHERE username=:u"), {"u": u}).scalar_one()  # noqa: E731
            rx = c.execute(text(
                "INSERT INTO prescriptions (patient_id, medication_id, dose, frequency_id, start_at, end_at,"
                " prescriber_id, ruleset_version_id, status) VALUES (:p, :m, :d, :f, :s, :e, :u,"
                " (SELECT max(id) FROM ruleset_versions), 'approved') RETURNING id"),
                {"p": patient["id"], "m": self.ref[med], "d": dose, "f": freq, "s": fmt_utc(start),
                 "e": fmt_utc(end), "u": uid("doc1")}).scalar_one()
            c.execute(text("INSERT INTO pharmacist_reviews (prescription_id, pharmacist_id, decision)"
                           " VALUES (:x, :u, 'approved')"), {"x": rx, "u": uid("ph1")})
            t, n = start, 0
            while t < end:
                n += 1
                c.execute(text("INSERT INTO scheduled_doses (prescription_id, dose_number, scheduled_at, planned_dose)"
                               " VALUES (:x, :n, :t, :d)"), {"x": rx, "n": n, "t": fmt_utc(t), "d": dose})
                t += timedelta(hours=interval_h)
        return rx


@pytest.fixture
def w(tdb):
    return World(tdb)


# ------------------------------------------------------------ الإنشاء

def test_M1_no_ruleset_no_prescribing(tdb):
    tdb.add_fake_allergens()
    reg, doc = tdb.session("reg1", "registration"), tdb.session("doc1", "doctor")
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")
    with pytest.raises(ConfigMissing):
        RX.create_prescription(tdb.app, doc, patient_id=p["id"], medication_id=1, dose="1", frequency_id=1,
                               start_at=now_of(tdb) + timedelta(hours=1), duration_days=1)
    assert tdb.count("prescriptions") == 0


def test_M2_allergy_not_recorded_blocks_sending(w):
    p = w.patient(status="not_recorded")
    with pytest.raises(ValidationFailed) as ei:
        w.rx(p, MA)
    assert ei.value.code == "allergy_not_recorded" and ei.value.audit_persisted
    assert w.tdb.count("prescriptions") == 0


@pytest.mark.parametrize("who", ["reg", "ph", "nu"])
def test_M3_only_doctor_prescribes(w, who):
    p = w.patient()
    with pytest.raises(PermissionDenied):
        w.rx(p, MA, doctor=getattr(w, who))
    assert w.tdb.count("prescriptions") == 0


@pytest.mark.parametrize("kw", [dict(dose="0"), dict(dose="101"), dict(dose="abc"), dict(days=8), dict(days=0)])
def test_M4_input_validation(w, kw):
    p = w.patient()
    with pytest.raises(ValidationFailed):
        w.rx(p, MA, **kw)
    assert w.tdb.count("prescriptions") == 0


def test_M4b_start_in_past_rejected(w):
    p = w.patient()
    with pytest.raises(ValidationFailed):
        w.rx(p, MA, start=now_of(w.tdb) - timedelta(hours=2))


def test_M5_alerts_generated_by_rules(w):
    p = w.patient(allergies=[A_ALLERGY])
    r1 = w.rx(p, MA)                     # T-R1 حساسية
    assert [a["code"] for a in w.alerts(r1)] == ["T-R1"]
    r2 = w.rx(p, MB)
    r3 = w.rx(p, MC)                     # T-R2 تداخل ب+ج يُسجَّل على الأحدث ويشير للأقدم
    al = w.alerts(r3)
    assert [(a["code"], a["related_prescription_id"]) for a in al] == [("T-R2", r2)]
    row = w.tdb.audit_rows(action="rx.create")[-1]
    assert json.loads(row["details"])["alerts"][0]["code"] == "T-R2"


def test_M6_no_alert_still_goes_to_pharmacist_then_doses(w):
    p = w.patient()
    r = w.rx(p, MA, freq="test-q8h", days=1)
    d = RX.get_detail(w.tdb.app, w.doc, r)
    assert d["status"] == "awaiting_pharmacist" and d["alerts"] == [] and d["doses"] == []
    assert w.approve(r) == 3
    assert [x["dose_number"] for x in w.doses(r)] == [1, 2, 3]


# ------------------------------------------------------------ المراجعة

def test_M7_return_only_rule_cannot_be_approved(w):
    p = w.patient()
    w.rx(p, MB)
    r = w.rx(p, MC)
    a = w.alerts(r)[0]
    assert a["state"] == "return_only"
    with pytest.raises(ValidationFailed):
        RV.resolve_alert(w.tdb.app, w.ph, a["id"], evidence={}, note="ملاحظة حرة طويلة لا تكفي")
    with pytest.raises(ValidationFailed) as ei:
        w.approve(r)
    assert ei.value.code == "unresolved_alerts"
    with pytest.raises(ValidationFailed):
        RV.return_to_doctor(w.tdb.app, w.ph, r, note="   ")
    RV.return_to_doctor(w.tdb.app, w.ph, r, note="قاعدة إعادة إلزامية (اختبار)")
    assert RX.get_detail(w.tdb.app, w.doc, r)["status"] == "returned"


def test_M8_conditional_needs_every_requirement(w):
    p = w.patient(allergies=[A_ALLERGY])
    r = w.rx(p, MA)
    a = w.alerts(r)[0]
    q1, q2 = a["requirements"]
    for ev in ({}, {q1["id"]: True}, {q1["id"]: True, q2["id"]: "   "}, {q1["id"]: False, q2["id"]: "نص"}):
        with pytest.raises(ValidationFailed) as ei:
            RV.resolve_alert(w.tdb.app, w.ph, a["id"], evidence=ev, note="تبرير مكتوب لا يكفي وحده")
        assert ei.value.code == "requirements_unmet"
    with pytest.raises(ValidationFailed):
        w.approve(r)
    RV.resolve_alert(w.tdb.app, w.ph, a["id"], evidence={q1["id"]: True, q2["id"]: "وصف تحقق وهمي"})
    assert w.approve(r) == 3
    with pytest.raises(Conflict):  # لا تسوية ثانية ولا اعتماد ثانٍ
        w.approve(r)


def test_M9_non_critical_needs_ack(w):
    p = w.patient()
    w.rx(p, MA)
    r = w.rx(p, MD)                       # T-R3 غير حرج
    a = w.alerts(r)[0]
    assert a["severity"] == "non_critical" and a["state"] == "needs_ack"
    with pytest.raises(ValidationFailed):
        w.approve(r)
    with pytest.raises(ValidationFailed):
        RV.resolve_alert(w.tdb.app, w.ph, a["id"], evidence={})
    RV.acknowledge_alert(w.tdb.app, w.ph, a["id"])
    assert w.approve(r) == 3


def test_M10_stale_check_new_allergy_after_creation(w):
    p = w.patient()
    r = w.rx(p, MA)
    P.set_allergies(w.tdb.app, w.reg, p["id"], expected_version=1, allergy_status="has_allergies",
                    allergen_ids=[w.ref[A_ALLERGY]])
    with pytest.raises(Conflict) as ei:
        w.approve(r)
    assert ei.value.code == "stale_check"
    assert RV.recheck(w.tdb.app, w.ph, r) == 1
    assert [a["code"] for a in w.alerts(r)] == ["T-R1"]
    assert RV.recheck(w.tdb.app, w.ph, r) == 0


def test_M10b_only_pharmacist_reviews(w):
    p = w.patient()
    r = w.rx(p, MA)
    for s in (w.doc, w.nu, w.reg):
        with pytest.raises(PermissionDenied):
            RV.approve(w.tdb.app, s, r)
    assert RX.get_detail(w.tdb.app, w.doc, r)["status"] == "awaiting_pharmacist"


# ------------------------------------------------------------ الإعطاء

def test_M11_nurse_verification(w):
    p = w.patient()
    other = w.patient()
    r = w.rx(p, MA)
    w.approve(r)
    d1 = w.doses(r)[0]["id"]
    with pytest.raises(ValidationFailed) as ei:
        w.give(d1, other)                 # رقم مريض آخر
    assert ei.value.code == "patient_mismatch"
    with pytest.raises(ValidationFailed) as ei:
        AD.record_administration(w.tdb.app, w.nu, d1, verified_mrn=p["mrn"], verified_medication=True,
                                 verified_pharmacist_decision=False, outcome="given", actual_dose="10",
                                 administered_at=now_of(w.tdb))
    assert ei.value.code == "verification_missing"
    with pytest.raises(ValidationFailed) as ei:
        w.give(w.doses(r)[2]["id"], p)    # جرعة بعد 16 ساعة لم يحن موعدها
    assert ei.value.code == "not_due"
    for s in (w.doc, w.ph, w.reg):
        with pytest.raises(PermissionDenied):
            AD.record_administration(w.tdb.app, s, d1, verified_mrn=p["mrn"], verified_medication=True,
                                     verified_pharmacist_decision=True, outcome="given", actual_dose="10",
                                     administered_at=now_of(w.tdb))
    assert w.tdb.count("administrations") == 0


def test_M12_dose_mismatch_not_given_referral_and_no_duplicates(w):
    p = w.patient()
    r = w.rx(p, MA)
    w.approve(r)
    d1 = w.doses(r)[0]["id"]
    with pytest.raises(ValidationFailed) as ei:
        w.give(d1, p, dose="9")
    assert ei.value.code == "dose_mismatch"
    with pytest.raises(ValidationFailed):
        w.not_given(d1, p, reason="other")  # «سبب آخر» يتطلب نصًا
    res = w.not_given(d1, p, reason="dose_mismatch", create_referral=True, referral_note="الجرعة المتاحة مختلفة")
    assert res["referral_id"]
    with pytest.raises(Conflict) as ei:
        w.give(d1, p)
    assert ei.value.code == "already_documented"
    dose = w.doses(r)[0]
    assert dose["status"] == "not_given" and dose["referral_id"] == res["referral_id"]


def test_M13_unresolved_critical_blocks_existing_rx_until_resolved(w):
    p = w.patient()
    a = w.rx(p, MB)
    w.approve(a)
    c = w.rx(p, MC)                       # T-R2: إعادة إلزامية، سياسة الوصفة القائمة: منع
    d1 = w.doses(a)[0]["id"]
    ctx = AD.dose_context(w.tdb.app, w.nu, d1)
    assert ctx["blocks"]
    with pytest.raises(AD.Blocked) as ei:
        w.give(d1, p)
    assert ei.value.audit_persisted is True
    assert w.tdb.count("audit_log", "action='dose.document' AND outcome='denied'") == 1
    assert w.tdb.count("administrations") == 0
    RV.return_to_doctor(w.tdb.app, w.ph, c, note="إعادة (اختبار)")
    assert w.give(d1, p)["outcome"] == "given"


def test_M13b_not_given_always_documentable_even_when_blocked(w):
    p = w.patient()
    a = w.rx(p, MB)
    w.approve(a)
    w.rx(p, MC)
    d1 = w.doses(a)[0]["id"]
    assert w.not_given(d1, p)["outcome"] == "not_given"


def test_M14_warn_only_policy_allows_with_recorded_warning(w):
    p = w.patient()
    a = w.rx(p, MC)
    w.approve(a)
    w.rx(p, ME)                           # T-R5 حرج، سياسة الوصفة القائمة: تحذير فقط
    d1 = w.doses(a)[0]["id"]
    res = w.give(d1, p)
    assert res["warnings"] and "T-R5" in res["warnings"][0]
    assert w.doses(a)[0]["warnings"] == res["warnings"]


def test_M15_new_undocumented_allergy_blocks_given(w):
    p = w.patient()
    a = w.rx(p, MC)
    w.approve(a)
    P.set_allergies(w.tdb.app, w.reg, p["id"], expected_version=1, allergy_status="has_allergies",
                    allergen_ids=[w.ref[B_ALLERGY]])  # T-R6 تخص دواء-ج
    with pytest.raises(AD.Blocked) as ei:
        w.give(w.doses(a)[0]["id"], p)
    assert "غير موثّق" in ei.value.message


@pytest.mark.parametrize("policy,expect_ok", [("strict", False), ("warn", True)])
def test_M16_missed_dose_sequence_policy(tdb, policy, expect_ok):
    w = World(tdb, missed_dose_sequence_policy=policy, dose_window_minutes=600)
    p = w.patient()
    r = w.past_approved_rx(p, MA, hours_ago=0.5, interval_h=1)
    doses = w.doses(r)
    assert doses[1]["status"] == "due"     # النافذة الوهمية الواسعة تجعل الجرعة 2 مستحقة
    if expect_ok:
        res = w.give(doses[1]["id"], p)
        assert "جرعات سابقة غير موثقة: 1" in res["warnings"][0]
    else:
        with pytest.raises(ValidationFailed) as ei:
            w.give(doses[1]["id"], p)
        assert ei.value.code == "previous_dose_undocumented"


def test_M17_late_documentation_separate_times(tdb):
    w = World(tdb, dose_window_minutes=60, late_documentation_max_hours=24)
    p = w.patient()
    r = w.past_approved_rx(p, MA, hours_ago=3, interval_h=24)
    d = w.doses(r)[0]
    assert d["status"] == "missed"
    given_at = parse_utc(d["scheduled_at"]) + timedelta(minutes=10)
    with pytest.raises(ValidationFailed) as ei:
        w.give(d["id"], p, at=given_at)
    assert ei.value.code == "late_reason_required"
    res = w.give(d["id"], p, at=given_at, late_reason="تأخر التوثيق بسبب حالة طارئة (اختبار)")
    assert res["late_documentation"] is True
    d = w.doses(r)[0]
    assert d["administered_at_reported"] == fmt_utc(given_at)          # ما أدخله الممرض
    assert parse_utc(d["documented_at"]) > given_at + timedelta(hours=2)  # ما وضعه الخادم
    assert d["timing"] == "on_time" and d["late_documentation"] is True
    with pytest.raises(DBAPIError):
        with tdb.admin.engine.begin() as c:
            c.execute(text("UPDATE administrations SET documented_at = administered_at_reported"))


def test_M17b_late_limit(tdb):
    w = World(tdb, dose_window_minutes=60, late_documentation_max_hours=1)
    p = w.patient()
    r = w.past_approved_rx(p, MA, hours_ago=5, interval_h=24)
    d = w.doses(r)[0]
    with pytest.raises(ValidationFailed) as ei:
        w.give(d["id"], p, at=parse_utc(d["scheduled_at"]), late_reason="سبب")
    assert ei.value.code == "late_limit_exceeded"
    assert tdb.count("administrations") == 0


def test_M17c_documented_at_cannot_be_supplied_postgres(w):
    if w.tdb.kind != "postgresql":
        pytest.skip("في SQLite لا يمكن للمشغّل تعديل القيمة المُدرجة؛ الحماية هنا أن الكود لا يرسلها")
    p = w.patient()
    r = w.rx(p, MA)
    w.approve(r)
    d1 = w.doses(r)[0]["id"]
    with w.tdb.admin.engine.begin() as c:
        c.execute(text(
            "INSERT INTO administrations (scheduled_dose_id, nurse_id, outcome, not_given_reason_id,"
            " documented_at, verified_patient_mrn, verified_medication, verified_pharmacist_decision, warnings)"
            " VALUES (:d, (SELECT id FROM users WHERE username='nu1'), 'not_given', :r, '2000-01-01T00:00:00.000000Z',"
            " :m, true, true, '[]')"), {"d": d1, "r": w.ref["other"], "m": p["mrn"]})
    assert not w.doses(r)[0]["documented_at"].startswith("2000")


def test_M17d_app_code_never_sends_documented_at():
    src = open(AD.__file__, encoding="utf-8").read()
    insert = src[src.index("INSERT INTO administrations"):src.index("RETURNING id", src.index("INSERT INTO administrations"))]
    assert "documented_at" not in insert


# ------------------------------------------------------------ الإيقاف والإحالة

def test_M18_stop_prescriber_only_cancels_future_doses(tdb):
    w = World(tdb, dose_window_minutes=60, late_documentation_max_hours="none")
    p = w.patient()
    r = w.past_approved_rx(p, MA, hours_ago=2, interval_h=8)
    with pytest.raises(PermissionDenied) as ei:
        RX.stop_prescription(tdb.app, w.doc2, r, reason="ليس الواصف")
    assert ei.value.code == "not_prescriber"
    with pytest.raises(ValidationFailed):
        RX.stop_prescription(tdb.app, w.doc, r, reason="   ")
    RX.stop_prescription(tdb.app, w.doc, r, reason="إيقاف (اختبار)")
    doses = w.doses(r)
    assert doses[0]["status"] == "missed" and all(d["status"] == "cancelled" for d in doses[1:])
    assert all(x["prescription_id"] != r or x["dose_number"] == 1 for x in AD.dose_worklist(tdb.app, w.nu))
    sched = parse_utc(doses[0]["scheduled_at"])
    with pytest.raises(ValidationFailed):     # وقت إعطاء بعد الإيقاف
        w.give(doses[0]["id"], p, at=now_of(tdb), late_reason="سبب")
    res = w.give(doses[0]["id"], p, at=sched, late_reason="توثيق متأخر لجرعة قبل الإيقاف")
    assert res["late_documentation"] is True
    with pytest.raises(ValidationFailed) as ei:
        w.give(doses[1]["id"], p, at=sched)
    assert ei.value.code == "cancelled_by_stop"
    with pytest.raises(Conflict):
        RX.stop_prescription(tdb.app, w.doc, r, reason="مرة ثانية")


def test_M19_referral_closure_rules(w):
    p = w.patient()
    r = w.rx(p, MA)
    w.approve(r)
    d1 = w.doses(r)[0]["id"]
    ref_id = w.not_given(d1, p, create_referral=True)["referral_id"]
    with pytest.raises(PermissionDenied):
        RX.close_referral(w.tdb.app, w.doc2, ref_id, action="no_action", note="ليس الواصف")
    with pytest.raises(PermissionDenied):
        RX.close_referral(w.tdb.app, w.nu, ref_id, action="no_action", note="ممرض")
    with pytest.raises(ValidationFailed):
        RX.close_referral(w.tdb.app, w.doc, ref_id, action="no_action", note=" ")
    with pytest.raises(ValidationFailed):
        RX.close_referral(w.tdb.app, w.doc, ref_id, action="stopped")   # الوصفة لم تُوقف
    assert len(RX.list_referrals(w.tdb.app, w.doc)) == 1
    RX.close_referral(w.tdb.app, w.doc, ref_id, action="no_action", note="اطلعت؛ لا إجراء (اختبار)")
    assert RX.list_referrals(w.tdb.app, w.doc) == []
    assert w.doses(r)[0]["status"] == "not_given"     # الإغلاق لا يغيّر حالة الجرعة
    with pytest.raises(Conflict):
        RX.close_referral(w.tdb.app, w.doc, ref_id, action="no_action", note="ثانية")
    with pytest.raises(DBAPIError):  # لا إحالة لإعطاء ناجح (المشغّل يرفض)
        with w.tdb.admin.engine.begin() as c:
            adm = c.execute(text("INSERT INTO administrations (scheduled_dose_id, nurse_id, outcome, actual_dose,"
                                 " administered_at_reported, verified_patient_mrn, verified_medication,"
                                 " verified_pharmacist_decision, warnings) VALUES (:d, 1, 'given', '10', :t, :m,"
                                 " :v, :v, '[]') RETURNING id"),
                            {"d": w.doses(r)[1]["id"], "t": fmt_utc(now_of(w.tdb)), "m": p["mrn"], "v": True}).scalar_one()
            c.execute(text("INSERT INTO referrals (administration_id, created_by) VALUES (:a, 1)"), {"a": adm})


# ------------------------------------------------------------ القواعد والإعدادات

def test_M20_incomplete_rule_blocks_only_what_it_touches(tdb):
    tdb.add_fake_allergens()
    from load_test_fixtures import FIXTURES
    data = json.loads((FIXTURES / "test_ruleset.json").read_text("utf-8"))
    bad = next(r for r in data["rules"] if r["code"] == "T-R4")   # ب + د
    del bad["severity"]
    s = load_ruleset(tdb.admin, data, operator="pytest")
    assert s["incomplete"][0]["code"] == "T-R4" and "T-R4" not in s["loaded"]
    from hc.reference import set_policy
    set_policy(tdb.admin, operator="pytest", key="max_treatment_days", value="7", synthetic=True)
    w = World.__new__(World)
    w.tdb, w.ref = tdb, tdb.ref()
    w.reg, w.doc = tdb.session("reg1", "registration"), tdb.session("doc1", "doctor")
    p = w.patient()
    with pytest.raises(ConfigMissing) as ei:
        w.rx(p, MB)
    assert ei.value.code == "rule_incomplete"
    assert w.rx(p, MA)                     # دواء لا تمسه القاعدة الناقصة


def test_M20b_unknown_conditions_block_everything(tdb):
    tdb.add_fake_allergens()
    from load_test_fixtures import FIXTURES
    data = json.loads((FIXTURES / "test_ruleset.json").read_text("utf-8"))
    data["rules"][0]["conditions"] = [{"allergen": "غير معرّف", "medication": "غير معرّف"}]
    load_ruleset(tdb.admin, data, operator="pytest")
    from hc.reference import set_policy
    set_policy(tdb.admin, operator="pytest", key="max_treatment_days", value="7", synthetic=True)
    w = World.__new__(World)
    w.tdb, w.ref = tdb, tdb.ref()
    w.reg, w.doc = tdb.session("reg1", "registration"), tdb.session("doc1", "doctor")
    p = w.patient()
    for m in (MA, MD):
        with pytest.raises(ConfigMissing):
            w.rx(p, m)


def test_M21_synthetic_ruleset_refused_outside_test(tdb):
    from load_test_fixtures import FIXTURES
    data = json.loads((FIXTURES / "test_ruleset.json").read_text("utf-8"))
    dev_ctx = Ctx(engine=tdb.admin.engine, hmac_key=AUDIT_KEY, env="dev")
    with pytest.raises(RulesetError):
        load_ruleset(dev_ctx, data, operator="pytest")


def test_M22_missing_policies_stop_only_dependent_functions(tdb):
    tdb.add_fake_allergens()
    from load_test_fixtures import FIXTURES
    load_ruleset(tdb.admin, json.loads((FIXTURES / "test_ruleset.json").read_text("utf-8")), operator="pytest")
    reg, doc = tdb.session("reg1", "registration"), tdb.session("doc1", "doctor")
    p = P.create_patient(tdb.app, reg, full_name="م", age=30, allergy_status="none_known")  # التسجيل يعمل
    with pytest.raises(ConfigMissing) as ei:
        RX.create_prescription(tdb.app, doc, patient_id=p["id"], medication_id=tdb.ref()[MA], dose="1",
                               frequency_id=tdb.ref()["test-q8h"], start_at=now_of(tdb) + timedelta(hours=1),
                               duration_days=1)
    assert "max_treatment_days" in ei.value.details["missing_settings"]


# ------------------------------------------------------------ الحماية والتزامن والسجل

def test_M23_cycle_tables_immutable_and_transitions_enforced(w):
    p = w.patient(allergies=[A_ALLERGY])
    r = w.rx(p, MA)
    a = w.alerts(r)[0]
    RV.resolve_alert(w.tdb.app, w.ph, a["id"], evidence={q["id"]: (True if q["evidence"] == "confirm" else "نص")
                                                          for q in a["requirements"]})
    w.approve(r)
    w.give(w.doses(r)[0]["id"], p)
    attacks = ["UPDATE administrations SET outcome='not_given'", "DELETE FROM administrations",
               "UPDATE alerts SET severity='non_critical'", "DELETE FROM alert_resolutions",
               "UPDATE pharmacist_reviews SET decision='returned'", "UPDATE scheduled_doses SET planned_dose='99'",
               "UPDATE prescriptions SET dose='99'", "UPDATE prescriptions SET status='awaiting_pharmacist'",
               "DELETE FROM prescriptions", "UPDATE rule_versions SET severity='non_critical'"]
    for sql in attacks:
        with pytest.raises(DBAPIError):
            with w.tdb.admin.engine.begin() as c:
                c.execute(text(sql))
    r2 = w.rx(p, MD)
    RV.return_to_doctor(w.tdb.app, w.ph, r2, note="اختبار")
    with pytest.raises(DBAPIError):   # مُعادة ← معتمدة ممنوع
        with w.tdb.admin.engine.begin() as c:
            c.execute(text("UPDATE prescriptions SET status='approved' WHERE id=:x"), {"x": r2})


def test_M24_two_nurses_same_dose_one_wins(w):
    p = w.patient()
    r = w.rx(p, MA, freq="test-q6h", days=7)
    w.approve(r)
    outcomes = []
    d1 = w.doses(r)[0]["id"]
    barrier = threading.Barrier(2)

    def worker(nurse):
        barrier.wait()
        try:
            w.give(d1, p, nurse=nurse)
            outcomes.append("ok")
        except Conflict:
            outcomes.append("conflict")

    ts = [threading.Thread(target=worker, args=(n,)) for n in (w.nu, w.nu2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(outcomes) == ["conflict", "ok"]
    assert w.tdb.count("administrations") == 1


def test_M25_app_db_account_limits_postgres(w):
    if w.tdb.kind != "postgresql":
        pytest.skip("صلاحيات الحسابات خاصة بـ PostgreSQL")
    p = w.patient()
    r = w.rx(p, MA)
    for sql in ("UPDATE prescriptions SET dose='99'", "INSERT INTO rule_versions (ruleset_version_id, code, version,"
                " rule_type, severity, alert_text, resolution_policy, existing_rx_policy, source_note)"
                " VALUES (1,'X',9,'allergy','critical','x','conditional','warn_only','x')",
                "INSERT INTO policy_settings (key, value, operator, is_synthetic) VALUES ('max_treatment_days','99','x',true)"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with w.tdb.app.engine.begin() as c:
                c.execute(text(sql))
    assert RX.get_detail(w.tdb.app, w.doc, r)["dose"] == "10"


def test_M26_whole_cycle_audited_and_chain_valid(w):
    p = w.patient(allergies=[A_ALLERGY])
    r = w.rx(p, MA)
    a = w.alerts(r)[0]
    RV.resolve_alert(w.tdb.app, w.ph, a["id"], evidence={q["id"]: (True if q["evidence"] == "confirm" else "نص")
                                                          for q in a["requirements"]})
    w.approve(r)
    w.give(w.doses(r)[0]["id"], p)
    actions = [t["action"] for t in RX.rx_audit_trail(w.tdb.app, w.doc, r)]
    assert actions == ["rx.create", "alert.resolve", "rx.review", "dose.document"]
    assert verify_chain(w.tdb.admin.engine, AUDIT_KEY).ok


def test_M27_approval_refused_if_allergy_status_reset(w):
    p = w.patient()
    r = w.rx(p, MA)
    P.set_allergies(w.tdb.app, w.reg, p["id"], expected_version=1, allergy_status="not_recorded")
    with pytest.raises(ValidationFailed) as ei:
        w.approve(r)
    assert ei.value.code == "allergy_not_recorded"


def test_M28_removal_reason_mandatory_whitespace_rejected(w):
    p = w.patient(allergies=[A_ALLERGY])
    for reason in (None, "", "   ", "\t \n"):
        with pytest.raises(ValidationFailed) as ei:
            P.set_allergies(w.tdb.app, w.reg, p["id"], expected_version=1, allergy_status="none_known",
                            removal_reason=reason)
        assert ei.value.details["field"] == "removal_reason"
    assert P.get_patient(w.tdb.app, w.reg, p["id"])["allergen_ids"] == [w.ref[A_ALLERGY]]
    P.set_allergies(w.tdb.app, w.reg, p["id"], expected_version=1, allergy_status="none_known",
                    removal_reason="سبب حقيقي مكتوب")
