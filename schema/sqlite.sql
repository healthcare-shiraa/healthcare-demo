-- مخطط قاعدة البيانات (SQLite). الأوقات نص ISO بالتوقيت العالمي UTC، بست خانات للكسور
-- (الصيغة نفسها في PostgreSQL) حتى تبقى المقارنة النصية بين الأوقات صحيحة.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS meta_no_update BEFORE UPDATE ON meta
BEGIN SELECT RAISE(ABORT, 'meta is immutable'); END;
CREATE TRIGGER IF NOT EXISTS meta_no_delete BEFORE DELETE ON meta
BEGIN SELECT RAISE(ABORT, 'meta is immutable'); END;

CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO counters(name, value) VALUES ('patient_mrn', 0);

CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    username           TEXT NOT NULL UNIQUE,
    password_hash      TEXT NOT NULL,
    full_name          TEXT NOT NULL,
    role               TEXT NOT NULL CHECK (role IN ('registration','doctor','pharmacist','nurse')),
    is_active          INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    credential_version INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    deactivated_at     TEXT
);
CREATE TRIGGER IF NOT EXISTS users_no_delete BEFORE DELETE ON users
BEGIN SELECT RAISE(ABORT, 'users cannot be deleted; deactivate instead'); END;
CREATE TRIGGER IF NOT EXISTS users_role_immutable BEFORE UPDATE OF role ON users
WHEN NEW.role <> OLD.role
BEGIN SELECT RAISE(ABORT, 'role cannot be changed'); END;

