"""يولّد قسم دورة الدواء في ملفي المخطط (SQLite و PostgreSQL) من تعريف واحد."""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent / "schema"
NOW_SQLITE = "(strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')"
NOW_PG = "hc_now_text()"

# (اسم الجدول, تعريف الأعمدة بصيغة محايدة). {PK} {ID} {NOW} {BOOL} تُستبدل لكل محرك.
TABLES = [
("medications", """
    id           {PK},
    name         TEXT NOT NULL UNIQUE,
    unit         TEXT NOT NULL,
    dose_min     TEXT NOT NULL,
    dose_max     TEXT NOT NULL,
    is_synthetic {BOOL} NOT NULL,
    created_at   TEXT NOT NULL DEFAULT {NOW}"""),
("frequencies", """
    id             {PK},
    code           TEXT NOT NULL UNIQUE,
    label          TEXT NOT NULL,
    interval_hours INTEGER NOT NULL CHECK (interval_hours > 0),
    is_synthetic   {BOOL} NOT NULL"""),
("medication_frequencies", """
    medication_id {ID} NOT NULL REFERENCES medications(id),
    frequency_id  {ID} NOT NULL REFERENCES frequencies(id),
    PRIMARY KEY (medication_id, frequency_id)"""),
("not_given_reasons", """
    id            {PK},
    code          TEXT NOT NULL UNIQUE,
    label         TEXT NOT NULL,
    requires_text {BOOL} NOT NULL,
    is_synthetic  {BOOL} NOT NULL"""),
("policy_settings", """
    id           {PK},
    key          TEXT NOT NULL CHECK (key IN ('dose_window_minutes','late_documentation_max_hours',
                                              'missed_dose_sequence_policy','max_treatment_days')),
    value        TEXT NOT NULL,
    operator     TEXT NOT NULL,
    is_synthetic {BOOL} NOT NULL,
    set_at       TEXT NOT NULL DEFAULT {NOW}"""),
("ruleset_versions", """
    id           {PK},
    label        TEXT NOT NULL,
    operator     TEXT NOT NULL,
    is_synthetic {BOOL} NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('clinical','test_fixture','illustrative')),
    created_at   TEXT NOT NULL DEFAULT {NOW},
    CHECK ((kind = 'clinical') = (is_synthetic = {FALSE}))"""),
("rule_versions", """
    id                 {PK},
    ruleset_version_id {ID} NOT NULL REFERENCES ruleset_versions(id),
    code               TEXT NOT NULL,
    version            INTEGER NOT NULL CHECK (version >= 1),
    rule_type          TEXT NOT NULL CHECK (rule_type IN ('allergy','interaction')),
    severity           TEXT NOT NULL CHECK (severity IN ('critical','non_critical')),
    alert_text         TEXT NOT NULL,
    resolution_policy  TEXT NOT NULL CHECK (resolution_policy IN ('return_only','conditional')),
    existing_rx_policy TEXT NOT NULL CHECK (existing_rx_policy IN ('block_until_resolved','warn_only')),
    lookback_hours     INTEGER CHECK (lookback_hours IS NULL OR lookback_hours >= 0),
    source_note        TEXT NOT NULL,
    UNIQUE (ruleset_version_id, code)"""),
("rule_conditions", """
    id              {PK},
    rule_version_id {ID} NOT NULL REFERENCES rule_versions(id),
    allergen_id     {ID} REFERENCES allergens(id),
    medication_a_id {ID} NOT NULL REFERENCES medications(id),
    medication_b_id {ID} REFERENCES medications(id),
    CHECK ((allergen_id IS NOT NULL AND medication_b_id IS NULL)
        OR (allergen_id IS NULL AND medication_b_id IS NOT NULL AND medication_b_id <> medication_a_id))"""),
("rule_resolution_requirements", """
    id              {PK},
    rule_version_id {ID} NOT NULL REFERENCES rule_versions(id),
    seq             INTEGER NOT NULL,
    text            TEXT NOT NULL,
    evidence        TEXT NOT NULL CHECK (evidence IN ('confirm','text')),
    UNIQUE (rule_version_id, seq)"""),
("incomplete_rules", """
    id                 {PK},
    ruleset_version_id {ID} NOT NULL REFERENCES ruleset_versions(id),
    code               TEXT NOT NULL,
    missing            TEXT NOT NULL,
    medication_ids     TEXT NOT NULL,
    conditions_known   {BOOL} NOT NULL"""),
("prescriptions", """
    id                 {PK},
    patient_id         {ID} NOT NULL REFERENCES patients(id),
    medication_id      {ID} NOT NULL REFERENCES medications(id),
    dose               TEXT NOT NULL,
    frequency_id       {ID} NOT NULL REFERENCES frequencies(id),
    start_at           TEXT NOT NULL,
    end_at             TEXT NOT NULL,
    prescriber_id      {ID} NOT NULL REFERENCES users(id),
    ruleset_version_id {ID} NOT NULL REFERENCES ruleset_versions(id),
    status             TEXT NOT NULL DEFAULT 'awaiting_pharmacist'
                       CHECK (status IN ('awaiting_pharmacist','approved','returned','stopped')),
    created_at         TEXT NOT NULL DEFAULT {NOW},
    CHECK (end_at > start_at)"""),
("prescription_stops", """
    id              {PK},
    prescription_id {ID} NOT NULL UNIQUE REFERENCES prescriptions(id),
    stopped_by      {ID} NOT NULL REFERENCES users(id),
    stopped_at      TEXT NOT NULL DEFAULT {NOW},
    reason          TEXT NOT NULL CHECK (length(trim(reason)) > 0)"""),
("alerts", """
    id                      {PK},
    prescription_id         {ID} NOT NULL REFERENCES prescriptions(id),
    rule_version_id         {ID} NOT NULL REFERENCES rule_versions(id),
    severity                TEXT NOT NULL CHECK (severity IN ('critical','non_critical')),
    alert_text              TEXT NOT NULL,
    related_prescription_id {ID} REFERENCES prescriptions(id),
    related_allergy_id      {ID} REFERENCES patient_allergies(id),
    created_at              TEXT NOT NULL DEFAULT {NOW},
    CHECK ((related_prescription_id IS NULL) <> (related_allergy_id IS NULL))"""),
("alert_resolutions", """
    id            {PK},
    alert_id      {ID} NOT NULL UNIQUE REFERENCES alerts(id),
    pharmacist_id {ID} NOT NULL REFERENCES users(id),
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT {NOW}"""),
("alert_resolution_items", """
    id             {PK},
    resolution_id  {ID} NOT NULL REFERENCES alert_resolutions(id),
    requirement_id {ID} NOT NULL REFERENCES rule_resolution_requirements(id),
    confirmed      {BOOL},
    text_value     TEXT,
    UNIQUE (resolution_id, requirement_id)"""),
("alert_acknowledgments", """
    id            {PK},
    alert_id      {ID} NOT NULL UNIQUE REFERENCES alerts(id),
    pharmacist_id {ID} NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT {NOW}"""),
("pharmacist_reviews", """
    id              {PK},
    prescription_id {ID} NOT NULL UNIQUE REFERENCES prescriptions(id),
    pharmacist_id   {ID} NOT NULL REFERENCES users(id),
    decision        TEXT NOT NULL CHECK (decision IN ('approved','returned')),
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT {NOW},
    CHECK (decision = 'approved' OR length(trim(coalesce(note, ''))) > 0)"""),
("scheduled_doses", """
    id              {PK},
    prescription_id {ID} NOT NULL REFERENCES prescriptions(id),
    dose_number     INTEGER NOT NULL CHECK (dose_number >= 1),
    scheduled_at    TEXT NOT NULL,
    planned_dose    TEXT NOT NULL,
    UNIQUE (prescription_id, dose_number)"""),
("administrations", """
    id                           {PK},
    scheduled_dose_id            {ID} NOT NULL UNIQUE REFERENCES scheduled_doses(id),
    nurse_id                     {ID} NOT NULL REFERENCES users(id),
    outcome                      TEXT NOT NULL CHECK (outcome IN ('given','not_given')),
    actual_dose                  TEXT,
    administered_at_reported     TEXT,
    documented_at                TEXT NOT NULL DEFAULT {NOW},
    not_given_reason_id          {ID} REFERENCES not_given_reasons(id),
    reason_text                  TEXT,
    late_reason                  TEXT,
    verified_patient_mrn         TEXT NOT NULL,
    verified_medication          {BOOL} NOT NULL CHECK (verified_medication = {TRUE}),
    verified_pharmacist_decision {BOOL} NOT NULL CHECK (verified_pharmacist_decision = {TRUE}),
    warnings                     TEXT NOT NULL,
    CHECK ((outcome = 'given' AND actual_dose IS NOT NULL AND administered_at_reported IS NOT NULL
            AND not_given_reason_id IS NULL)
        OR (outcome = 'not_given' AND not_given_reason_id IS NOT NULL AND actual_dose IS NULL
            AND administered_at_reported IS NULL))"""),
("referrals", """
    id                {PK},
    administration_id {ID} NOT NULL UNIQUE REFERENCES administrations(id),
    created_by        {ID} NOT NULL REFERENCES users(id),
    note              TEXT,
    created_at        TEXT NOT NULL DEFAULT {NOW}"""),
("referral_closures", """
    id                  {PK},
    referral_id         {ID} NOT NULL UNIQUE REFERENCES referrals(id),
    doctor_id           {ID} NOT NULL REFERENCES users(id),
    action              TEXT NOT NULL CHECK (action IN ('stopped','new_prescription','no_action')),
    new_prescription_id {ID} REFERENCES prescriptions(id),
    note                TEXT,
    created_at          TEXT NOT NULL DEFAULT {NOW},
    CHECK (action <> 'new_prescription' OR new_prescription_id IS NOT NULL),
    CHECK (action <> 'no_action' OR length(trim(coalesce(note, ''))) > 0)"""),
]
MUTABLE = {"prescriptions"}  # الوحيد الذي يتغير فيه حقل الحالة بانتقالات محددة

