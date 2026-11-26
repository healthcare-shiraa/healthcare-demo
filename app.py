"""Health Care — واجهة النموذج الأولي.

الواجهة لا تقرر الصلاحيات ولا السلامة: كل عملية تمر بدوال الخادم في hc/ التي تفحص
المستخدم ودوره والقواعد من قاعدة البيانات. إخفاء الأزرار هنا للراحة فقط.
"""
from __future__ import annotations

import streamlit as st

from hc.audit import Ctx
from hc.auth import ROLES, Session, login, logout
from hc.config import load_config
from hc.db import check_db_env, make_engine
from hc.errors import ConfigError, DomainError, EnvironmentMismatch, OperationFailed
from hc.reference import status_summary
from hc.ui import doctor, nurse, pharmacist, registration
from hc.ui.common import UI, show_error
from hc.ui.theme import LOGO, disclaimer, e, env_banner, initials, inject_css, logo

st.set_page_config(page_title="Health Care", page_icon="⚕️", layout="wide", initial_sidebar_state="expanded")
inject_css()

ROLE_PAGES = {"registration": registration, "doctor": doctor, "pharmacist": pharmacist, "nurse": nurse}


@st.cache_resource
def get_runtime():
    cfg = load_config({k: str(v) for k, v in st.secrets.items() if not isinstance(v, dict)})
    engine = make_engine(cfg.database_url)
    check_db_env(engine, cfg.env)
    return Ctx(engine=engine, hmac_key=cfg.audit_hmac_key, env=cfg.env,
               allow_illustrative=cfg.allow_illustrative), cfg


try:
    ctx, cfg = get_runtime()
except (ConfigError, EnvironmentMismatch) as err:
    st.error(f"لا يمكن تشغيل التطبيق: {err}")
    st.stop()

try:
    summary = status_summary(ctx)
except Exception:  # noqa: BLE001 — لا نوقف الواجهة بسبب شريط معلومات
    summary = {"synthetic": False, "ruleset": None, "kind": None, "policies": []}

session: Session | None = st.session_state.get("session")

# ---------------------------------------------------------------- الدخول
if session is None:
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(f'<div class="hc-login-hero">{logo(56)}<h1>Health Care</h1>'
                    f'<p>نظام سلامة استخدام الأدوية · المستشفى الافتراضي</p></div>', unsafe_allow_html=True)
        env_banner(cfg.env, summary["synthetic"], summary["kind"])
        with st.form("login"):
            st.markdown("**تسجيل الدخول**")
            username = st.text_input("اسم المستخدم")
            password = st.text_input("كلمة السر", type="password")
            if st.form_submit_button("دخول", type="primary", icon=":material/login:", width="stretch"):
                try:
                    st.session_state["session"] = login(ctx, username, password)
                    st.rerun()
                except (DomainError, OperationFailed) as err:
                    show_error(err)
        st.caption("الحسابات يُنشئها فريق المشروع من خارج التطبيق؛ لا يوجد تسجيل ذاتي.")
        disclaimer()
    st.stop()

# ---------------------------------------------------------------- الإطار
module = ROLE_PAGES[session.role]
with st.sidebar:
    st.markdown(f'<div class="hc-brand">{LOGO}<div><b>Health Care</b><small>سلامة استخدام الأدوية</small></div></div>'
                f'<div class="hc-user"><div class="hc-avatar">{e(initials(session.full_name))}</div><div>'
                f'<div class="n">{e(session.full_name)}</div><div class="r">{e(ROLES[session.role])}</div></div></div>'
                f'<div class="hc-navlabel">القائمة</div>', unsafe_allow_html=True)
    page = st.radio("القسم", module.PAGES, key=f"nav_{session.role}", label_visibility="collapsed")
    st.divider()
    if summary["ruleset"]:
        kind_ar = {"test_fixture": " (وهمية للاختبار)", "illustrative": " (توضيحية — غير معتمدة)"}
        st.caption(f"مجموعة القواعد الفعّالة: إصدار {summary['ruleset']}" + kind_ar.get(summary["kind"], ""))
    else:
        st.caption("لم تُحمَّل مجموعة قواعد بعد.")
    st.caption(f"البيئة: {cfg.env} · التوقيت: {cfg.display_tz}")
    if st.button("تسجيل الخروج", icon=":material/logout:", width="stretch"):
        try:
            logout(ctx, session)
        except (DomainError, OperationFailed):
            pass
        st.session_state.clear()
        st.rerun()

env_banner(cfg.env, summary["synthetic"], summary["kind"])
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"), icon=":material/check_circle:")

module.render(UI(ctx=ctx, cfg=cfg, session=session), page)
disclaimer()