CREATE TABLE IF NOT EXISTS patients (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    mrn            TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
    age            INTEGER NOT NULL CHECK (age >= 18),
    allergy_status TEXT NOT NULL CHECK (allergy_status IN ('not_recorded','none_known','has_allergies')),
    row_version    INTEGER NOT NULL DEFAULT 1,
    created_by     INTEGER NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    updated_by     INTEGER REFERENCES users(id),
    updated_at     TEXT
);
CREATE TRIGGER IF NOT EXISTS patients_no_delete BEFORE DELETE ON patients
BEGIN SELECT RAISE(ABORT, 'patients cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS patients_mrn_immutable BEFORE UPDATE OF mrn ON patients
WHEN NEW.mrn <> OLD.mrn
BEGIN SELECT RAISE(ABORT, 'mrn is immutable'); END;

CREATE TABLE IF NOT EXISTS allergens (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- تاريخ الحساسيات: لا يُحذف أي سطر. الإزالة من الحالة الحالية تُوثَّق بتعبئة حقول الإزالة مرة واحدة.
-- الحساسية «الحالية» = سطر removed_at فيه فارغ. إعادة إضافة حساسية أُزيلت تُنشئ سطرًا جديدًا.
CREATE TABLE IF NOT EXISTS patient_allergies (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL REFERENCES patients(id),
    allergen_id    INTEGER NOT NULL REFERENCES allergens(id),
    recorded_by    INTEGER NOT NULL REFERENCES users(id),
    recorded_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    removed_by     INTEGER REFERENCES users(id),
    removed_at     TEXT,
    removal_reason TEXT,
    CHECK ((removed_at IS NULL AND removed_by IS NULL AND removal_reason IS NULL)
        OR (removed_at IS NOT NULL AND removed_by IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS patient_allergies_one_current
    ON patient_allergies(patient_id, allergen_id) WHERE removed_at IS NULL;
CREATE TRIGGER IF NOT EXISTS patient_allergies_no_delete BEFORE DELETE ON patient_allergies
BEGIN SELECT RAISE(ABORT, 'allergy history cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS patient_allergies_remove_once BEFORE UPDATE ON patient_allergies
WHEN NOT (OLD.removed_at IS NULL AND NEW.removed_at IS NOT NULL AND NEW.removed_by IS NOT NULL
          AND NEW.id = OLD.id AND NEW.patient_id = OLD.patient_id AND NEW.allergen_id = OLD.allergen_id
          AND NEW.recorded_by = OLD.recorded_by AND NEW.recorded_at = OLD.recorded_at)
BEGIN SELECT RAISE(ABORT, 'allergy history: only a single removal is allowed'); END;

CREATE TABLE IF NOT EXISTS audit_log (
    seq             INTEGER PRIMARY KEY,
    occurred_at     TEXT NOT NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user','script','anonymous')),
    actor_user_id   INTEGER,
    actor_username  TEXT,
    actor_role      TEXT,
    operator_name   TEXT,
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       TEXT,
    outcome         TEXT NOT NULL CHECK (outcome IN ('success','denied','validation_error','conflict','busy','error')),
    details         TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    entry_hash      TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- >>> PHASE2 (مولّد آليًا من tools/gen_phase2_schema.py) >>>

-- دورة الدواء. كل الجداول للإضافة فقط، عدا حالة الوصفة (انتقالات محددة).

CREATE TABLE IF NOT EXISTS medications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    unit         TEXT NOT NULL,
    dose_min     TEXT NOT NULL,
    dose_max     TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')
);

CREATE TRIGGER IF NOT EXISTS medications_no_delete BEFORE DELETE ON medications
BEGIN SELECT RAISE(ABORT, 'medications is append-only'); END;

CREATE TRIGGER IF NOT EXISTS medications_no_update BEFORE UPDATE ON medications
BEGIN SELECT RAISE(ABORT, 'medications is append-only'); END;

CREATE TABLE IF NOT EXISTS frequencies (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT NOT NULL UNIQUE,
    label          TEXT NOT NULL,
    interval_hours INTEGER NOT NULL CHECK (interval_hours > 0),
    is_synthetic   INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS frequencies_no_delete BEFORE DELETE ON frequencies
BEGIN SELECT RAISE(ABORT, 'frequencies is append-only'); END;

CREATE TRIGGER IF NOT EXISTS frequencies_no_update BEFORE UPDATE ON frequencies
BEGIN SELECT RAISE(ABORT, 'frequencies is append-only'); END;

CREATE TABLE IF NOT EXISTS medication_frequencies (
    medication_id INTEGER NOT NULL REFERENCES medications(id),
    frequency_id  INTEGER NOT NULL REFERENCES frequencies(id),
    PRIMARY KEY (medication_id, frequency_id)
);

CREATE TRIGGER IF NOT EXISTS medication_frequencies_no_delete BEFORE DELETE ON medication_frequencies
BEGIN SELECT RAISE(ABORT, 'medication_frequencies is append-only'); END;

CREATE TRIGGER IF NOT EXISTS medication_frequencies_no_update BEFORE UPDATE ON medication_frequencies
BEGIN SELECT RAISE(ABORT, 'medication_frequencies is append-only'); END;

CREATE TABLE IF NOT EXISTS not_given_reasons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL UNIQUE,
    label         TEXT NOT NULL,
    requires_text INTEGER NOT NULL,
    is_synthetic  INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS not_given_reasons_no_delete BEFORE DELETE ON not_given_reasons
BEGIN SELECT RAISE(ABORT, 'not_given_reasons is append-only'); END;

CREATE TRIGGER IF NOT EXISTS not_given_reasons_no_update BEFORE UPDATE ON not_given_reasons
BEGIN SELECT RAISE(ABORT, 'not_given_reasons is append-only'); END;

CREATE TABLE IF NOT EXISTS policy_settings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT NOT NULL CHECK (key IN ('dose_window_minutes','late_documentation_max_hours',
                                              'missed_dose_sequence_policy','max_treatment_days')),
    value        TEXT NOT NULL,
    operator     TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL,
    set_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')
);

CREATE TRIGGER IF NOT EXISTS policy_settings_no_delete BEFORE DELETE ON policy_settings
BEGIN SELECT RAISE(ABORT, 'policy_settings is append-only'); END;

CREATE TRIGGER IF NOT EXISTS policy_settings_no_update BEFORE UPDATE ON policy_settings
BEGIN SELECT RAISE(ABORT, 'policy_settings is append-only'); END;

CREATE TABLE IF NOT EXISTS ruleset_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    label        TEXT NOT NULL,
    operator     TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('clinical','test_fixture','illustrative')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CHECK ((kind = 'clinical') = (is_synthetic = 0))
);

CREATE TRIGGER IF NOT EXISTS ruleset_versions_no_delete BEFORE DELETE ON ruleset_versions
BEGIN SELECT RAISE(ABORT, 'ruleset_versions is append-only'); END;

CREATE TRIGGER IF NOT EXISTS ruleset_versions_no_update BEFORE UPDATE ON ruleset_versions
BEGIN SELECT RAISE(ABORT, 'ruleset_versions is append-only'); END;

CREATE TABLE IF NOT EXISTS rule_versions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset_version_id INTEGER NOT NULL REFERENCES ruleset_versions(id),
    code               TEXT NOT NULL,
    version            INTEGER NOT NULL CHECK (version >= 1),
    rule_type          TEXT NOT NULL CHECK (rule_type IN ('allergy','interaction')),
    severity           TEXT NOT NULL CHECK (severity IN ('critical','non_critical')),
    alert_text         TEXT NOT NULL,
    resolution_policy  TEXT NOT NULL CHECK (resolution_policy IN ('return_only','conditional')),
    existing_rx_policy TEXT NOT NULL CHECK (existing_rx_policy IN ('block_until_resolved','warn_only')),
    lookback_hours     INTEGER CHECK (lookback_hours IS NULL OR lookback_hours >= 0),
    source_note        TEXT NOT NULL,
    UNIQUE (ruleset_version_id, code)
);

CREATE TRIGGER IF NOT EXISTS rule_versions_no_delete BEFORE DELETE ON rule_versions
BEGIN SELECT RAISE(ABORT, 'rule_versions is append-only'); END;

CREATE TRIGGER IF NOT EXISTS rule_versions_no_update BEFORE UPDATE ON rule_versions
BEGIN SELECT RAISE(ABORT, 'rule_versions is append-only'); END;

CREATE TABLE IF NOT EXISTS rule_conditions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version_id INTEGER NOT NULL REFERENCES rule_versions(id),
    allergen_id     INTEGER REFERENCES allergens(id),
    medication_a_id INTEGER NOT NULL REFERENCES medications(id),
    medication_b_id INTEGER REFERENCES medications(id),
    CHECK ((allergen_id IS NOT NULL AND medication_b_id IS NULL)
        OR (allergen_id IS NULL AND medication_b_id IS NOT NULL AND medication_b_id <> medication_a_id))
);

CREATE TRIGGER IF NOT EXISTS rule_conditions_no_delete BEFORE DELETE ON rule_conditions
BEGIN SELECT RAISE(ABORT, 'rule_conditions is append-only'); END;

CREATE TRIGGER IF NOT EXISTS rule_conditions_no_update BEFORE UPDATE ON rule_conditions
BEGIN SELECT RAISE(ABORT, 'rule_conditions is append-only'); END;

CREATE TABLE IF NOT EXISTS rule_resolution_requirements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version_id INTEGER NOT NULL REFERENCES rule_versions(id),
    seq             INTEGER NOT NULL,
    text            TEXT NOT NULL,
    evidence        TEXT NOT NULL CHECK (evidence IN ('confirm','text')),
    UNIQUE (rule_version_id, seq)
);

CREATE TRIGGER IF NOT EXISTS rule_resolution_requirements_no_delete BEFORE DELETE ON rule_resolution_requirements
BEGIN SELECT RAISE(ABORT, 'rule_resolution_requirements is append-only'); END;

CREATE TRIGGER IF NOT EXISTS rule_resolution_requirements_no_update BEFORE UPDATE ON rule_resolution_requirements
BEGIN SELECT RAISE(ABORT, 'rule_resolution_requirements is append-only'); END;

CREATE TABLE IF NOT EXISTS incomplete_rules (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset_version_id INTEGER NOT NULL REFERENCES ruleset_versions(id),
    code               TEXT NOT NULL,
    missing            TEXT NOT NULL,
    medication_ids     TEXT NOT NULL,
    conditions_known   INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS incomplete_rules_no_delete BEFORE DELETE ON incomplete_rules
BEGIN SELECT RAISE(ABORT, 'incomplete_rules is append-only'); END;

CREATE TRIGGER IF NOT EXISTS incomplete_rules_no_update BEFORE UPDATE ON incomplete_rules
BEGIN SELECT RAISE(ABORT, 'incomplete_rules is append-only'); END;

CREATE TABLE IF NOT EXISTS prescriptions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id         INTEGER NOT NULL REFERENCES patients(id),
    medication_id      INTEGER NOT NULL REFERENCES medications(id),
    dose               TEXT NOT NULL,
    frequency_id       INTEGER NOT NULL REFERENCES frequencies(id),
    start_at           TEXT NOT NULL,
    end_at             TEXT NOT NULL,
    prescriber_id      INTEGER NOT NULL REFERENCES users(id),
    ruleset_version_id INTEGER NOT NULL REFERENCES ruleset_versions(id),
    status             TEXT NOT NULL DEFAULT 'awaiting_pharmacist'
                       CHECK (status IN ('awaiting_pharmacist','approved','returned','stopped')),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CHECK (end_at > start_at)
);

CREATE TRIGGER IF NOT EXISTS prescriptions_no_delete BEFORE DELETE ON prescriptions
BEGIN SELECT RAISE(ABORT, 'prescriptions is append-only'); END;

CREATE TABLE IF NOT EXISTS prescription_stops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL UNIQUE REFERENCES prescriptions(id),
    stopped_by      INTEGER NOT NULL REFERENCES users(id),
    stopped_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    reason          TEXT NOT NULL CHECK (length(trim(reason)) > 0)
);

CREATE TRIGGER IF NOT EXISTS prescription_stops_no_delete BEFORE DELETE ON prescription_stops
BEGIN SELECT RAISE(ABORT, 'prescription_stops is append-only'); END;

CREATE TRIGGER IF NOT EXISTS prescription_stops_no_update BEFORE UPDATE ON prescription_stops
BEGIN SELECT RAISE(ABORT, 'prescription_stops is append-only'); END;

CREATE TABLE IF NOT EXISTS alerts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id         INTEGER NOT NULL REFERENCES prescriptions(id),
    rule_version_id         INTEGER NOT NULL REFERENCES rule_versions(id),
    severity                TEXT NOT NULL CHECK (severity IN ('critical','non_critical')),
    alert_text              TEXT NOT NULL,
    related_prescription_id INTEGER REFERENCES prescriptions(id),
    related_allergy_id      INTEGER REFERENCES patient_allergies(id),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CHECK ((related_prescription_id IS NULL) <> (related_allergy_id IS NULL))
);