MARK_BEGIN = "-- >>> PHASE2 (مولّد آليًا من tools/gen_phase2_schema.py) >>>"
MARK_END = "-- <<< PHASE2 <<<"


def sqlite_sql():
    out = [MARK_BEGIN, "-- دورة الدواء. كل الجداول للإضافة فقط، عدا حالة الوصفة (انتقالات محددة)."]
    for name, cols in TABLES:
        c = (cols.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{ID}", "INTEGER")
                 .replace("{NOW}", NOW_SQLITE).replace("{BOOL}", "INTEGER").replace("{TRUE}", "1").replace("{FALSE}", "0"))
        out.append(f"CREATE TABLE IF NOT EXISTS {name} ({c}\n);")
        out.append(f"CREATE TRIGGER IF NOT EXISTS {name}_no_delete BEFORE DELETE ON {name}\n"
                   f"BEGIN SELECT RAISE(ABORT, '{name} is append-only'); END;")
        if name not in MUTABLE:
            out.append(f"CREATE TRIGGER IF NOT EXISTS {name}_no_update BEFORE UPDATE ON {name}\n"
                       f"BEGIN SELECT RAISE(ABORT, '{name} is append-only'); END;")
    out.append("""CREATE TRIGGER IF NOT EXISTS prescriptions_transition BEFORE UPDATE ON prescriptions
WHEN NOT (NEW.id = OLD.id AND NEW.patient_id = OLD.patient_id AND NEW.medication_id = OLD.medication_id
          AND NEW.dose = OLD.dose AND NEW.frequency_id = OLD.frequency_id AND NEW.start_at = OLD.start_at
          AND NEW.end_at = OLD.end_at AND NEW.prescriber_id = OLD.prescriber_id
          AND NEW.ruleset_version_id = OLD.ruleset_version_id AND NEW.created_at = OLD.created_at
          AND ((OLD.status = 'awaiting_pharmacist' AND NEW.status IN ('approved','returned','stopped'))
               OR (OLD.status = 'approved' AND NEW.status = 'stopped')))
BEGIN SELECT RAISE(ABORT, 'prescription: transition not allowed'); END;""")
    out.append("""CREATE TRIGGER IF NOT EXISTS referrals_only_not_given BEFORE INSERT ON referrals
WHEN (SELECT outcome FROM administrations WHERE id = NEW.administration_id) IS NOT 'not_given'
BEGIN SELECT RAISE(ABORT, 'referral requires a not_given administration'); END;""")
    out.append(MARK_END)
    return "\n\n".join(out) + "\n"


