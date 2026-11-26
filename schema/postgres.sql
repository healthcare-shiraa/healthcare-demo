-- مخطط المرحلة الأولى (PostgreSQL). يُنفَّذ بحساب المالك (admin) لا بحساب التطبيق.
-- الأوقات نص ISO بالتوقيت العالمي UTC لتبقى البصمات ثابتة بين المحركين.

CREATE OR REPLACE FUNCTION hc_now_text() RETURNS text LANGUAGE sql AS
$$ SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') $$;

CREATE OR REPLACE FUNCTION hc_reject_change() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION '% on % is not allowed (%)', TG_OP, TG_TABLE_NAME, TG_ARGV[0]; END $$;

CREATE TABLE IF NOT EXISTS meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);
CREATE OR REPLACE TRIGGER meta_immutable BEFORE UPDATE OR DELETE ON meta
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('meta is immutable');

CREATE TABLE IF NOT EXISTS counters (
    name  text PRIMARY KEY,
    value bigint NOT NULL
);
INSERT INTO counters(name, value) VALUES ('patient_mrn', 0) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS users (
    id                 bigserial PRIMARY KEY,
    username           text NOT NULL UNIQUE,
    password_hash      text NOT NULL,
    full_name          text NOT NULL,
    role               text NOT NULL CHECK (role IN ('registration','doctor','pharmacist','nurse')),
    is_active          boolean NOT NULL DEFAULT true,
    credential_version integer NOT NULL DEFAULT 1,
    created_at         text NOT NULL DEFAULT hc_now_text(),
    deactivated_at     text
);
CREATE OR REPLACE TRIGGER users_no_delete BEFORE DELETE ON users
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('deactivate instead');
CREATE OR REPLACE FUNCTION hc_users_role_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN IF NEW.role <> OLD.role THEN RAISE EXCEPTION 'role cannot be changed'; END IF; RETURN NEW; END $$;
CREATE OR REPLACE TRIGGER users_role_immutable BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION hc_users_role_immutable();

CREATE TABLE IF NOT EXISTS patients (
    id             bigserial PRIMARY KEY,
    mrn            text NOT NULL UNIQUE,
    full_name      text NOT NULL CHECK (length(btrim(full_name)) > 0),
    age            integer NOT NULL CHECK (age >= 18),
    allergy_status text NOT NULL CHECK (allergy_status IN ('not_recorded','none_known','has_allergies')),
    row_version    integer NOT NULL DEFAULT 1,
    created_by     bigint NOT NULL REFERENCES users(id),
    created_at     text NOT NULL DEFAULT hc_now_text(),
    updated_by     bigint REFERENCES users(id),
    updated_at     text
);
CREATE OR REPLACE TRIGGER patients_no_delete BEFORE DELETE ON patients
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('patients cannot be deleted');
CREATE OR REPLACE FUNCTION hc_patients_mrn_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN IF NEW.mrn <> OLD.mrn THEN RAISE EXCEPTION 'mrn is immutable'; END IF; RETURN NEW; END $$;
CREATE OR REPLACE TRIGGER patients_mrn_immutable BEFORE UPDATE ON patients
FOR EACH ROW EXECUTE FUNCTION hc_patients_mrn_immutable();

CREATE TABLE IF NOT EXISTS allergens (
    id   bigserial PRIMARY KEY,
    name text NOT NULL UNIQUE
);