CREATE TRIGGER IF NOT EXISTS alerts_no_delete BEFORE DELETE ON alerts
BEGIN SELECT RAISE(ABORT, 'alerts is append-only'); END;

CREATE TRIGGER IF NOT EXISTS alerts_no_update BEFORE UPDATE ON alerts
BEGIN SELECT RAISE(ABORT, 'alerts is append-only'); END;

CREATE TABLE IF NOT EXISTS alert_resolutions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id      INTEGER NOT NULL UNIQUE REFERENCES alerts(id),
    pharmacist_id INTEGER NOT NULL REFERENCES users(id),
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')
);

CREATE TRIGGER IF NOT EXISTS alert_resolutions_no_delete BEFORE DELETE ON alert_resolutions
BEGIN SELECT RAISE(ABORT, 'alert_resolutions is append-only'); END;

CREATE TRIGGER IF NOT EXISTS alert_resolutions_no_update BEFORE UPDATE ON alert_resolutions
BEGIN SELECT RAISE(ABORT, 'alert_resolutions is append-only'); END;

CREATE TABLE IF NOT EXISTS alert_resolution_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    resolution_id  INTEGER NOT NULL REFERENCES alert_resolutions(id),
    requirement_id INTEGER NOT NULL REFERENCES rule_resolution_requirements(id),
    confirmed      INTEGER,
    text_value     TEXT,
    UNIQUE (resolution_id, requirement_id)
);

