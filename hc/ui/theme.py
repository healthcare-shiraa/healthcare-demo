"""نظام التصميم: الألوان، الأنماط، والمكونات المرئية المشتركة.

مبادئ مأخوذة من إرشادات قابلية استخدام السجلات الصحية الإلكترونية:
- شريط تعريف المريض ثابت في أعلى كل شاشة سريرية، والحساسية فيه بارزة.
- التنبيهات مرتبة حسب الخطورة، وتذكر العنصر المسبب والإجراء المطلوب.
- اللون لا يحمل المعنى وحده: كل حالة لها نص وأيقونة.
كل النصوص القادمة من البيانات تُهرَّب (html.escape) قبل إدراجها.
"""
from __future__ import annotations

import html

import streamlit as st

TONES = {
    "critical": ("#B42318", "#FEF3F2", "#FDA29B"),
    "warning": ("#B54708", "#FFFAEB", "#FEC84B"),
    "success": ("#067647", "#ECFDF3", "#75E0A7"),
    "info": ("#175CD3", "#EFF8FF", "#84CAFF"),
    "neutral": ("#344054", "#F2F4F7", "#D0D5DD"),
    "brand": ("#0E6E74", "#E6F4F4", "#7CC4C2"),
}

ICONS = {  # أيقونات SVG بسيطة (رسم أصلي)
    "alert": '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".6"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r=".6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 5-6 8-6s6.5 2 8 6"/>',
    "pill": '<rect x="3" y="8" width="18" height="8" rx="4" transform="rotate(-35 12 12)"/><path d="m9 9 6 6" transform="rotate(0)"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "shield": '<path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6l-8-3Z"/>',
    "block": '<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>',
    "flask": '<path d="M9 3h6M10 3v6L4 19a1.5 1.5 0 0 0 1.3 2h13.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/>',
}


def icon(name: str, size: int = 18, color: str = "currentColor") -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{ICONS[name]}</svg>')


def logo(size: int = 34) -> str:
    return LOGO.replace('width="34" height="34"', f'width="{size}" height="{size}"', 1)


LOGO = ('<svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">'
        '<rect width="34" height="34" rx="9" fill="#5CC8C2"/>'
        '<path d="M14 7h6v7h7v6h-7v7h-6v-7H7v-6h7z" fill="#0F2A3A"/>'
        '<path d="M5 24h6l2-3 3 6 3-9 2 6h8" fill="none" stroke="#FFFFFF" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round" opacity=".9"/></svg>')