-- تاريخ الحساسيات: لا يُحذف أي سطر. الإزالة من الحالة الحالية تُوثَّق بتعبئة حقول الإزالة مرة واحدة.
CREATE TABLE IF NOT EXISTS patient_allergies (
    id             bigserial PRIMARY KEY,
    patient_id     bigint NOT NULL REFERENCES patients(id),
    allergen_id    bigint NOT NULL REFERENCES allergens(id),
    recorded_by    bigint NOT NULL REFERENCES users(id),
    recorded_at    text NOT NULL DEFAULT hc_now_text(),
    removed_by     bigint REFERENCES users(id),
    removed_at     text,
    removal_reason text,
    CHECK ((removed_at IS NULL AND removed_by IS NULL AND removal_reason IS NULL)
        OR (removed_at IS NOT NULL AND removed_by IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS patient_allergies_one_current
    ON patient_allergies(patient_id, allergen_id) WHERE removed_at IS NULL;
CREATE OR REPLACE TRIGGER patient_allergies_no_delete BEFORE DELETE ON patient_allergies
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('allergy history cannot be deleted');
CREATE OR REPLACE TRIGGER patient_allergies_no_truncate BEFORE TRUNCATE ON patient_allergies
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('allergy history cannot be deleted');
CREATE OR REPLACE FUNCTION hc_allergy_remove_once() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF NOT (OLD.removed_at IS NULL AND NEW.removed_at IS NOT NULL AND NEW.removed_by IS NOT NULL
          AND NEW.id = OLD.id AND NEW.patient_id = OLD.patient_id AND NEW.allergen_id = OLD.allergen_id
          AND NEW.recorded_by = OLD.recorded_by AND NEW.recorded_at = OLD.recorded_at) THEN
    RAISE EXCEPTION 'allergy history: only a single removal is allowed';
  END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER patient_allergies_remove_once BEFORE UPDATE ON patient_allergies
FOR EACH ROW EXECUTE FUNCTION hc_allergy_remove_once();

CREATE TABLE IF NOT EXISTS audit_log (
    seq             bigint PRIMARY KEY,
    occurred_at     text NOT NULL,
    actor_type      text NOT NULL CHECK (actor_type IN ('user','script','anonymous')),
    actor_user_id   bigint,
    actor_username  text,
    actor_role      text,
    operator_name   text,
    action          text NOT NULL,
    entity_type     text,
    entity_id       text,
    outcome         text NOT NULL CHECK (outcome IN ('success','denied','validation_error','conflict','busy','error')),
    details         text NOT NULL,
    prev_hash       text NOT NULL,
    entry_hash      text NOT NULL
);
CREATE OR REPLACE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('audit_log is append-only');
-- TRUNCATE لا يُطلق مشغّلات الأسطر؛ نمنعه بمشغّل على مستوى الجملة
CREATE OR REPLACE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_log
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('audit_log is append-only');

-- >>> PHASE2 (مولّد آليًا من tools/gen_phase2_schema.py) >>>

-- دورة الدواء. كل الجداول للإضافة فقط، عدا حالة الوصفة (انتقالات محددة).

CREATE TABLE IF NOT EXISTS medications (
    id           bigserial PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    unit         text NOT NULL,
    dose_min     text NOT NULL,
    dose_max     text NOT NULL,
    is_synthetic boolean NOT NULL,
    created_at   text NOT NULL DEFAULT hc_now_text()
);

CREATE OR REPLACE TRIGGER medications_append_only BEFORE UPDATE OR DELETE ON medications
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('medications is append-only');

CREATE OR REPLACE TRIGGER medications_no_truncate BEFORE TRUNCATE ON medications
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('medications is append-only');

CREATE TABLE IF NOT EXISTS frequencies (
    id             bigserial PRIMARY KEY,
    code           text NOT NULL UNIQUE,
    label          text NOT NULL,
    interval_hours integer NOT NULL CHECK (interval_hours > 0),
    is_synthetic   boolean NOT NULL
);

CREATE OR REPLACE TRIGGER frequencies_append_only BEFORE UPDATE OR DELETE ON frequencies
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('frequencies is append-only');

CREATE OR REPLACE TRIGGER frequencies_no_truncate BEFORE TRUNCATE ON frequencies
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('frequencies is append-only');

CREATE TABLE IF NOT EXISTS medication_frequencies (
    medication_id bigint NOT NULL REFERENCES medications(id),
    frequency_id  bigint NOT NULL REFERENCES frequencies(id),
    PRIMARY KEY (medication_id, frequency_id)
);

CREATE OR REPLACE TRIGGER medication_frequencies_append_only BEFORE UPDATE OR DELETE ON medication_frequencies
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('medication_frequencies is append-only');

CREATE OR REPLACE TRIGGER medication_frequencies_no_truncate BEFORE TRUNCATE ON medication_frequencies
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('medication_frequencies is append-only');

CREATE TABLE IF NOT EXISTS not_given_reasons (
    id            bigserial PRIMARY KEY,
    code          text NOT NULL UNIQUE,
    label         text NOT NULL,
    requires_text boolean NOT NULL,
    is_synthetic  boolean NOT NULL
);

CREATE OR REPLACE TRIGGER not_given_reasons_append_only BEFORE UPDATE OR DELETE ON not_given_reasons
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('not_given_reasons is append-only');

CREATE OR REPLACE TRIGGER not_given_reasons_no_truncate BEFORE TRUNCATE ON not_given_reasons
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('not_given_reasons is append-only');

CREATE TABLE IF NOT EXISTS policy_settings (
    id           bigserial PRIMARY KEY,
    key          text NOT NULL CHECK (key IN ('dose_window_minutes','late_documentation_max_hours',
                                              'missed_dose_sequence_policy','max_treatment_days')),
    value        text NOT NULL,
    operator     text NOT NULL,
    is_synthetic boolean NOT NULL,
    set_at       text NOT NULL DEFAULT hc_now_text()
);

CREATE OR REPLACE TRIGGER policy_settings_append_only BEFORE UPDATE OR DELETE ON policy_settings
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('policy_settings is append-only');

CREATE OR REPLACE TRIGGER policy_settings_no_truncate BEFORE TRUNCATE ON policy_settings
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('policy_settings is append-only');

CREATE TABLE IF NOT EXISTS ruleset_versions (
    id           bigserial PRIMARY KEY,
    label        text NOT NULL,
    operator     text NOT NULL,
    is_synthetic boolean NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('clinical','test_fixture','illustrative')),
    created_at   text NOT NULL DEFAULT hc_now_text(),
    CHECK ((kind = 'clinical') = (is_synthetic = false))
);

CREATE OR REPLACE TRIGGER ruleset_versions_append_only BEFORE UPDATE OR DELETE ON ruleset_versions
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('ruleset_versions is append-only');

CREATE OR REPLACE TRIGGER ruleset_versions_no_truncate BEFORE TRUNCATE ON ruleset_versions
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('ruleset_versions is append-only');

CREATE TABLE IF NOT EXISTS rule_versions (
    id                 bigserial PRIMARY KEY,
    ruleset_version_id bigint NOT NULL REFERENCES ruleset_versions(id),
    code               text NOT NULL,
    version            integer NOT NULL CHECK (version >= 1),
    rule_type          text NOT NULL CHECK (rule_type IN ('allergy','interaction')),
    severity           text NOT NULL CHECK (severity IN ('critical','non_critical')),
    alert_text         text NOT NULL,
    resolution_policy  text NOT NULL CHECK (resolution_policy IN ('return_only','conditional')),
    existing_rx_policy text NOT NULL CHECK (existing_rx_policy IN ('block_until_resolved','warn_only')),
    lookback_hours     integer CHECK (lookback_hours IS NULL OR lookback_hours >= 0),
    source_note        text NOT NULL,
    UNIQUE (ruleset_version_id, code)
);

CREATE OR REPLACE TRIGGER rule_versions_append_only BEFORE UPDATE OR DELETE ON rule_versions
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('rule_versions is append-only');

CREATE OR REPLACE TRIGGER rule_versions_no_truncate BEFORE TRUNCATE ON rule_versions
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('rule_versions is append-only');

CREATE TABLE IF NOT EXISTS rule_conditions (
    id              bigserial PRIMARY KEY,
    rule_version_id bigint NOT NULL REFERENCES rule_versions(id),
    allergen_id     bigint REFERENCES allergens(id),
    medication_a_id bigint NOT NULL REFERENCES medications(id),
    medication_b_id bigint REFERENCES medications(id),
    CHECK ((allergen_id IS NOT NULL AND medication_b_id IS NULL)
        OR (allergen_id IS NULL AND medication_b_id IS NOT NULL AND medication_b_id <> medication_a_id))
);

CREATE OR REPLACE TRIGGER rule_conditions_append_only BEFORE UPDATE OR DELETE ON rule_conditions
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('rule_conditions is append-only');

CREATE OR REPLACE TRIGGER rule_conditions_no_truncate BEFORE TRUNCATE ON rule_conditions
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('rule_conditions is append-only');

CREATE TABLE IF NOT EXISTS rule_resolution_requirements (
    id              bigserial PRIMARY KEY,
    rule_version_id bigint NOT NULL REFERENCES rule_versions(id),
    seq             integer NOT NULL,
    text            text NOT NULL,
    evidence        text NOT NULL CHECK (evidence IN ('confirm','text')),
    UNIQUE (rule_version_id, seq)
);

CREATE OR REPLACE TRIGGER rule_resolution_requirements_append_only BEFORE UPDATE OR DELETE ON rule_resolution_requirements
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('rule_resolution_requirements is append-only');

CREATE OR REPLACE TRIGGER rule_resolution_requirements_no_truncate BEFORE TRUNCATE ON rule_resolution_requirements
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('rule_resolution_requirements is append-only');

CREATE TABLE IF NOT EXISTS incomplete_rules (
    id                 bigserial PRIMARY KEY,
    ruleset_version_id bigint NOT NULL REFERENCES ruleset_versions(id),
    code               text NOT NULL,
    missing            text NOT NULL,
    medication_ids     text NOT NULL,
    conditions_known   boolean NOT NULL
);

CREATE OR REPLACE TRIGGER incomplete_rules_append_only BEFORE UPDATE OR DELETE ON incomplete_rules
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('incomplete_rules is append-only');

CREATE OR REPLACE TRIGGER incomplete_rules_no_truncate BEFORE TRUNCATE ON incomplete_rules
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('incomplete_rules is append-only');

CREATE TABLE IF NOT EXISTS prescriptions (
    id                 bigserial PRIMARY KEY,
    patient_id         bigint NOT NULL REFERENCES patients(id),
    medication_id      bigint NOT NULL REFERENCES medications(id),
    dose               text NOT NULL,
    frequency_id       bigint NOT NULL REFERENCES frequencies(id),
    start_at           text NOT NULL,
    end_at             text NOT NULL,
    prescriber_id      bigint NOT NULL REFERENCES users(id),
    ruleset_version_id bigint NOT NULL REFERENCES ruleset_versions(id),
    status             text NOT NULL DEFAULT 'awaiting_pharmacist'
                       CHECK (status IN ('awaiting_pharmacist','approved','returned','stopped')),
    created_at         text NOT NULL DEFAULT hc_now_text(),
    CHECK (end_at > start_at)
);

CREATE OR REPLACE TRIGGER prescriptions_append_only BEFORE DELETE ON prescriptions
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('prescriptions is append-only');

CREATE OR REPLACE TRIGGER prescriptions_no_truncate BEFORE TRUNCATE ON prescriptions
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('prescriptions is append-only');

CREATE TABLE IF NOT EXISTS prescription_stops (
    id              bigserial PRIMARY KEY,
    prescription_id bigint NOT NULL UNIQUE REFERENCES prescriptions(id),
    stopped_by      bigint NOT NULL REFERENCES users(id),
    stopped_at      text NOT NULL DEFAULT hc_now_text(),
    reason          text NOT NULL CHECK (length(trim(reason)) > 0)
);

CREATE OR REPLACE TRIGGER prescription_stops_append_only BEFORE UPDATE OR DELETE ON prescription_stops
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('prescription_stops is append-only');

CREATE OR REPLACE TRIGGER prescription_stops_no_truncate BEFORE TRUNCATE ON prescription_stops
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('prescription_stops is append-only');

CREATE TABLE IF NOT EXISTS alerts (
    id                      bigserial PRIMARY KEY,
    prescription_id         bigint NOT NULL REFERENCES prescriptions(id),
    rule_version_id         bigint NOT NULL REFERENCES rule_versions(id),
    severity                text NOT NULL CHECK (severity IN ('critical','non_critical')),
    alert_text              text NOT NULL,
    related_prescription_id bigint REFERENCES prescriptions(id),
    related_allergy_id      bigint REFERENCES patient_allergies(id),
    created_at              text NOT NULL DEFAULT hc_now_text(),
    CHECK ((related_prescription_id IS NULL) <> (related_allergy_id IS NULL))
);

CREATE OR REPLACE TRIGGER alerts_append_only BEFORE UPDATE OR DELETE ON alerts
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('alerts is append-only');

CREATE OR REPLACE TRIGGER alerts_no_truncate BEFORE TRUNCATE ON alerts
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('alerts is append-only');

CREATE TABLE IF NOT EXISTS alert_resolutions (
    id            bigserial PRIMARY KEY,
    alert_id      bigint NOT NULL UNIQUE REFERENCES alerts(id),
    pharmacist_id bigint NOT NULL REFERENCES users(id),
    note          text,
    created_at    text NOT NULL DEFAULT hc_now_text()
);

CREATE OR REPLACE TRIGGER alert_resolutions_append_only BEFORE UPDATE OR DELETE ON alert_resolutions
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('alert_resolutions is append-only');

CREATE OR REPLACE TRIGGER alert_resolutions_no_truncate BEFORE TRUNCATE ON alert_resolutions
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('alert_resolutions is append-only');

CREATE TABLE IF NOT EXISTS alert_resolution_items (
    id             bigserial PRIMARY KEY,
    resolution_id  bigint NOT NULL REFERENCES alert_resolutions(id),
    requirement_id bigint NOT NULL REFERENCES rule_resolution_requirements(id),
    confirmed      boolean,
    text_value     text,
    UNIQUE (resolution_id, requirement_id)
);

CREATE OR REPLACE TRIGGER alert_resolution_items_append_only BEFORE UPDATE OR DELETE ON alert_resolution_items
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('alert_resolution_items is append-only');

CREATE OR REPLACE TRIGGER alert_resolution_items_no_truncate BEFORE TRUNCATE ON alert_resolution_items
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('alert_resolution_items is append-only');

CREATE TABLE IF NOT EXISTS alert_acknowledgments (
    id            bigserial PRIMARY KEY,
    alert_id      bigint NOT NULL UNIQUE REFERENCES alerts(id),
    pharmacist_id bigint NOT NULL REFERENCES users(id),
    created_at    text NOT NULL DEFAULT hc_now_text()
);

CREATE OR REPLACE TRIGGER alert_acknowledgments_append_only BEFORE UPDATE OR DELETE ON alert_acknowledgments
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('alert_acknowledgments is append-only');

CREATE OR REPLACE TRIGGER alert_acknowledgments_no_truncate BEFORE TRUNCATE ON alert_acknowledgments
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('alert_acknowledgments is append-only');

CREATE TABLE IF NOT EXISTS pharmacist_reviews (
    id              bigserial PRIMARY KEY,
    prescription_id bigint NOT NULL UNIQUE REFERENCES prescriptions(id),
    pharmacist_id   bigint NOT NULL REFERENCES users(id),
    decision        text NOT NULL CHECK (decision IN ('approved','returned')),
    note            text,
    created_at      text NOT NULL DEFAULT hc_now_text(),
    CHECK (decision = 'approved' OR length(trim(coalesce(note, ''))) > 0)
);

CREATE OR REPLACE TRIGGER pharmacist_reviews_append_only BEFORE UPDATE OR DELETE ON pharmacist_reviews
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('pharmacist_reviews is append-only');

CREATE OR REPLACE TRIGGER pharmacist_reviews_no_truncate BEFORE TRUNCATE ON pharmacist_reviews
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('pharmacist_reviews is append-only');

CREATE TABLE IF NOT EXISTS scheduled_doses (
    id              bigserial PRIMARY KEY,
    prescription_id bigint NOT NULL REFERENCES prescriptions(id),
    dose_number     integer NOT NULL CHECK (dose_number >= 1),
    scheduled_at    text NOT NULL,
    planned_dose    text NOT NULL,
    UNIQUE (prescription_id, dose_number)
);

CREATE OR REPLACE TRIGGER scheduled_doses_append_only BEFORE UPDATE OR DELETE ON scheduled_doses
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('scheduled_doses is append-only');

CREATE OR REPLACE TRIGGER scheduled_doses_no_truncate BEFORE TRUNCATE ON scheduled_doses
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('scheduled_doses is append-only');

CREATE TABLE IF NOT EXISTS administrations (
    id                           bigserial PRIMARY KEY,
    scheduled_dose_id            bigint NOT NULL UNIQUE REFERENCES scheduled_doses(id),
    nurse_id                     bigint NOT NULL REFERENCES users(id),
    outcome                      text NOT NULL CHECK (outcome IN ('given','not_given')),
    actual_dose                  text,
    administered_at_reported     text,
    documented_at                text NOT NULL DEFAULT hc_now_text(),
    not_given_reason_id          bigint REFERENCES not_given_reasons(id),
    reason_text                  text,
    late_reason                  text,
    verified_patient_mrn         text NOT NULL,
    verified_medication          boolean NOT NULL CHECK (verified_medication = true),
    verified_pharmacist_decision boolean NOT NULL CHECK (verified_pharmacist_decision = true),
    warnings                     text NOT NULL,
    CHECK ((outcome = 'given' AND actual_dose IS NOT NULL AND administered_at_reported IS NOT NULL
            AND not_given_reason_id IS NULL)
        OR (outcome = 'not_given' AND not_given_reason_id IS NOT NULL AND actual_dose IS NULL
            AND administered_at_reported IS NULL))
);

CREATE OR REPLACE TRIGGER administrations_append_only BEFORE UPDATE OR DELETE ON administrations
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('administrations is append-only');

CREATE OR REPLACE TRIGGER administrations_no_truncate BEFORE TRUNCATE ON administrations
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('administrations is append-only');

CREATE TABLE IF NOT EXISTS referrals (
    id                bigserial PRIMARY KEY,
    administration_id bigint NOT NULL UNIQUE REFERENCES administrations(id),
    created_by        bigint NOT NULL REFERENCES users(id),
    note              text,
    created_at        text NOT NULL DEFAULT hc_now_text()
);

CREATE OR REPLACE TRIGGER referrals_append_only BEFORE UPDATE OR DELETE ON referrals
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('referrals is append-only');

CREATE OR REPLACE TRIGGER referrals_no_truncate BEFORE TRUNCATE ON referrals
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('referrals is append-only');

CREATE TABLE IF NOT EXISTS referral_closures (
    id                  bigserial PRIMARY KEY,
    referral_id         bigint NOT NULL UNIQUE REFERENCES referrals(id),
    doctor_id           bigint NOT NULL REFERENCES users(id),
    action              text NOT NULL CHECK (action IN ('stopped','new_prescription','no_action')),
    new_prescription_id bigint REFERENCES prescriptions(id),
    note                text,
    created_at          text NOT NULL DEFAULT hc_now_text(),
    CHECK (action <> 'new_prescription' OR new_prescription_id IS NOT NULL),
    CHECK (action <> 'no_action' OR length(trim(coalesce(note, ''))) > 0)
);

CREATE OR REPLACE TRIGGER referral_closures_append_only BEFORE UPDATE OR DELETE ON referral_closures
FOR EACH ROW EXECUTE FUNCTION hc_reject_change('referral_closures is append-only');

CREATE OR REPLACE TRIGGER referral_closures_no_truncate BEFORE TRUNCATE ON referral_closures
FOR EACH STATEMENT EXECUTE FUNCTION hc_reject_change('referral_closures is append-only');

CREATE OR REPLACE FUNCTION hc_rx_transition() RETURNS trigger LANGUAGE plpgsql AS
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
FOR EACH ROW EXECUTE FUNCTION hc_rx_transition();

-- وقت التوثيق يضعه الخادم دائمًا، ويتجاهل أي قيمة يرسلها التطبيق
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
FOR EACH ROW EXECUTE FUNCTION hc_referral_only_not_given();

-- <<< PHASE2 <<<