CREATE TRIGGER IF NOT EXISTS alert_resolution_items_no_delete BEFORE DELETE ON alert_resolution_items
BEGIN SELECT RAISE(ABORT, 'alert_resolution_items is append-only'); END;

CREATE TRIGGER IF NOT EXISTS alert_resolution_items_no_update BEFORE UPDATE ON alert_resolution_items
BEGIN SELECT RAISE(ABORT, 'alert_resolution_items is append-only'); END;

CREATE TABLE IF NOT EXISTS alert_acknowledgments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id      INTEGER NOT NULL UNIQUE REFERENCES alerts(id),
    pharmacist_id INTEGER NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')
);

CREATE TRIGGER IF NOT EXISTS alert_acknowledgments_no_delete BEFORE DELETE ON alert_acknowledgments
BEGIN SELECT RAISE(ABORT, 'alert_acknowledgments is append-only'); END;

CREATE TRIGGER IF NOT EXISTS alert_acknowledgments_no_update BEFORE UPDATE ON alert_acknowledgments
BEGIN SELECT RAISE(ABORT, 'alert_acknowledgments is append-only'); END;

CREATE TABLE IF NOT EXISTS pharmacist_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL UNIQUE REFERENCES prescriptions(id),
    pharmacist_id   INTEGER NOT NULL REFERENCES users(id),
    decision        TEXT NOT NULL CHECK (decision IN ('approved','returned')),
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CHECK (decision = 'approved' OR length(trim(coalesce(note, ''))) > 0)
);