def pg_sql():
    out = [MARK_BEGIN, "-- دورة الدواء. كل الجداول للإضافة فقط، عدا حالة الوصفة (انتقالات محددة)."]
    for name, cols in TABLES:
        c = (cols.replace("{PK}", "bigserial PRIMARY KEY").replace("{ID}", "bigint")
                 .replace("{NOW}", NOW_PG).replace("{BOOL}", "boolean").replace("{TRUE}", "true").replace("{FALSE}", "false")
                 .replace("TEXT", "text").replace("INTEGER", "integer"))
        out.append(f"CREATE TABLE IF NOT EXISTS {name} ({c}\n);")
        ops = "DELETE" if name in MUTABLE else "UPDATE OR DELETE"
        out.append(f"CREATE OR REPLACE TRIGGER {name}_append_only BEFORE {ops} ON {name}\n"
                   f"FOR EACH ROW EXECUTE FUNCTION hc_reject_change('{name} is append-only');")
        out.append(f"CREATE OR REPLACE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name}\n"
                   f"FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('{name} is append-only');")
    out.append("""CREATE OR REPLACE FUNCTION hc_rx_transition() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF NOT (NEW.id = OLD.id AND NEW.patient_id = OLD.patient_id AND NEW.medication_id = OLD.medication_id
          AND NEW.dose = OLD.dose AND NEW.frequency_id = OLD.frequency_id AND NEW.start_at = OLD.start_at
          AND NEW.end_at = OLD.end_at AND NEW.prescriber_id = OLD.prescriber_id
          AND NEW.ruleset_version_id = OLD.ruleset_version_id AND NEW.created_at = OLD.created_at
          AND ((OLD.status = 'awaiting_pharmacist' AND NEW.status IN ('approved','returned','stopped'))
               OR (OLD.status = 'approved' AND NEW.status = 'stopped'))) THEN
    RAISE EXCEPTION 'prescription: transition not allowed';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER prescriptions_transition BEFORE UPDATE ON prescriptions
FOR EACH ROW EXECUTE FUNCTION hc_rx_transition();""")
    out.append("""-- وقت التوثيق يضعه الخادم دائمًا، ويتجاهل أي قيمة يرسلها التطبيق
CREATE OR REPLACE FUNCTION hc_admin_documented_at() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN NEW.documented_at := hc_now_text(); RETURN NEW; END $$;
CREATE OR REPLACE TRIGGER administrations_documented_at BEFORE INSERT ON administrations
FOR EACH ROW EXECUTE FUNCTION hc_admin_documented_at();
CREATE OR REPLACE FUNCTION hc_referral_only_not_given() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF (SELECT outcome FROM administrations WHERE id = NEW.administration_id) IS DISTINCT FROM 'not_given' THEN
    RAISE EXCEPTION 'referral requires a not_given administration';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER referrals_only_not_given BEFORE INSERT ON referrals
FOR EACH ROW EXECUTE FUNCTION hc_referral_only_not_given();""")
    out.append(MARK_END)
    return "\n\n".join(out) + "\n"


for fname, gen in (("sqlite.sql", sqlite_sql), ("postgres.sql", pg_sql)):
    p = ROOT / fname
    s = p.read_text("utf-8")
    s = re.sub(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n", "", s, flags=re.S)
    p.write_text(s.rstrip("\n") + "\n\n" + gen(), encoding="utf-8")
print("ok")
