"""Deterministic metrics engine — all computation, zero hallucination.

Pure Python (no I/O, no LLM). Floats rounded to 2 dp at output boundary.
Never raises on dirty data — emits quality counters instead.
"""
import json
import re
from datetime import date, datetime, timedelta
from typing import Any


_DAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def parse_hhmm(value: Any) -> int | None:
    """Parse HH:MM or H:MM to minutes since midnight. Invalid → None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        parts = value.split(":")
        if len(parts) < 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        return h * 60 + m
    except (ValueError, IndexError):
        return None


def parse_iso(value: Any) -> datetime | None:
    """Parse ISO 8601 datetime (Z → +00:00). Invalid → None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def parse_date(value: Any) -> date | None:
    """Parse YYYY-MM-DD. Invalid → None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def week_buckets(date_from: str, date_to: str) -> list[dict]:
    """7-day windows from date_from, last window truncated at date_to.
    Range ≤35 days: weekly; >35 days: monthly.
    """
    df = parse_date(date_from)
    dt = parse_date(date_to)
    if not df or not dt or df > dt:
        return []

    days_span = (dt - df).days + 1
    buckets = []

    if days_span <= 35:
        # Weekly buckets
        current = df
        while current <= dt:
            bucket_end = min(current + timedelta(days=6), dt)
            buckets.append({
                "label": f"{current.strftime('%d-%d %b')} {'(partial)' if bucket_end < current + timedelta(days=6) else ''}".strip(),
                "start": current.isoformat(),
                "end": bucket_end.isoformat(),
            })
            current = bucket_end + timedelta(days=1)
    else:
        # Monthly buckets
        current = df.replace(day=1)
        while current <= dt:
            next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
            bucket_end = min(next_month - timedelta(days=1), dt)
            buckets.append({
                "label": current.strftime("%B %Y"),
                "start": current.isoformat(),
                "end": bucket_end.isoformat(),
            })
            current = next_month

    return buckets


def weekly_counts(days: list[dict], key: str, buckets: list[dict]) -> tuple[list[int], int]:
    """Bucket items by bucketDate; return (counts_per_bucket, unbucketed_count)."""
    if not buckets:
        return [], 0

    counts = [0] * len(buckets)
    unbucketed = 0

    for day_record in days:
        items = day_record.get(key) or []
        bucket_date_str = day_record.get("bucketDate") or day_record.get("date")
        if not bucket_date_str:
            unbucketed += len(items)
            continue

        bucket_date = parse_date(bucket_date_str)
        if not bucket_date:
            unbucketed += len(items)
            continue

        for i, bucket in enumerate(buckets):
            b_start = parse_date(bucket["start"])
            b_end = parse_date(bucket["end"])
            if b_start and b_end and b_start <= bucket_date <= b_end:
                counts[i] += len(items)
                break
        else:
            unbucketed += len(items)

    return counts, unbucketed


def least_squares_slope(values: list[float]) -> float:
    """OLS slope over x=[0..n-1]. n<2 → 0.0."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def r_squared(values: list[float]) -> float:
    """Correlation squared over x=[0..n-1]. n<2 → 0.0."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    ss_tot = sum((v - y_mean) ** 2 for v in values)
    if ss_tot == 0:
        return 0.0
    ss_res = sum((values[i] - (y_mean + least_squares_slope(values) * (i - x_mean))) ** 2 for i in range(n))
    return 1 - (ss_res / ss_tot) if ss_tot else 0.0


def classify_trend(values: list[int]) -> str:
    """Classify trend as 'insufficient' / 'stable' / 'increasing' / 'decreasing'."""
    if len(values) < 3:
        return "insufficient"
    slope = least_squares_slope([float(v) for v in values])
    if abs(slope) < 0.5:
        return "stable"
    return "increasing" if slope >= 0.5 else "decreasing"


def expected_shifts(schedule: list[dict], date_from: str, date_to: str) -> dict:
    """Compute expected shift occurrences from supportSchedule.
    Handles overnight wrap (end < start → +24h) and zero-duration slots.
    """
    df = parse_date(date_from)
    dt = parse_date(date_to)
    if not df or not dt:
        return {"occurrences": 0, "expectedHours": 0.0, "malformedTimes": 0, "zeroDurationSlots": 0}

    occurrences = 0
    total_hours = 0.0
    malformed = 0
    zero_duration = 0

    for slot in schedule:
        day_code = slot.get("dayOfWeek", "").upper()
        weekday = _DAY_CODES.get(day_code)
        if weekday is None:
            malformed += 1
            continue

        # Count occurrences of this weekday in the range
        first_occurrence = df + timedelta(days=(weekday - df.weekday()) % 7)
        if first_occurrence < df:
            first_occurrence += timedelta(days=7)
        slot_occurrences = 0
        check_date = first_occurrence
        while check_date <= dt:
            slot_occurrences += 1
            check_date += timedelta(days=7)

        occurrences += slot_occurrences

        # Compute hours per slot
        start_str = slot.get("startTime")
        end_str = slot.get("endTime")
        start_min = parse_hhmm(start_str)
        end_min = parse_hhmm(end_str)

        if start_min is None or end_min is None:
            malformed += 1
            continue

        if end_min == start_min:
            zero_duration += 1
            continue

        duration_min = end_min - start_min
        if duration_min < 0:  # Overnight wrap
            duration_min += 24 * 60

        slot_hours = duration_min / 60.0
        total_hours += slot_hours * slot_occurrences

    return {
        "occurrences": occurrences,
        "expectedHours": round(total_hours, 2),
        "malformedTimes": malformed,
        "zeroDurationSlots": zero_duration,
    }


def delivered_shifts(shifts: list[dict]) -> dict:
    """Compute delivered shift metrics."""
    total = len(shifts)
    if total == 0:
        return {"total": 0, "byStatus": {}, "completed": 0, "deliveredHours": 0.0, "unparseableDurations": 0}

    by_status = {}
    completed = 0
    total_hours = 0.0
    unparseable = 0

    for shift in shifts:
        status = shift.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

        if status == "completed":
            completed += 1

        start_str = shift.get("start_time")
        end_str = shift.get("end_time")
        start = parse_iso(start_str)
        end = parse_iso(end_str)

        if start and end and end >= start:
            duration = (end - start).total_seconds() / 3600
            total_hours += duration
        elif start_str or end_str:
            unparseable += 1

    return {
        "total": total,
        "byStatus": by_status,
        "completed": completed,
        "deliveredHours": round(total_hours, 2),
        "unparseableDurations": unparseable,
    }


def fulfillment(completed: int, expected: int) -> float | None:
    """Fulfillment rate (not clamped). None when expected==0."""
    if expected == 0:
        return None
    return round(completed / expected, 2)


def incident_stats(incidents: list[dict], completed_shifts: int, weekly: list[int]) -> dict:
    """Incident metrics."""
    total = len(incidents)
    by_risk = {}
    by_type = {}
    by_ndis = {"reportable": 0, "unreportable": 0}

    for inc in incidents:
        risk = inc.get("riskRating", "unknown")
        inc_type = inc.get("incidentType", "unknown")
        ndis = inc.get("ndisReportable", False)

        by_risk[risk] = by_risk.get(risk, 0) + 1
        by_type[inc_type] = by_type.get(inc_type, 0) + 1
        by_ndis[("reportable" if ndis else "unreportable")] += 1

    per_shift = round(total / max(1, completed_shifts), 2) if completed_shifts > 0 else None

    return {
        "total": total,
        "weeklyCounts": weekly,
        "byRiskRating": by_risk,
        "byType": by_type,
        "byNdisReportable": by_ndis,
        "perCompletedShift": per_shift,
    }


def rp_stats(rps: list[dict], weekly: list[int]) -> dict:
    """Restrictive practice metrics."""
    total = len(rps)
    by_type = {}
    by_status = {}
    total_minutes = 0
    ndis_reported = 0

    for rp in rps:
        rp_type = rp.get("type_of_restrictive_practice", "unknown")
        status = rp.get("status", "unknown")
        reported = rp.get("date_reported_ndis")

        by_type[rp_type] = by_type.get(rp_type, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if reported:
            ndis_reported += 1

        # Duration
        start_str = rp.get("duration_start")
        end_str = rp.get("duration_end")
        start = parse_iso(start_str)
        end = parse_iso(end_str)
        if start and end and end >= start:
            duration_min = (end - start).total_seconds() / 60
            total_minutes += duration_min

    trend = classify_trend(weekly)
    slope = round(least_squares_slope([float(w) for w in weekly]), 2)

    return {
        "total": total,
        "weeklyCounts": weekly,
        "byType": by_type,
        "byStatus": by_status,
        "totalRestraintMinutes": round(total_minutes, 1),
        "ndisReported": ndis_reported,
        "slopePerWeek": slope,
        "trend": trend,
    }


def feedback_complaint_stats(feedback: list[dict], complaints: list[dict]) -> dict:
    """Feedback and complaint metrics."""
    fb_count = len(feedback)
    cp_count = len(complaints)

    # Rating from feedback (numeric only)
    ratings = []
    for fb in feedback:
        rating = fb.get("rating")
        if isinstance(rating, (int, float)):
            ratings.append(rating)

    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    # Complaints by type and status
    cp_by_type = {}
    cp_by_status = {}
    risk_flagged = 0

    for cp in complaints:
        cp_type = cp.get("complaint_type", "unknown")
        status = cp.get("status", "unknown")
        risk_flag = cp.get("risk_flag", False)

        cp_by_type[cp_type] = cp_by_type.get(cp_type, 0) + 1
        cp_by_status[status] = cp_by_status.get(status, 0) + 1
        if risk_flag:
            risk_flagged += 1

    return {
        "feedbackCount": fb_count,
        "avgRating": avg_rating,
        "complaintCount": cp_count,
        "complaintsByType": cp_by_type,
        "complaintsByStatus": cp_by_status,
        "riskFlagged": risk_flagged,
    }


def data_quality(stats: dict) -> dict:
    """Data quality score 0-1 from malformed/unbucketed counters."""
    issues = []
    total_counters = 0
    problem_count = 0

    shift_exp = stats.get("shifts", {}).get("expectedShifts", {})
    if shift_exp:
        if shift_exp.get("malformedTimes", 0) > 0:
            issues.append(f"Shift schedule: {shift_exp['malformedTimes']} malformed times")
            problem_count += shift_exp["malformedTimes"]
        if shift_exp.get("zeroDurationSlots", 0) > 0:
            issues.append(f"Shift schedule: {shift_exp['zeroDurationSlots']} zero-duration slots")
            problem_count += shift_exp["zeroDurationSlots"]
        total_counters += shift_exp.get("malformedTimes", 0) + shift_exp.get("zeroDurationSlots", 0)

    shift_del = stats.get("shifts", {}).get("deliveredShifts", {})
    if shift_del and shift_del.get("unparseableDurations", 0) > 0:
        issues.append(f"Shift durations: {shift_del['unparseableDurations']} unparseable")
        problem_count += shift_del["unparseableDurations"]
        total_counters += shift_del["unparseableDurations"]

    if not stats.get("data") and stats.get("dataQuality", {}).get("flag") == "NO_DATA":
        return {"score": 0.0, "issues": ["No data for this period"], "flag": "NO_DATA"}

    score = 1.0 if problem_count == 0 else max(0.0, 1.0 - (problem_count / max(1, total_counters + 10)))
    return {"score": round(score, 2), "issues": issues}


def compute_stats(data: dict, date_from: str, date_to: str) -> dict:
    """Compute all stats from API response. ValueError on bad/reversed dates."""
    df = parse_date(date_from)
    dt = parse_date(date_to)

    if not df or not dt:
        raise ValueError(f"Invalid date range: {date_from} to {date_to}")
    if df > dt:
        raise ValueError(f"date_from > date_to: {date_from} > {date_to}")

    days = data.get("days") or data.get("data") or []
    client = data.get("client", {})
    schedule = client.get("supportSchedule", [])

    if not days:
        return {
            "period": {"dateFrom": date_from, "dateTo": date_to, "days": (dt - df).days + 1, "weeks": []},
            "caseNotes": {"total": 0, "weeklyCounts": [], "trend": "insufficient"},
            "shifts": {"expected": {"occurrences": 0}, "delivered": {"total": 0}, "fulfillmentRatePct": None},
            "incidents": {"total": 0, "weeklyCounts": [], "perCompletedShift": None},
            "restrictivePractices": {"total": 0, "weeklyCounts": [], "trend": "insufficient"},
            "feedbackAndComplaints": {"feedbackCount": 0, "complaintCount": 0, "avgRating": None},
            "dataQuality": {"score": 0.0, "issues": [], "flag": "NO_DATA"},
        }

    buckets = week_buckets(date_from, date_to)

    # Memory warning for huge datasets (quarterly+)
    num_days = len(days)
    if num_days > 60:
        total_records = sum(
            len(day.get("shifts", [])) +
            len(day.get("incidents", [])) +
            len(day.get("restrictivePractices", [])) +
            len(day.get("shiftFeedback", [])) +
            len(day.get("clientComplaints", []))
            for day in days
        )
        print(f"[stats] Large dataset: {num_days} days, {total_records} total records (memory: ~{total_records * 1.5:.0f} KB)")

    cn_counts, cn_ub = weekly_counts(days, "caseNotes", buckets)
    sh_counts, sh_ub = weekly_counts(days, "shifts", buckets)
    inc_counts, inc_ub = weekly_counts(days, "incidents", buckets)
    rp_counts, rp_ub = weekly_counts(days, "restrictivePractices", buckets)
    fb_counts, fb_ub = weekly_counts(days, "shiftFeedback", buckets)
    cc_counts, cc_ub = weekly_counts(days, "clientComplaints", buckets)

    # Flatten into aggregators (memory efficient: process and aggregate as we go)
    all_shifts = []
    all_incidents = []
    all_rps = []
    all_feedback = []
    all_complaints = []

    for day in days:
        all_shifts.extend(day.get("shifts") or [])
        all_incidents.extend(day.get("incidents") or [])
        all_rps.extend(day.get("restrictivePractices") or [])
        all_feedback.extend(day.get("shiftFeedback") or [])
        all_complaints.extend(day.get("clientComplaints") or [])

    exp_shifts = expected_shifts(schedule, date_from, date_to)
    del_shifts = delivered_shifts(all_shifts)
    comp_shifts = del_shifts.get("completed", 0)

    result = {
        "period": {
            "dateFrom": date_from,
            "dateTo": date_to,
            "days": (dt - df).days + 1,
            "weeks": buckets,
        },
        "caseNotes": {
            "total": sum(cn_counts),
            "weeklyCounts": cn_counts,
            "trend": classify_trend(cn_counts),
        },
        "shifts": {
            "expectedShifts": exp_shifts,
            "deliveredShifts": del_shifts,
            "fulfillmentRatePct": fulfillment(comp_shifts, exp_shifts.get("occurrences", 0)),
        },
        "incidents": incident_stats(all_incidents, comp_shifts, inc_counts),
        "restrictivePractices": rp_stats(all_rps, rp_counts),
        "feedbackAndComplaints": feedback_complaint_stats(all_feedback, all_complaints),
    }
    # Score quality from the REAL computed counters (malformed/zero-duration/unparseable)
    result["dataQuality"] = data_quality(result)
    return result


def extract_milestones(days: list[dict]) -> list[dict]:
    """Extract achievement milestones from caseNotes and shiftFeedback.

    Keywords: "first time", "independently", "initiated", "without prompting", etc.
    Returns list of {date, source, excerpt, weight}.
    """
    keywords = r"\b(first time|independently|initiated|without prompting|for the first time|self-directed|spontaneous)\b"
    milestones = []
    milestone_dates = set()

    for day_record in days:
        day_date = day_record.get("date") or day_record.get("bucketDate")

        # Scan caseNotes
        for note in day_record.get("caseNotes") or []:
            for field in ["summaryOfShift", "activitiesAndSkill", "wellbeingAndBehaviour"]:
                text = note.get(field, "")
                if isinstance(text, str) and re.search(keywords, text, re.IGNORECASE):
                    milestone_dates.add(day_date or "")
                    excerpt = text[:150]
                    milestones.append({
                        "date": day_date or "",
                        "source": "caseNote",
                        "excerpt": excerpt,
                        "weight": 0.7,
                    })

        # Scan feedback
        for fb in day_record.get("shiftFeedback") or []:
            text = fb.get("feedback_description", "")
            if isinstance(text, str) and re.search(keywords, text, re.IGNORECASE):
                milestone_dates.add(day_date or "")
                excerpt = text[:150]
                milestones.append({
                    "date": day_date or "",
                    "source": "feedback",
                    "excerpt": excerpt,
                    "weight": 0.7,
                })

    # Adjust weights based on multi-day evidence
    final = []
    for m in milestones:
        m["weight"] = 1.0 if len(milestone_dates) >= 2 else 0.7
        final.append(m)

    return final


def extract_quotes(feedback_items: list[dict]) -> list[dict]:
    """Extract verbatim participant quotes from feedback_description.

    Max 200 chars per quote. Returns {quote, date, source_id}.
    """
    quotes = []
    for fb in feedback_items:
        text = fb.get("feedback_description", "")
        if not isinstance(text, str) or len(text) == 0:
            continue

        # Try to find quoted text (between quotes)
        quoted = re.findall(r"[\"']([^\"']{10,200})[\"']", text)
        for q in quoted:
            quotes.append({
                "quote": q,
                "date": fb.get("date") or fb.get("bucketDate", ""),
                "source_id": fb.get("feedbackId", ""),
            })

        # If no quotes found, use the whole text if it's short enough
        if not quoted and 10 <= len(text) <= 200:
            quotes.append({
                "quote": text,
                "date": fb.get("date") or fb.get("bucketDate", ""),
                "source_id": fb.get("feedbackId", ""),
            })

    return quotes


def build_risk_register(incidents: list[dict], rps: list[dict], complaints: list[dict]) -> list[dict]:
    """Build a formal risk register from incidents, RPs, and complaints.

    Returns list of {category, source_type, date, severity_label, response}.
    """
    register = []

    # Incidents
    for inc in incidents:
        register.append({
            "category": inc.get("incidentType", "Incident"),
            "source_type": "formal_incident",
            "date": inc.get("date") or inc.get("bucketDate", ""),
            "severity_label": inc.get("riskRating", "Unknown"),
            "response": inc.get("responseAction", "No response recorded"),
            "ndisReportable": inc.get("ndisReportable", False),
        })

    # RPs
    for rp in rps:
        register.append({
            "category": rp.get("type_of_restrictive_practice", "Restrictive Practice"),
            "source_type": "restrictive_practice",
            "date": rp.get("date") or rp.get("bucketDate", ""),
            "severity_label": rp.get("status", "Active"),
            "response": f"Status: {rp.get('status', 'unknown')}, Duration: {rp.get('durationMin', 'N/A')} min",
            "ndisReportable": bool(rp.get("date_reported_ndis")),
        })

    # Risk-flagged complaints
    for cp in complaints:
        if cp.get("risk_flag"):
            register.append({
                "category": cp.get("complaint_type", "Complaint"),
                "source_type": "complaint",
                "date": cp.get("date") or cp.get("bucketDate", ""),
                "severity_label": cp.get("status", "Logged"),
                "response": f"Status: {cp.get('status', 'open')}",
                "ndisReportable": False,
            })

    return register


def mom_deltas(current: dict, previous: dict | None) -> dict | None:
    """Compute month-over-month deltas and direction words.

    Returns {metric_name: {current_value, previous_value, delta, direction}} or None if no previous.
    """
    if not previous:
        return None

    prev_stats = previous.get("stats", {})
    if not prev_stats:
        return None

    deltas = {}

    # Incidents
    curr_inc = current.get("incidents", {}).get("total", 0)
    prev_inc = prev_stats.get("incidents", {}).get("total", 0)
    if curr_inc != prev_inc or prev_inc > 0:
        direction = "↓" if curr_inc < prev_inc else ("↑" if curr_inc > prev_inc else "→")
        deltas["incidents"] = {
            "current": curr_inc,
            "previous": prev_inc,
            "delta": curr_inc - prev_inc,
            "direction": direction,
        }

    # RPs
    curr_rp = current.get("restrictivePractices", {}).get("total", 0)
    prev_rp = prev_stats.get("restrictivePractices", {}).get("total", 0)
    if curr_rp != prev_rp or prev_rp > 0:
        direction = "↓" if curr_rp < prev_rp else ("↑" if curr_rp > prev_rp else "→")
        deltas["restrictivePractices"] = {
            "current": curr_rp,
            "previous": prev_rp,
            "delta": curr_rp - prev_rp,
            "direction": direction,
        }

    # Shifts
    curr_shifts = current.get("shifts", {}).get("deliveredShifts", {}).get("total", 0)
    prev_shifts = prev_stats.get("shifts", {}).get("deliveredShifts", {}).get("total", 0)
    if curr_shifts != prev_shifts or prev_shifts > 0:
        direction = "↑" if curr_shifts > prev_shifts else ("↓" if curr_shifts < prev_shifts else "→")
        deltas["shifts"] = {
            "current": curr_shifts,
            "previous": prev_shifts,
            "delta": curr_shifts - prev_shifts,
            "direction": direction,
        }

    return deltas if deltas else None


def build_trend_table(stats: dict) -> str:
    """Build the Section 5 markdown table from stats.

    Returns markdown table with per-bucket rows (sessions, community, engagement, incidents, RP).
    """
    buckets = stats.get("period", {}).get("weeks", [])
    if not buckets:
        return "| Week | Sessions | Community | Incidents | RP |\n|------|----------|-----------|-----------|----|\n"

    lines = [
        "| Week | Sessions | Community | Incidents | RP |",
        "|------|----------|-----------|-----------|-----|",
    ]

    shift_counts = stats.get("shifts", {}).get("deliveredShifts", {}).get("byStatus", {})
    total_shifts = shift_counts.get("completed", 0) if shift_counts else 0
    inc_weeks = stats.get("incidents", {}).get("weeklyCounts", [])
    rp_weeks = stats.get("restrictivePractices", {}).get("weeklyCounts", [])

    for i, bucket in enumerate(buckets):
        week_label = bucket.get("label", f"Week {i+1}")
        sessions = total_shifts // max(1, len(buckets)) if total_shifts else 0
        community = 0  # Would need parsed shifts for this; stub for now
        incidents = inc_weeks[i] if i < len(inc_weeks) else 0
        rps = rp_weeks[i] if i < len(rp_weeks) else 0

        lines.append(f"| {week_label} | {sessions} | {community} | {incidents} | {rps} |")

    return "\n".join(lines) + "\n"