CREATE TRIGGER IF NOT EXISTS pharmacist_reviews_no_delete BEFORE DELETE ON pharmacist_reviews
BEGIN SELECT RAISE(ABORT, 'pharmacist_reviews is append-only'); END;

CREATE TRIGGER IF NOT EXISTS pharmacist_reviews_no_update BEFORE UPDATE ON pharmacist_reviews
BEGIN SELECT RAISE(ABORT, 'pharmacist_reviews is append-only'); END;

CREATE TABLE IF NOT EXISTS scheduled_doses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL REFERENCES prescriptions(id),
    dose_number     INTEGER NOT NULL CHECK (dose_number >= 1),
    scheduled_at    TEXT NOT NULL,
    planned_dose    TEXT NOT NULL,
    UNIQUE (prescription_id, dose_number)
);

CREATE TRIGGER IF NOT EXISTS scheduled_doses_no_delete BEFORE DELETE ON scheduled_doses
BEGIN SELECT RAISE(ABORT, 'scheduled_doses is append-only'); END;

CREATE TRIGGER IF NOT EXISTS scheduled_doses_no_update BEFORE UPDATE ON scheduled_doses
BEGIN SELECT RAISE(ABORT, 'scheduled_doses is append-only'); END;

CREATE TABLE IF NOT EXISTS administrations (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_dose_id            INTEGER NOT NULL UNIQUE REFERENCES scheduled_doses(id),
    nurse_id                     INTEGER NOT NULL REFERENCES users(id),
    outcome                      TEXT NOT NULL CHECK (outcome IN ('given','not_given')),
    actual_dose                  TEXT,
    administered_at_reported     TEXT,
    documented_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    not_given_reason_id          INTEGER REFERENCES not_given_reasons(id),
    reason_text                  TEXT,
    late_reason                  TEXT,
    verified_patient_mrn         TEXT NOT NULL,
    verified_medication          INTEGER NOT NULL CHECK (verified_medication = 1),
    verified_pharmacist_decision INTEGER NOT NULL CHECK (verified_pharmacist_decision = 1),
    warnings                     TEXT NOT NULL,
    CHECK ((outcome = 'given' AND actual_dose IS NOT NULL AND administered_at_reported IS NOT NULL
            AND not_given_reason_id IS NULL)
        OR (outcome = 'not_given' AND not_given_reason_id IS NOT NULL AND actual_dose IS NULL
            AND administered_at_reported IS NULL))
);