CSS = """
<style>
:root { --ink:#0F1B2D; --muted:#5B6B7F; --line:#E2E8F0; --bg:#F4F6F9; --brand:#0E6E74; }
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], .stMarkdown, .stRadio,
.stTextInput, .stSelectbox, .stNumberInput, .stDateInput, .stTimeInput, .stTextArea, .stMultiSelect,
.stCheckbox { direction: rtl; text-align: right; }
[data-testid="stMarkdownContainer"] { text-align: right; }
input, textarea { direction: rtl; text-align: right; }
/* الأرقام والأوقات والتواريخ تُقرأ من اليسار لليمين حتى لا تنعكس (17:53 لا 53:17) */
[data-testid="stTimeInput"] > div:not([data-testid="stWidgetLabel"]), [data-testid="stDateInput"] > div:not([data-testid="stWidgetLabel"]),
[data-testid="stTimeInputTimeDisplay"], [data-testid="stNumberInput"] input { direction: ltr; }
[data-testid="stHeader"] { background: transparent; height: 0; }
footer, [data-testid="stStatusWidget"], [data-testid="stDecoration"] { display: none !important; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px; }

/* الشريط الجانبي */
[data-testid="stSidebar"] .stRadio > div { gap: 2px; }
[data-testid="stSidebar"] .stRadio label { width: 100%; padding: 9px 12px; border-radius: 8px; margin: 0;
  transition: background .15s; cursor: pointer; }
[data-testid="stSidebar"] .stRadio label:hover { background: rgba(255,255,255,.06); }
[data-testid="stSidebar"] .stRadio label:has(input:checked) { background: #16384C; box-shadow: inset -3px 0 0 #5CC8C2; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child { display: none; }
[data-testid="stToolbar"], [data-testid="stMainMenu"] { display: none !important; }
[data-testid="stSidebar"] hr { border-color: #1F4A62; }

.hc-brand { display:flex; align-items:center; gap:10px; margin: 4px 0 18px; }
.hc-brand b { font-size: 18px; color:#fff; letter-spacing:.2px; }
.hc-brand small { display:block; color:#9DB7C6; font-size:12px; }
.hc-user { display:flex; gap:10px; align-items:center; background:#16384C; border:1px solid #1F4A62;
  padding:10px 12px; border-radius:10px; margin-bottom:14px; }
.hc-avatar { width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-weight:700; background:#5CC8C2; color:#0F2A3A; flex: 0 0 36px; }
.hc-user .n { color:#fff; font-weight:600; font-size:14px; line-height:1.3; }
.hc-user .r { color:#9DB7C6; font-size:12px; }
.hc-navlabel { color:#7FA0B3; font-size:11px; font-weight:600; letter-spacing:.6px; margin:6px 4px; }

/* العناوين والبطاقات */
.hc-page { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; margin-bottom: 14px; }
.hc-page h1 { font-size: 24px; margin:0; color:var(--ink); font-weight:700; }
.hc-page p { margin:4px 0 0; color:var(--muted); font-size:14px; }
.hc-card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin-bottom:12px; }
.hc-card h3 { font-size:16px; margin:0 0 10px; color:var(--ink); display:flex; align-items:center; gap:8px; }
.hc-section { font-size:15px; font-weight:700; color:var(--ink); margin: 18px 0 8px; display:flex; gap:8px; align-items:center; }
.hc-kv { display:grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px 18px; }
.hc-kv div span { display:block; color:var(--muted); font-size:12px; }
.hc-kv div b { color:var(--ink); font-size:14.5px; font-weight:600; }
.hc-muted { color: var(--muted); font-size: 13px; }

.hc-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom: 14px; }
.hc-kpi { background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px; position:relative; overflow:hidden; }
.hc-kpi:before { content:""; position:absolute; inset-inline-start:0; top:0; bottom:0; width:4px; background: var(--accent); }
.hc-kpi .v { font-size:28px; font-weight:700; color:var(--ink); line-height:1.1; }
.hc-kpi .l { color:var(--muted); font-size:13px; margin-top:4px; }

/* الشارات */
.hc-chip { display:inline-flex; align-items:center; gap:5px; padding:3px 10px; border-radius:999px; font-size:12.5px;
  font-weight:600; border:1px solid; white-space:nowrap; }

/* شريط المريض */
.hc-banner { display:flex; flex-wrap:wrap; align-items:center; gap:14px 22px; background:#fff; border:1px solid var(--line);
  border-inline-start:5px solid var(--brand); border-radius:12px; padding:12px 16px; margin-bottom:14px; }
.hc-banner .who { display:flex; gap:12px; align-items:center; min-width: 220px; }
.hc-banner .who .nm { font-size:17px; font-weight:700; color:var(--ink); }
.hc-banner .meta { display:flex; gap:18px; color:var(--muted); font-size:13px; }
.hc-banner .meta b { color:var(--ink); font-weight:600; margin-inline-start:4px; }
.hc-banner .alg { margin-inline-start:auto; }

/* التنبيهات */
.hc-alert { border:1px solid var(--bd); background: var(--bg2); border-inline-start: 5px solid var(--fg);
  border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
.hc-alert .hd { display:flex; gap:8px; align-items:center; color: var(--fg); font-weight:700; font-size:14.5px; flex-wrap:wrap; }
.hc-alert .bd { color: var(--ink); margin-top: 6px; font-size:14px; }
.hc-alert .ft { color: var(--muted); margin-top: 6px; font-size:12.5px; }

.hc-env { display:flex; gap:10px; align-items:center; background:#FFFAEB; border:1px solid #FEC84B; color:#93370D;
  padding:8px 14px; border-radius:10px; font-size:13.5px; margin-bottom: 12px; font-weight:500; }
.hc-disclaimer { color:#5B6B7F; font-size:12px; text-align:center; margin-top: 26px; }

/* الجدول الزمني للجرعات */
.hc-doses { display:flex; flex-wrap:wrap; gap:8px; }
.hc-dose { border:1px solid var(--bd); background: var(--bg2); color: var(--fg); border-radius:10px; padding:8px 10px;
  min-width: 128px; font-size:12.5px; }
.hc-dose b { display:block; font-size:13.5px; color: var(--ink); }

/* شاشة الدخول */
.hc-login-hero { text-align:center; margin: 4vh 0 18px; }
.hc-login-hero h1 { font-size: 26px; margin: 10px 0 2px; color: var(--ink); }
.hc-login-hero p { color: var(--muted); margin: 0; }

div[data-testid="stForm"] { background:#fff; border:1px solid var(--line); border-radius:12px; padding: 18px 18px 8px; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { font-weight:600; }
[data-testid="stExpander"] details { background:#fff; border-radius:10px; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def chip(text_: str, tone: str = "neutral", ic: str | None = None) -> str:
    fg, bg, bd = TONES[tone]
    i = icon(ic, 14, fg) if ic else ""
    return f'<span class="hc-chip" style="color:{fg};background:{bg};border-color:{bd}">{i}{e(text_)}</span>'


def page_header(title: str, subtitle: str = "", right_html: str = "") -> None:
    st.markdown(f'<div class="hc-page"><div><h1>{e(title)}</h1>'
                f'{"<p>" + e(subtitle) + "</p>" if subtitle else ""}</div><div>{right_html}</div></div>',
                unsafe_allow_html=True)


def section(title: str, ic: str | None = None) -> None:
    st.markdown(f'<div class="hc-section">{icon(ic, 18, "#0E6E74") if ic else ""}{e(title)}</div>',
                unsafe_allow_html=True)


def kpis(items: list[tuple[str, object, str]]) -> None:
    """items: (التسمية، القيمة، النغمة)"""
    cells = "".join(f'<div class="hc-kpi" style="--accent:{TONES[t][0]}"><div class="v">{e(v)}</div>'
                    f'<div class="l">{e(lbl)}</div></div>' for lbl, v, t in items)
    st.markdown(f'<div class="hc-kpis">{cells}</div>', unsafe_allow_html=True)


def kv(items: list[tuple[str, object]]) -> str:
    return '<div class="hc-kv">' + "".join(f"<div><span>{e(k)}</span><b>{e(v)}</b></div>" for k, v in items) + "</div>"


def card(title: str, body_html: str, ic: str | None = None) -> None:
    st.markdown(f'<div class="hc-card"><h3>{icon(ic, 18, "#0E6E74") if ic else ""}{e(title)}</h3>{body_html}</div>',
                unsafe_allow_html=True)


def initials(name: str) -> str:
    letters = [next((ch for ch in part if ch.isalpha()), "") for part in (name or "").split()]
    letters = [x for x in letters if x]
    return "".join(letters[:2]) or "؟"


ALLERGY_LABEL = {"not_recorded": "لم تُسجَّل بيانات الحساسية", "none_known": "لا توجد حساسية معروفة"}


def allergy_chip(status: str, allergies: list[str] | None = None) -> str:
    if status == "has_allergies":
        return chip("حساسية: " + "، ".join(allergies or []), "critical", "alert")
    if status == "none_known":
        return chip(ALLERGY_LABEL[status], "success", "check")
    return chip(ALLERGY_LABEL["not_recorded"], "warning", "alert")


def patient_banner(p: dict, allergies: list[str] | None = None) -> None:
    st.markdown(
        f'<div class="hc-banner"><div class="who"><div class="hc-avatar" style="background:#E6F4F4;color:#0E6E74">'
        f'{e(initials(p["full_name"]))}</div><div><div class="nm">{e(p["full_name"])}</div>'
        f'<div class="hc-muted">مريض بالغ · بيانات اصطناعية</div></div></div>'
        f'<div class="meta"><span>رقم المريض<b>{e(p["mrn"])}</b></span><span>العمر<b>{e(p["age"])}</b></span></div>'
        f'<div class="alg">{allergy_chip(p["allergy_status"], allergies)}</div></div>',
        unsafe_allow_html=True)


def alert_box(tone: str, title: str, body: str = "", foot: str = "", ic: str = "alert") -> None:
    fg, bg, bd = TONES[tone]
    st.markdown(f'<div class="hc-alert" style="--fg:{fg};--bg2:{bg};--bd:{bd}"><div class="hd">{icon(ic, 18, fg)}'
                f'{e(title)}</div>{"<div class=bd>" + e(body) + "</div>" if body else ""}'
                f'{"<div class=ft>" + e(foot) + "</div>" if foot else ""}</div>', unsafe_allow_html=True)


ILLUSTRATIVE_WARNING = ("نسخة عرض توضيحية — القواعد والأدوية والإعدادات تجريبية وغير معتمدة سريريًا، "
                        "والبيانات اصطناعية فقط. لا يُستخدم هذا الموقع لاتخاذ أي قرار علاجي حقيقي.")


def env_banner(env: str, synthetic: bool, kind: str | None = None) -> None:
    if kind == "illustrative" or (env == "demo" and synthetic):
        st.markdown(f'<div class="hc-env" style="background:#FEF3F2;border-color:#FDA29B;color:#912018">'
                    f'{icon("alert", 18, "#B42318")}{ILLUSTRATIVE_WARNING}</div>', unsafe_allow_html=True)
    elif env == "test" or synthetic:
        st.markdown(f'<div class="hc-env">{icon("flask", 18, "#B54708")}بيئة اختبار — القواعد والأدوية والإعدادات '
                    f'الحالية وهمية لاختبار آليات النظام، وليست معتمدة سريريًا.</div>', unsafe_allow_html=True)
    elif env == "demo":
        st.markdown(f'<div class="hc-env">{icon("info", 18, "#B54708")}نموذج أولي تعليمي — بيانات اصطناعية فقط، '
                    f'ولا يُستخدم لاتخاذ قرارات علاجية حقيقية.</div>', unsafe_allow_html=True)


def disclaimer() -> None:
    st.markdown('<div class="hc-disclaimer">نموذج أولي تعليمي · بيانات اصطناعية فقط · ليس نظامًا سريريًا معتمدًا · '
                'لا يستخدم الذكاء الاصطناعي في أي قرار</div>', unsafe_allow_html=True)


def empty(text_: str) -> None:
    st.markdown(f'<div class="hc-card" style="text-align:center;color:#5B6B7F">{icon("info", 22, "#98A2B3")}'
                f'<div style="margin-top:6px">{e(text_)}</div></div>', unsafe_allow_html=True)
