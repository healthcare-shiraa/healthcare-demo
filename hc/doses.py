"""حالة الجرعة تُحسب عند العرض ولا تُخزَّن (لا يوجد عمود حالة قابل للتعديل)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from .timefmt import parse_utc


def dose_rows(conn, rx_id: int) -> list[dict]:
    rows = conn.execute(text(
        "SELECT d.id, d.prescription_id, d.dose_number, d.scheduled_at, d.planned_dose,"
        " ad.id AS adm_id, ad.outcome, ad.actual_dose, ad.administered_at_reported, ad.documented_at,"
        " ad.reason_text, ad.late_reason, ad.warnings, ad.verified_patient_mrn,"
        " u.username AS nurse_username, u.full_name AS nurse_name, r.label AS not_given_reason,"
        " rf.id AS referral_id"
        " FROM scheduled_doses d LEFT JOIN administrations ad ON ad.scheduled_dose_id = d.id"
        " LEFT JOIN users u ON u.id = ad.nurse_id"
        " LEFT JOIN not_given_reasons r ON r.id = ad.not_given_reason_id"
        " LEFT JOIN referrals rf ON rf.administration_id = ad.id"
        " WHERE d.prescription_id = :x ORDER BY d.dose_number"), {"x": rx_id}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["warnings"] = json.loads(d["warnings"]) if d["warnings"] else []
        out.append(d)
    return out


def compute_status(dose: dict, *, stopped_at: str | None, window_minutes: int | None, now: datetime) -> str:
    if dose.get("adm_id"):
        return dose["outcome"]
    sched = parse_utc(dose["scheduled_at"])
    if stopped_at and sched > parse_utc(stopped_at):
        return "cancelled"
    if window_minutes is None:
        return "unknown"
    w = timedelta(minutes=window_minutes)
    if now < sched - w:
        return "upcoming"
    if now <= sched + w:
        return "due"
    return "missed"


def timing_flag(scheduled_at: str, administered_at: str, window_minutes: int) -> str:
    s, a, w = parse_utc(scheduled_at), parse_utc(administered_at), timedelta(minutes=window_minutes)
    if a < s - w:
        return "early"
    if a > s + w:
        return "late"
    return "on_time"


def is_late_documentation(scheduled_at: str, documented_at: str, window_minutes: int) -> bool:
    return parse_utc(documented_at) > parse_utc(scheduled_at) + timedelta(minutes=window_minutes)