CREATE TRIGGER IF NOT EXISTS administrations_no_delete BEFORE DELETE ON administrations
BEGIN SELECT RAISE(ABORT, 'administrations is append-only'); END;

CREATE TRIGGER IF NOT EXISTS administrations_no_update BEFORE UPDATE ON administrations
BEGIN SELECT RAISE(ABORT, 'administrations is append-only'); END;

CREATE TABLE IF NOT EXISTS referrals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    administration_id INTEGER NOT NULL UNIQUE REFERENCES administrations(id),
    created_by        INTEGER NOT NULL REFERENCES users(id),
    note              TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z')
);

CREATE TRIGGER IF NOT EXISTS referrals_no_delete BEFORE DELETE ON referrals
BEGIN SELECT RAISE(ABORT, 'referrals is append-only'); END;

CREATE TRIGGER IF NOT EXISTS referrals_no_update BEFORE UPDATE ON referrals
BEGIN SELECT RAISE(ABORT, 'referrals is append-only'); END;

CREATE TABLE IF NOT EXISTS referral_closures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    referral_id         INTEGER NOT NULL UNIQUE REFERENCES referrals(id),
    doctor_id           INTEGER NOT NULL REFERENCES users(id),
    action              TEXT NOT NULL CHECK (action IN ('stopped','new_prescription','no_action')),
    new_prescription_id INTEGER REFERENCES prescriptions(id),
    note                TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now') || '000Z'),
    CHECK (action <> 'new_prescription' OR new_prescription_id IS NOT NULL),
    CHECK (action <> 'no_action' OR length(trim(coalesce(note, ''))) > 0)
);

CREATE TRIGGER IF NOT EXISTS referral_closures_no_delete BEFORE DELETE ON referral_closures
BEGIN SELECT RAISE(ABORT, 'referral_closures is append-only'); END;

CREATE TRIGGER IF NOT EXISTS referral_closures_no_update BEFORE UPDATE ON referral_closures
BEGIN SELECT RAISE(ABORT, 'referral_closures is append-only'); END;

CREATE TRIGGER IF NOT EXISTS prescriptions_transition BEFORE UPDATE ON prescriptions
WHEN NOT (NEW.id = OLD.id AND NEW.patient_id = OLD.patient_id AND NEW.medication_id = OLD.medication_id
          AND NEW.dose = OLD.dose AND NEW.frequency_id = OLD.frequency_id AND NEW.start_at = OLD.start_at
          AND NEW.end_at = OLD.end_at AND NEW.prescriber_id = OLD.prescriber_id
          AND NEW.ruleset_version_id = OLD.ruleset_version_id AND NEW.created_at = OLD.created_at
          AND ((OLD.status = 'awaiting_pharmacist' AND NEW.status IN ('approved','returned','stopped'))
               OR (OLD.status = 'approved' AND NEW.status = 'stopped')))
BEGIN SELECT RAISE(ABORT, 'prescription: transition not allowed'); END;

CREATE TRIGGER IF NOT EXISTS referrals_only_not_given BEFORE INSERT ON referrals
WHEN (SELECT outcome FROM administrations WHERE id = NEW.administration_id) IS NOT 'not_given'
BEGIN SELECT RAISE(ABORT, 'referral requires a not_given administration'); END;

-- <<< PHASE2 <<<
