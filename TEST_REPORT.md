# تقرير الاختبارات — مولّد آليًا من مخرجات pytest

وقت التشغيل (من الملف): 2026-11-26T19:58:13.408417+03:00 · المضيف: vm

**المجموع:** 252 · نجح 245 · فشل 0 · خطأ 0 · لم يُنفَّذ 7

| الملف | الاختبار | المعامل | المحرك | النتيجة | ملاحظة | الزمن (ث) |
|---|---|---|---|---|---|---|
| test_anchor | test_T21_tail_deletion_chain_blind_anchor_detects | sqlite | sqlite | نجح |  | 0.769 |
| test_anchor | test_T21_tail_deletion_chain_blind_anchor_detects | postgresql | postgresql | نجح |  | 0.859 |
| test_anchor | test_T22_restore_older_copy_chain_blind_anchor_detects | sqlite | sqlite | نجح |  | 0.655 |
| test_anchor | test_T22_restore_older_copy_chain_blind_anchor_detects | postgresql | postgresql | نجح |  | 1.067 |
| test_anchor | test_T23_recompute_with_wrong_key_detected | sqlite | sqlite | نجح |  | 0.689 |
| test_anchor | test_T23_recompute_with_wrong_key_detected | postgresql | postgresql | نجح |  | 0.867 |
| test_anchor | test_T24_correct_key_hides_from_chain_but_anchor_detects | sqlite | sqlite | نجح |  | 0.669 |
| test_anchor | test_T24_correct_key_hides_from_chain_but_anchor_detects | postgresql | postgresql | نجح |  | 0.900 |
| test_anchor | test_T25_correct_key_after_anchor_NOT_detected | sqlite | sqlite | نجح |  | 0.669 |
| test_anchor | test_T25_correct_key_after_anchor_NOT_detected | postgresql | postgresql | نجح |  | 0.892 |
| test_anchor | test_T26_anchor_file_tamper_or_wrong_key_rejected | sqlite | sqlite | نجح |  | 0.676 |
| test_anchor | test_T26_anchor_file_tamper_or_wrong_key_rejected | postgresql | postgresql | نجح |  | 0.999 |
| test_app_ui | test_UI1_login_and_register_patient |  | — | نجح |  | 1.008 |
| test_app_ui | test_UI2_bad_login_shows_error_and_wrong_role_cannot_see_forms |  | — | نجح |  | 1.559 |
| test_app_ui | test_UI3_wrong_env_db_refuses_to_start |  | — | نجح |  | 0.324 |
| test_app_ui_cycle | test_UI5_full_cycle_through_screens |  | — | نجح |  | 3.814 |
| test_app_ui_cycle | test_UI6_nurse_sees_block_and_cannot_document_given |  | — | نجح |  | 3.537 |
| test_app_ui_cycle | test_UI7_every_role_every_page_renders |  | — | نجح |  | 3.944 |
| test_app_ui_cycle | test_UI8_doctor_cannot_send_when_allergy_not_recorded |  | — | نجح |  | 2.506 |
| test_app_ui_cycle | test_UI9_register_new_patient_with_allergies_from_screen |  | — | نجح |  | 2.540 |
| test_app_ui_history | test_UI4_allergy_removal_shows_in_history |  | — | نجح |  | 1.474 |
| test_audit | test_A1_success_saves_data_and_audit_together | sqlite | sqlite | نجح |  | 0.660 |
| test_audit | test_A1_success_saves_data_and_audit_together | postgresql | postgresql | نجح |  | 0.882 |
| test_audit | test_A3_audit_failure_on_success_path_rolls_back_operation | sqlite | sqlite | نجح |  | 0.664 |
| test_audit | test_A3_audit_failure_on_success_path_rolls_back_operation | postgresql | postgresql | نجح |  | 0.933 |
| test_audit | test_A7_operation_error_with_live_connection_audited_separately | sqlite | sqlite | نجح |  | 0.645 |
| test_audit | test_A7_operation_error_with_live_connection_audited_separately | postgresql | postgresql | نجح |  | 0.943 |
| test_audit | test_A8_if_separate_audit_also_fails_we_do_not_claim_it | sqlite | sqlite | نجح |  | 0.695 |
| test_audit | test_A8_if_separate_audit_also_fails_we_do_not_claim_it | postgresql | postgresql | نجح |  | 0.949 |
| test_audit | test_A6_connection_failure_goes_to_external_log_only | sqlite | sqlite | نجح |  | 0.041 |
| test_audit | test_A6_connection_failure_goes_to_external_log_only | postgresql | postgresql | نجح |  | 0.299 |
| test_audit | test_A4_audit_log_append_only_even_for_owner | sqlite-UPDATE audit_log SET details='{}' WHERE seq=1 | sqlite | نجح |  | 0.659 |
| test_audit | test_A4_audit_log_append_only_even_for_owner | sqlite-DELETE FROM audit_log WHERE seq=1 | sqlite | نجح |  | 0.641 |
| test_audit | test_A4_audit_log_append_only_even_for_owner | postgresql-UPDATE audit_log SET details='{}' WHERE seq=1 | postgresql | نجح |  | 0.934 |
| test_audit | test_A4_audit_log_append_only_even_for_owner | postgresql-DELETE FROM audit_log WHERE seq=1 | postgresql | نجح |  | 0.937 |
| test_audit | test_A4b_truncate_blocked_postgres | sqlite | sqlite | لم يُنفَّذ (تخطٍّ) | TRUNCATE غير موجود في SQLite | 0.656 |
| test_audit | test_A4b_truncate_blocked_postgres | postgresql | postgresql | نجح |  | 0.877 |
| test_audit | test_A5_middle_edit_and_middle_delete_detected | sqlite | sqlite | نجح |  | 0.633 |
| test_audit | test_A5_middle_edit_and_middle_delete_detected | postgresql | postgresql | نجح |  | 0.978 |
| test_audit | test_A9_rejections_never_save_data | sqlite | sqlite | نجح |  | 1.261 |
| test_audit | test_A9_rejections_never_save_data | postgresql | postgresql | نجح |  | 1.515 |
| test_concurrency | test_C1_C2_two_nurses_same_item_exactly_one_wins | sqlite | sqlite | نجح |  | 1.440 |
| test_concurrency | test_C1_C2_two_nurses_same_item_exactly_one_wins | postgresql | postgresql | نجح |  | 1.819 |
| test_concurrency | test_C3_unique_constraint_is_last_line_of_defence | sqlite | sqlite | نجح |  | 0.628 |
| test_concurrency | test_C3_unique_constraint_is_last_line_of_defence | postgresql | postgresql | نجح |  | 0.931 |
| test_concurrency | test_C4_unique_violation_handled_and_connection_stays_usable | sqlite | sqlite | نجح |  | 0.671 |
| test_concurrency | test_C4_unique_violation_handled_and_connection_stays_usable | postgresql | postgresql | نجح |  | 0.979 |
| test_concurrency | test_C5_only_nurse_role_can_claim | sqlite | sqlite | نجح |  | 0.747 |
| test_concurrency | test_C5_only_nurse_role_can_claim | postgresql | postgresql | نجح |  | 0.898 |
| test_deploy_admin | test_D1_no_expression_inside_run_commands |  | — | نجح |  | 0.006 |
| test_deploy_admin | test_D2_validation_step_runs_first_and_rejects_injection |  | — | نجح |  | 0.078 |
| test_deploy_admin | test_D2b_inputs_only_used_quoted_env_vars |  | — | نجح |  | 0.005 |
| test_deploy_admin | test_D3_create_app_role_safe_and_limited |  | — | نجح |  | 0.047 |
| test_env | test_E1_db_env_mismatch_refused |  | — | نجح |  | 0.029 |
| test_env | test_E1b_cannot_reinit_db_for_other_env |  | — | نجح |  | 0.025 |
| test_env | test_E1c_uninitialized_db_refused |  | — | نجح |  | 0.003 |
| test_env | test_E2_fixtures_refused_outside_test_env |  | — | نجح |  | 0.001 |
| test_env | test_E2b_fixtures_refuse_db_labelled_demo_before_any_write |  | — | نجح |  | 0.040 |
| test_env | test_E3_fixtures_never_read_demo_credentials |  | — | نجح |  | 0.001 |
| test_env | test_E3b_pg_test_db_name_must_end_with_test |  | — | نجح |  | 0.001 |
| test_env | test_E4_app_config_rejects_anchor_key |  | — | نجح |  | 0.001 |
| test_env | test_E4b_demo_requires_postgres |  | — | نجح |  | 0.001 |
| test_env | test_E4c_two_envs_same_db_refused |  | — | نجح |  | 0.001 |
| test_env | test_E4d_missing_or_bad_settings |  | — | نجح |  | 0.001 |
| test_env | test_E4e_app_never_receives_admin_url |  | — | نجح |  | 0.001 |
| test_env | test_E5_app_reads_only_its_own_env_vars |  | — | نجح |  | 0.001 |
| test_env | test_TZ1_storage_utc_display_configurable | sqlite | sqlite | نجح |  | 0.631 |
| test_env | test_TZ1_storage_utc_display_configurable | postgresql | postgresql | نجح |  | 0.944 |
| test_illustrative_mode | test_I1_illustrative_refused_in_test_env |  | — | نجح |  | 0.038 |
| test_illustrative_mode | test_I2_illustrative_refused_in_demo_without_flag |  | — | نجح |  | 0.041 |
| test_illustrative_mode | test_I3_test_fixtures_refused_in_demo_even_with_flag |  | — | نجح |  | 0.037 |
| test_illustrative_mode | test_I4_illustrative_loads_in_demo_with_flag_and_is_labelled |  | — | نجح |  | 0.062 |
| test_illustrative_mode | test_I5_separation_no_shared_names_or_codes |  | — | نجح |  | 0.001 |
| test_illustrative_mode | test_I6_runtime_flag_required_for_prescribing |  | — | نجح |  | 1.231 |
| test_illustrative_mode | test_I7_illustrative_ruleset_unusable_in_test_env |  | — | نجح |  | 1.231 |
| test_illustrative_mode | test_I8_config_flag_rules |  | — | نجح |  | 0.001 |
| test_illustrative_mode | test_I9_warning_banner_on_every_page_in_demo |  | — | نجح |  | 4.989 |
| test_known_secrets_guard | test_K1_test_audit_key_refused_as_demo_key |  | — | نجح |  | 0.001 |
| test_known_secrets_guard | test_K2_test_passwords_refused_for_demo_accounts |  | — | نجح |  | 0.359 |
| test_known_secrets_guard | test_K3_test_passwords_still_allowed_in_test_env |  | — | نجح |  | 0.336 |
| test_known_secrets_guard | test_K4_test_anchor_key_refused_in_demo |  | — | نجح |  | 0.274 |
| test_known_secrets_guard | test_K5_test_password_refused_for_app_role_in_demo |  | — | نجح |  | 0.019 |
| test_known_secrets_guard | test_K6_every_secret_constant_in_tests_is_guarded |  | — | نجح |  | 0.038 |
| test_known_secrets_guard | test_K7_guard_module_stores_hashes_not_values |  | — | نجح |  | 0.035 |
| test_medication_cycle | test_M1_no_ruleset_no_prescribing | sqlite | sqlite | نجح |  | 1.245 |
| test_medication_cycle | test_M1_no_ruleset_no_prescribing | postgresql | postgresql | نجح |  | 1.571 |
| test_medication_cycle | test_M2_allergy_not_recorded_blocks_sending | sqlite | sqlite | نجح |  | 3.802 |
| test_medication_cycle | test_M2_allergy_not_recorded_blocks_sending | postgresql | postgresql | نجح |  | 4.068 |
| test_medication_cycle | test_M3_only_doctor_prescribes | sqlite-reg | sqlite | نجح |  | 3.689 |
| test_medication_cycle | test_M3_only_doctor_prescribes | sqlite-ph | sqlite | نجح |  | 3.645 |
| test_medication_cycle | test_M3_only_doctor_prescribes | sqlite-nu | sqlite | نجح |  | 3.682 |
| test_medication_cycle | test_M3_only_doctor_prescribes | postgresql-reg | postgresql | نجح |  | 4.150 |
| test_medication_cycle | test_M3_only_doctor_prescribes | postgresql-ph | postgresql | نجح |  | 4.163 |
| test_medication_cycle | test_M3_only_doctor_prescribes | postgresql-nu | postgresql | نجح |  | 4.274 |
| test_medication_cycle | test_M4_input_validation | sqlite-kw0 | sqlite | نجح |  | 3.735 |
| test_medication_cycle | test_M4_input_validation | sqlite-kw1 | sqlite | نجح |  | 3.793 |
| test_medication_cycle | test_M4_input_validation | sqlite-kw2 | sqlite | نجح |  | 3.698 |
| test_medication_cycle | test_M4_input_validation | sqlite-kw3 | sqlite | نجح |  | 3.723 |
| test_medication_cycle | test_M4_input_validation | sqlite-kw4 | sqlite | نجح |  | 3.792 |
| test_medication_cycle | test_M4_input_validation | postgresql-kw0 | postgresql | نجح |  | 4.056 |
| test_medication_cycle | test_M4_input_validation | postgresql-kw1 | postgresql | نجح |  | 4.083 |
| test_medication_cycle | test_M4_input_validation | postgresql-kw2 | postgresql | نجح |  | 3.996 |
| test_medication_cycle | test_M4_input_validation | postgresql-kw3 | postgresql | نجح |  | 3.945 |
| test_medication_cycle | test_M4_input_validation | postgresql-kw4 | postgresql | نجح |  | 4.054 |
| test_medication_cycle | test_M4b_start_in_past_rejected | sqlite | sqlite | نجح |  | 3.701 |
| test_medication_cycle | test_M4b_start_in_past_rejected | postgresql | postgresql | نجح |  | 4.162 |
| test_medication_cycle | test_M5_alerts_generated_by_rules | sqlite | sqlite | نجح |  | 3.748 |
| test_medication_cycle | test_M5_alerts_generated_by_rules | postgresql | postgresql | نجح |  | 4.198 |
| test_medication_cycle | test_M6_no_alert_still_goes_to_pharmacist_then_doses | sqlite | sqlite | نجح |  | 3.702 |
| test_medication_cycle | test_M6_no_alert_still_goes_to_pharmacist_then_doses | postgresql | postgresql | نجح |  | 4.048 |
| test_medication_cycle | test_M7_return_only_rule_cannot_be_approved | sqlite | sqlite | نجح |  | 3.621 |
| test_medication_cycle | test_M7_return_only_rule_cannot_be_approved | postgresql | postgresql | نجح |  | 4.001 |
| test_medication_cycle | test_M8_conditional_needs_every_requirement | sqlite | sqlite | نجح |  | 3.764 |
| test_medication_cycle | test_M8_conditional_needs_every_requirement | postgresql | postgresql | نجح |  | 4.136 |
| test_medication_cycle | test_M9_non_critical_needs_ack | sqlite | sqlite | نجح |  | 3.703 |
| test_medication_cycle | test_M9_non_critical_needs_ack | postgresql | postgresql | نجح |  | 4.036 |
| test_medication_cycle | test_M10_stale_check_new_allergy_after_creation | sqlite | sqlite | نجح |  | 3.603 |
| test_medication_cycle | test_M10_stale_check_new_allergy_after_creation | postgresql | postgresql | نجح |  | 4.155 |
| test_medication_cycle | test_M10b_only_pharmacist_reviews | sqlite | sqlite | نجح |  | 3.643 |
| test_medication_cycle | test_M10b_only_pharmacist_reviews | postgresql | postgresql | نجح |  | 4.020 |
| test_medication_cycle | test_M11_nurse_verification | sqlite | sqlite | نجح |  | 3.604 |
| test_medication_cycle | test_M11_nurse_verification | postgresql | postgresql | نجح |  | 4.125 |
| test_medication_cycle | test_M12_dose_mismatch_not_given_referral_and_no_duplicates | sqlite | sqlite | نجح |  | 3.639 |
| test_medication_cycle | test_M12_dose_mismatch_not_given_referral_and_no_duplicates | postgresql | postgresql | نجح |  | 3.921 |
| test_medication_cycle | test_M13_unresolved_critical_blocks_existing_rx_until_resolved | sqlite | sqlite | نجح |  | 3.669 |
| test_medication_cycle | test_M13_unresolved_critical_blocks_existing_rx_until_resolved | postgresql | postgresql | نجح |  | 4.189 |
| test_medication_cycle | test_M13b_not_given_always_documentable_even_when_blocked | sqlite | sqlite | نجح |  | 3.627 |
| test_medication_cycle | test_M13b_not_given_always_documentable_even_when_blocked | postgresql | postgresql | نجح |  | 3.936 |
| test_medication_cycle | test_M14_warn_only_policy_allows_with_recorded_warning | sqlite | sqlite | نجح |  | 3.583 |
| test_medication_cycle | test_M14_warn_only_policy_allows_with_recorded_warning | postgresql | postgresql | نجح |  | 4.008 |
| test_medication_cycle | test_M15_new_undocumented_allergy_blocks_given | sqlite | sqlite | نجح |  | 3.755 |
| test_medication_cycle | test_M15_new_undocumented_allergy_blocks_given | postgresql | postgresql | نجح |  | 3.958 |
| test_medication_cycle | test_M16_missed_dose_sequence_policy | sqlite-strict-False | sqlite | نجح |  | 3.644 |
| test_medication_cycle | test_M16_missed_dose_sequence_policy | sqlite-warn-True | sqlite | نجح |  | 3.664 |
| test_medication_cycle | test_M16_missed_dose_sequence_policy | postgresql-strict-False | postgresql | نجح |  | 4.021 |
| test_medication_cycle | test_M16_missed_dose_sequence_policy | postgresql-warn-True | postgresql | نجح |  | 4.088 |
| test_medication_cycle | test_M17_late_documentation_separate_times | sqlite | sqlite | نجح |  | 3.581 |
| test_medication_cycle | test_M17_late_documentation_separate_times | postgresql | postgresql | نجح |  | 4.099 |
| test_medication_cycle | test_M17b_late_limit | sqlite | sqlite | نجح |  | 3.564 |
| test_medication_cycle | test_M17b_late_limit | postgresql | postgresql | نجح |  | 3.769 |
| test_medication_cycle | test_M17c_documented_at_cannot_be_supplied_postgres | sqlite | sqlite | لم يُنفَّذ (تخطٍّ) | في SQLite لا يمكن للمشغّل تعديل القيمة المُدرجة؛ الحماية هنا أن الكود لا يرسلها | 3.547 |
| test_medication_cycle | test_M17c_documented_at_cannot_be_supplied_postgres | postgresql | postgresql | نجح |  | 4.204 |
| test_medication_cycle | test_M17d_app_code_never_sends_documented_at |  | — | نجح |  | 0.001 |
| test_medication_cycle | test_M18_stop_prescriber_only_cancels_future_doses | sqlite | sqlite | نجح |  | 3.726 |
| test_medication_cycle | test_M18_stop_prescriber_only_cancels_future_doses | postgresql | postgresql | نجح |  | 4.211 |
| test_medication_cycle | test_M19_referral_closure_rules | sqlite | sqlite | نجح |  | 3.697 |
| test_medication_cycle | test_M19_referral_closure_rules | postgresql | postgresql | نجح |  | 3.934 |
| test_medication_cycle | test_M20_incomplete_rule_blocks_only_what_it_touches | sqlite | sqlite | نجح |  | 1.259 |
| test_medication_cycle | test_M20_incomplete_rule_blocks_only_what_it_touches | postgresql | postgresql | نجح |  | 1.589 |
| test_medication_cycle | test_M20b_unknown_conditions_block_everything | sqlite | sqlite | نجح |  | 1.277 |
| test_medication_cycle | test_M20b_unknown_conditions_block_everything | postgresql | postgresql | نجح |  | 1.477 |
| test_medication_cycle | test_M21_synthetic_ruleset_refused_outside_test | sqlite | sqlite | نجح |  | 0.040 |
| test_medication_cycle | test_M21_synthetic_ruleset_refused_outside_test | postgresql | postgresql | نجح |  | 0.250 |
| test_medication_cycle | test_M22_missing_policies_stop_only_dependent_functions | sqlite | sqlite | نجح |  | 1.226 |
| test_medication_cycle | test_M22_missing_policies_stop_only_dependent_functions | postgresql | postgresql | نجح |  | 1.610 |
| test_medication_cycle | test_M23_cycle_tables_immutable_and_transitions_enforced | sqlite | sqlite | نجح |  | 3.669 |
| test_medication_cycle | test_M23_cycle_tables_immutable_and_transitions_enforced | postgresql | postgresql | نجح |  | 4.060 |
| test_medication_cycle | test_M24_two_nurses_same_dose_one_wins | sqlite | sqlite | نجح |  | 3.613 |
| test_medication_cycle | test_M24_two_nurses_same_dose_one_wins | postgresql | postgresql | نجح |  | 3.992 |
| test_medication_cycle | test_M25_app_db_account_limits_postgres | sqlite | sqlite | لم يُنفَّذ (تخطٍّ) | صلاحيات الحسابات خاصة بـ PostgreSQL | 3.568 |
| test_medication_cycle | test_M25_app_db_account_limits_postgres | postgresql | postgresql | نجح |  | 3.991 |
| test_medication_cycle | test_M26_whole_cycle_audited_and_chain_valid | sqlite | sqlite | نجح |  | 3.792 |
| test_medication_cycle | test_M26_whole_cycle_audited_and_chain_valid | postgresql | postgresql | نجح |  | 4.243 |
| test_medication_cycle | test_M27_approval_refused_if_allergy_status_reset | sqlite | sqlite | نجح |  | 3.629 |
| test_medication_cycle | test_M27_approval_refused_if_allergy_status_reset | postgresql | postgresql | نجح |  | 3.985 |
| test_medication_cycle | test_M28_removal_reason_mandatory_whitespace_rejected | sqlite | sqlite | نجح |  | 3.553 |
| test_medication_cycle | test_M28_removal_reason_mandatory_whitespace_rejected | postgresql | postgresql | نجح |  | 3.820 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs0 | sqlite | نجح |  | 0.625 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs1 | sqlite | نجح |  | 0.631 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs2 | sqlite | نجح |  | 0.651 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs3 | sqlite | نجح |  | 0.630 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs4 | sqlite | نجح |  | 0.617 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs5 | sqlite | نجح |  | 0.628 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs6 | sqlite | نجح |  | 0.624 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs7 | sqlite | نجح |  | 0.634 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs8 | sqlite | نجح |  | 0.658 |
| test_patients | test_P1_validation_rejected_nothing_saved | sqlite-kwargs9 | sqlite | نجح |  | 0.644 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs0 | postgresql | نجح |  | 0.789 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs1 | postgresql | نجح |  | 0.806 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs2 | postgresql | نجح |  | 0.782 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs3 | postgresql | نجح |  | 0.786 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs4 | postgresql | نجح |  | 0.753 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs5 | postgresql | نجح |  | 0.764 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs6 | postgresql | نجح |  | 0.802 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs7 | postgresql | نجح |  | 0.776 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs8 | postgresql | نجح |  | 0.782 |
| test_patients | test_P1_validation_rejected_nothing_saved | postgresql-kwargs9 | postgresql | نجح |  | 0.801 |
| test_patients | test_P1b_allergen_consistency | sqlite | sqlite | نجح |  | 0.657 |
| test_patients | test_P1b_allergen_consistency | postgresql | postgresql | نجح |  | 0.927 |
| test_patients | test_P2_concurrent_creates_get_unique_mrns | sqlite | sqlite | نجح |  | 0.719 |
| test_patients | test_P2_concurrent_creates_get_unique_mrns | postgresql | postgresql | نجح |  | 0.983 |
| test_patients | test_P3_stale_version_rejected | sqlite | sqlite | نجح |  | 1.286 |
| test_patients | test_P3_stale_version_rejected | postgresql | postgresql | نجح |  | 1.483 |
| test_patients | test_P3b_truly_simultaneous_updates_one_wins | sqlite | sqlite | نجح |  | 0.660 |
| test_patients | test_P3b_truly_simultaneous_updates_one_wins | postgresql | postgresql | نجح |  | 0.902 |
| test_patients | test_P4_not_recorded_is_kept_distinct | sqlite | sqlite | نجح |  | 0.649 |
| test_patients | test_P4_not_recorded_is_kept_distinct | postgresql | postgresql | نجح |  | 1.038 |
| test_patients | test_P5_mrn_immutable_and_no_delete | sqlite | sqlite | نجح |  | 0.633 |
| test_patients | test_P5_mrn_immutable_and_no_delete | postgresql | postgresql | نجح |  | 0.936 |
| test_phase1_fixes | test_R1_open_read_transaction_does_not_hold_write_lock | sqlite | sqlite | نجح |  | 0.626 |
| test_phase1_fixes | test_R1_open_read_transaction_does_not_hold_write_lock | postgresql | postgresql | لم يُنفَّذ (تخطٍّ) | خاص بـ SQLite؛ PostgreSQL لا يقفل القاعدة عند القراءة أصلًا | 0.241 |
| test_phase1_fixes | test_R2_write_transaction_still_reserves_lock | sqlite | sqlite | نجح |  | 0.033 |
| test_phase1_fixes | test_R2_write_transaction_still_reserves_lock | postgresql | postgresql | لم يُنفَّذ (تخطٍّ) | خاص بـ SQLite | 0.239 |
| test_phase1_fixes | test_R3_concurrent_reads_and_a_write_while_reads_are_open | sqlite | sqlite | نجح |  | 0.635 |
| test_phase1_fixes | test_R3_concurrent_reads_and_a_write_while_reads_are_open | postgresql | postgresql | نجح |  | 0.993 |
| test_phase1_fixes | test_T27_anchor_env_must_match_db_env | sqlite | sqlite | نجح |  | 0.636 |
| test_phase1_fixes | test_T27_anchor_env_must_match_db_env | postgresql | postgresql | نجح |  | 0.980 |
| test_phase1_fixes | test_T27b_real_anchor_from_dev_db_rejected_on_test_db | sqlite | sqlite | نجح |  | 0.378 |
| test_phase1_fixes | test_T27b_real_anchor_from_dev_db_rejected_on_test_db | postgresql | postgresql | نجح |  | 0.621 |
| test_phase1_fixes | test_X1_export_refused_when_chain_broken | sqlite | sqlite | نجح |  | 0.653 |
| test_phase1_fixes | test_X1_export_refused_when_chain_broken | postgresql | postgresql | نجح |  | 0.905 |
| test_phase1_fixes | test_X2_explicit_override_is_signed_and_audited_and_never_clean | sqlite | sqlite | نجح |  | 0.670 |
| test_phase1_fixes | test_X2_explicit_override_is_signed_and_audited_and_never_clean | postgresql | postgresql | نجح |  | 0.965 |
| test_phase1_fixes | test_X3_clean_export_is_audited | sqlite | sqlite | نجح |  | 0.330 |
| test_phase1_fixes | test_X3_clean_export_is_audited | postgresql | postgresql | نجح |  | 0.635 |
| test_phase1_fixes | test_X4_cli_refuses_then_accepts_documented_override |  | — | نجح |  | 1.154 |
| test_phase1_fixes | test_H1_removal_keeps_history_with_who_when_why | sqlite | sqlite | نجح |  | 0.663 |
| test_phase1_fixes | test_H1_removal_keeps_history_with_who_when_why | postgresql | postgresql | نجح |  | 0.881 |
| test_phase1_fixes | test_H2_readding_creates_new_row_old_row_untouched | sqlite | sqlite | نجح |  | 0.688 |
| test_phase1_fixes | test_H2_readding_creates_new_row_old_row_untouched | postgresql | postgresql | نجح |  | 1.026 |
| test_phase1_fixes | test_H3_history_cannot_be_deleted_or_rewritten | sqlite | sqlite | نجح |  | 0.669 |
| test_phase1_fixes | test_H3_history_cannot_be_deleted_or_rewritten | postgresql | postgresql | نجح |  | 0.897 |
| test_phase1_fixes | test_H4_only_one_current_row_per_allergen | sqlite | sqlite | نجح |  | 0.644 |
| test_phase1_fixes | test_H4_only_one_current_row_per_allergen | postgresql | postgresql | نجح |  | 1.100 |
| test_phase1_fixes | test_H5_app_db_account_cannot_delete_allergy_history | sqlite | sqlite | لم يُنفَّذ (تخطٍّ) | صلاحيات الحسابات خاصة بـ PostgreSQL؛ في SQLite يحمي المشغّل فقط (H3) | 0.645 |
| test_phase1_fixes | test_H5_app_db_account_cannot_delete_allergy_history | postgresql | postgresql | نجح |  | 1.018 |
| test_phase1_fixes | test_H6_removal_reason_too_long_rejected | sqlite | sqlite | نجح |  | 0.682 |
| test_phase1_fixes | test_H6_removal_reason_too_long_rejected | postgresql | postgresql | نجح |  | 1.071 |
| test_users | test_U1_login_ok_and_bad | sqlite | sqlite | نجح |  | 1.235 |
| test_users | test_U1_login_ok_and_bad | postgresql | postgresql | نجح |  | 1.499 |
| test_users | test_U2_deactivated_cannot_login | sqlite | sqlite | نجح |  | 0.615 |
| test_users | test_U2_deactivated_cannot_login | postgresql | postgresql | نجح |  | 0.885 |
| test_users | test_U3_reset_password | sqlite | sqlite | نجح |  | 1.584 |
| test_users | test_U3_reset_password | postgresql | postgresql | نجح |  | 1.845 |
| test_users | test_U3b_short_password_rejected | sqlite | sqlite | نجح |  | 0.041 |
| test_users | test_U3b_short_password_rejected | postgresql | postgresql | نجح |  | 0.262 |
| test_users | test_U4_only_registration_writes_patients | sqlite-doctor | sqlite | نجح |  | 1.214 |
| test_users | test_U4_only_registration_writes_patients | sqlite-pharmacist | sqlite | نجح |  | 1.213 |
| test_users | test_U4_only_registration_writes_patients | sqlite-nurse | sqlite | نجح |  | 1.243 |
| test_users | test_U4_only_registration_writes_patients | postgresql-doctor | postgresql | نجح |  | 1.574 |
| test_users | test_U4_only_registration_writes_patients | postgresql-pharmacist | postgresql | نجح |  | 1.570 |
| test_users | test_U4_only_registration_writes_patients | postgresql-nurse | postgresql | نجح |  | 1.551 |
| test_users | test_U4b_no_session_denied_and_audited | sqlite | sqlite | نجح |  | 0.040 |
| test_users | test_U4b_no_session_denied_and_audited | postgresql | postgresql | نجح |  | 0.283 |
| test_users | test_U5_deactivated_mid_session_rejected_immediately | sqlite | sqlite | نجح |  | 0.655 |
| test_users | test_U5_deactivated_mid_session_rejected_immediately | postgresql | postgresql | نجح |  | 0.907 |
| test_users | test_U6_role_cannot_be_changed_even_by_owner | sqlite | sqlite | نجح |  | 0.334 |
| test_users | test_U6_role_cannot_be_changed_even_by_owner | postgresql | postgresql | نجح |  | 0.643 |
| test_users | test_U6b_app_db_account_cannot_create_or_promote_users | sqlite | sqlite | لم يُنفَّذ (تخطٍّ) | SQLite لا يملك حسابات قاعدة بيانات منفصلة؛ الحماية هنا في الكود فقط (U6c) | 0.040 |
| test_users | test_U6b_app_db_account_cannot_create_or_promote_users | postgresql | postgresql | نجح |  | 0.646 |
| test_users | test_U6c_app_code_has_no_user_creation_path |  | — | نجح |  | 0.007 |
| test_users | test_U7_first_account_via_script_no_default_password |  | — | نجح |  | 2.970 |
