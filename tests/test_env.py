"""E: فصل البيئات والإعدادات، و TZ: المنطقة الزمنية."""
import pytest
from sqlalchemy import text

from conftest import AUDIT_KEY, make_sqlite_db
from hc.config import load_config
from hc.db import check_db_env, make_engine
from hc.errors import ConfigError, EnvironmentMismatch
from hc.schema import init_database
from hc.timefmt import to_display
from load_test_fixtures import FixtureGuardError, guarded_test_url, load

KEY = AUDIT_KEY.decode()
BASE = {"HC_DISPLAY_TZ": "Asia/Aden"}


def cfg(**kw):
    return {**BASE, **kw}


def test_E1_db_env_mismatch_refused(tmp_path):
    db = make_sqlite_db(tmp_path, env="dev")
    with pytest.raises(EnvironmentMismatch):
        check_db_env(db.admin.engine, "test")


def test_E1b_cannot_reinit_db_for_other_env(tmp_path):
    db = make_sqlite_db(tmp_path, env="dev")
    with pytest.raises(EnvironmentMismatch):
        init_database(db.admin.engine, "test")


def test_E1c_uninitialized_db_refused(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path/'empty.db'}")
    with pytest.raises(EnvironmentMismatch):
        check_db_env(eng, "test")


def test_E2_fixtures_refused_outside_test_env(tmp_path):
    url = f"sqlite:///{tmp_path/'x.db'}"
    for env in ("dev", "demo", "", None):
        e = {"HC_TEST_DATABASE_URL": url}
        if env is not None:
            e["HC_ENV"] = env
        with pytest.raises(FixtureGuardError):
            guarded_test_url(e)


def test_E2b_fixtures_refuse_db_labelled_demo_before_any_write(tmp_path):
    demo = make_sqlite_db(tmp_path, name="demo.db", env="demo")
    with pytest.raises(EnvironmentMismatch):
        load({"HC_ENV": "test", "HC_TEST_DATABASE_URL": demo.app_url})
    assert demo.count("allergens") == 0


def test_E3_fixtures_never_read_demo_credentials(tmp_path):
    demo_url = f"sqlite:///{tmp_path/'demo.db'}"
    # إعداد خاطئ: لا يوجد عنوان اختبار، فقط عنوان demo — يجب ألا يُستخدم
    with pytest.raises(FixtureGuardError):
        guarded_test_url({"HC_ENV": "test", "HC_DEMO_DATABASE_URL": demo_url})
    # إعداد خاطئ: عنوان الاختبار نُسخ من demo
    with pytest.raises(FixtureGuardError):
        guarded_test_url({"HC_ENV": "test", "HC_TEST_DATABASE_URL": demo_url,
                          "HC_DEMO_DATABASE_URL": demo_url})


def test_E3b_pg_test_db_name_must_end_with_test():
    with pytest.raises(FixtureGuardError):
        guarded_test_url({"HC_ENV": "test",
                          "HC_TEST_DATABASE_URL": "postgresql+psycopg://u@h/hc_demo"})
    assert guarded_test_url({"HC_ENV": "test",
                             "HC_TEST_DATABASE_URL": "postgresql+psycopg://u@h/hc_x_test"})


def test_E4_app_config_rejects_anchor_key():
    with pytest.raises(ConfigError):
        load_config(cfg(HC_ENV="test", HC_TEST_DATABASE_URL="sqlite:///a.db",
                        HC_TEST_AUDIT_HMAC_KEY=KEY, HC_ANCHOR_KEY="x" * 40))


def test_E4b_demo_requires_postgres():
    with pytest.raises(ConfigError):
        load_config(cfg(HC_ENV="demo", HC_DEMO_DATABASE_URL="sqlite:///a.db",
                        HC_DEMO_AUDIT_HMAC_KEY=KEY))


def test_E4c_two_envs_same_db_refused():
    with pytest.raises(ConfigError):
        load_config(cfg(HC_ENV="dev", HC_DEV_DATABASE_URL="postgresql+psycopg://u@h/d",
                        HC_DEMO_DATABASE_URL="postgresql+psycopg://u@h/d", HC_DEV_AUDIT_HMAC_KEY=KEY))


def test_E4d_missing_or_bad_settings():
    good = cfg(HC_ENV="dev", HC_DEV_DATABASE_URL="sqlite:///a.db", HC_DEV_AUDIT_HMAC_KEY=KEY)
    assert load_config(good).env == "dev"
    for bad in ({**good, "HC_ENV": "prod"},
                {**good, "HC_DEV_AUDIT_HMAC_KEY": "short"},
                {k: v for k, v in good.items() if k != "HC_DISPLAY_TZ"},
                {**good, "HC_DISPLAY_TZ": "Mars/Olympus"},
                {k: v for k, v in good.items() if k != "HC_DEV_DATABASE_URL"}):
        with pytest.raises(ConfigError):
            load_config(bad)


def test_E4e_app_never_receives_admin_url():
    c = load_config(cfg(HC_ENV="dev", HC_DEV_DATABASE_URL="sqlite:///a.db", HC_DEV_AUDIT_HMAC_KEY=KEY,
                        HC_DEV_ADMIN_DATABASE_URL="sqlite:///admin.db"))
    assert c.admin_database_url is None


def test_E5_app_reads_only_its_own_env_vars():
    # HC_ENV=dev لكن عنوان dev غير موجود؛ وجود عنوان demo لا يجب أن يُستخدم بدلًا منه
    with pytest.raises(ConfigError):
        load_config(cfg(HC_ENV="dev", HC_DEMO_DATABASE_URL="postgresql+psycopg://u@h/d",
                        HC_DEMO_AUDIT_HMAC_KEY=KEY))


def test_TZ1_storage_utc_display_configurable(tdb):
    s = tdb.session("reg1", "registration")
    from hc import patients as P
    p = P.create_patient(tdb.app, s, full_name="مريض", age=30, allergy_status="none_known")
    with tdb.admin.engine.connect() as c:
        created = c.execute(text("SELECT created_at FROM patients WHERE id=:i"), {"i": p["id"]}).scalar_one()
    assert created.endswith("Z")  # مخزّن بالتوقيت العالمي
    assert to_display("2026-11-26T13:00:00.000000Z", "Asia/Aden") == "2026-11-26 16:00"
    assert to_display("2026-11-26T13:00:00.000000Z", "UTC") == "2026-11-26 13:00"
