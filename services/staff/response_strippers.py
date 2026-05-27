"""Per-endpoint response strippers — reduce LLM token cost by trimming raw API
JSON to just the fields the model actually needs.

Each endpoint maps to a strip function that returns a minimal subset of fields.
Endpoints without a specific mapping fall through to a generic depth-3 truncator.

"""
import re
import sys


def _walk_data(raw):
    """Unwrap common API response envelopes (e.g. {"data": {...}})."""
    if not isinstance(raw, dict):
        return raw
    for key in ("data", "result", "body", "payload", "response"):
        inner = raw.get(key)
        if inner is not None:
            return inner
    return raw


def _find_records_list(node, depth=0, max_depth=6):
    """Deep-search a response for the first list-of-dicts (the actual records).

    Looks for the records list at any depth — handles {data: {data: {list: [...]}}},
    {data: {pagination: {records: [...]}}}, raw list responses, etc.
    Returns the first non-empty list of dicts found, or [] if none.
    """
    if depth > max_depth:
        return []
    if isinstance(node, list) and node and isinstance(node[0], dict):
        return node
    if isinstance(node, dict):
        # Prefer well-known keys first (faster + more reliable)
        priority_keys = ["clients", "items", "rows", "list", "records", "shifts",
                         "staff", "members", "supportWorkers", "results", "docs",
                         "users", "entries", "data"]
        for key in priority_keys:
            if key in node:
                found = _find_records_list(node[key], depth + 1, max_depth)
                if found:
                    return found
        # Fallback: explore all keys
        for key, value in node.items():
            if key in priority_keys:
                continue  # already tried
            found = _find_records_list(value, depth + 1, max_depth)
            if found:
                return found
    return []


def _find_total(node, depth=0, max_depth=6):
    """Deep-search for a total/count field at any depth."""
    if depth > max_depth:
        return None
    if isinstance(node, dict):
        for key in ("total", "totalCount", "totalRecords", "count", "totalItems"):
            v = node.get(key)
            if isinstance(v, (int, float)) and v >= 0:
                return int(v)
        for value in node.values():
            found = _find_total(value, depth + 1, max_depth)
            if found is not None:
                return found
    return None


def _full_name(record):
    if not isinstance(record, dict):
        return ""
    name = record.get("name") or record.get("fullName") or record.get("full_name")
    if name:
        return name
    first = record.get("firstName") or record.get("first_name") or ""
    last = record.get("lastName") or record.get("last_name") or ""
    return f"{first} {last}".strip()


def _count_by(records, field_options):
    """Count records by one of several possible field names."""
    if isinstance(field_options, str):
        field_options = [field_options]
    counts = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        val = None
        for f in field_options:
            if r.get(f):
                val = r[f]
                break
        val = val or "unknown"
        counts[val] = counts.get(val, 0) + 1
    return counts


def _addr_short(addr):
    """Compact address representation."""
    if not isinstance(addr, dict):
        return addr
    parts = [addr.get("suburb"), addr.get("state"), addr.get("postcode")]
    return ", ".join([p for p in parts if p])


# ---- Per-endpoint strippers ----

def strip_client_list(raw):
    """Strip client list endpoints — keep id, name, status, NDIS, suburb."""
    # Deep-search for the records list (handles any nesting depth)
    clients = _find_records_list(raw)
    total = _find_total(raw) or len(clients)
    page = 1
    total_pages = None
    if isinstance(raw, dict):
        for k in ("page", "currentPage", "pageNumber"):
            if isinstance(raw.get(k), (int, float)):
                page = int(raw[k])
                break
            # Also look inside data/result/body
            inner = raw.get("data") or raw.get("result") or {}
            if isinstance(inner, dict) and isinstance(inner.get(k), (int, float)):
                page = int(inner[k])
                break
        for k in ("totalPages", "pages", "lastPage"):
            if isinstance(raw.get(k), (int, float)):
                total_pages = int(raw[k])
                break

    return {
        "total": total,
        "showing": len(clients),
        "page": page,
        "total_pages": total_pages,
        "clients": [
            {
                "id": c.get("id") or c.get("_id") or c.get("clientId"),
                "name": _full_name(c),
                "ndis": c.get("ndisNumber") or c.get("ndis_number"),
                "status": c.get("status") or c.get("onboardingStatus") or c.get("clientStatus"),
                "gender": c.get("gender"),
                "suburb": _addr_short(c.get("address") or c.get("primaryAddress") or {}),
            }
            for c in clients if isinstance(c, dict)
        ],
        "status_breakdown": _count_by(clients, ["status", "onboardingStatus", "clientStatus"]),
    }


def _first_present(d, keys):
    """Return the first non-empty value among keys, else None."""
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def strip_client_search(raw):
    """Strip /organization/client/search — client-list shape plus the clinical
    dimensions a search typically filters on (diagnosis, mobility, medication),
    so the LLM can explain WHY each client matched without a follow-up fetch."""
    clients = _find_records_list(raw)
    total = _find_total(raw) or len(clients)
    page = 1
    total_pages = None
    if isinstance(raw, dict):
        for k in ("page", "currentPage", "pageNumber"):
            if isinstance(raw.get(k), (int, float)):
                page = int(raw[k])
                break
        for k in ("totalPages", "pages", "lastPage"):
            if isinstance(raw.get(k), (int, float)):
                total_pages = int(raw[k])
                break

    def _strip(c):
        med = c.get("medicalProfile") or c.get("medical_profile") or {}
        if not isinstance(med, dict):
            med = {}
        return {
            "id": c.get("id") or c.get("_id") or c.get("clientId"),
            "name": _full_name(c),
            "ndis": c.get("ndisNumber") or c.get("ndis_number"),
            "status": c.get("status") or c.get("onboardingStatus") or c.get("clientStatus"),
            "gender": c.get("gender"),
            "suburb": _addr_short(c.get("address") or c.get("primaryAddress") or {}),
            "diagnosis": _first_present(c, ["primaryDiagnosis", "diagnosis"])
            or _first_present(med, ["primaryDiagnosis", "diagnosis"]),
            "mobility": _first_present(c, ["mobility", "mobilityType", "mobilityStatus"])
            or _first_present(med, ["mobilityStatus", "mobility"]),
            "medications": _first_present(c, ["medications", "medication", "currentMedications"])
            or _first_present(med, ["medications", "medication"]),
        }

    return {
        "total": total,
        "showing": len(clients),
        "page": page,
        "total_pages": total_pages,
        "clients": [_strip(c) for c in clients if isinstance(c, dict)],
        "status_breakdown": _count_by(clients, ["status", "onboardingStatus", "clientStatus"]),
    }


def strip_staff_list(raw):
    """Strip staff list endpoints — keep id, name, role, member_type, status."""
    staff = _find_records_list(raw)
    total = _find_total(raw) or len(staff)

    return {
        "total": total,
        "showing": len(staff),
        "staff": [
            {
                "id": s.get("id") or s.get("_id") or s.get("staffId"),
                "name": _full_name(s),
                "role": s.get("role") or s.get("designation") or s.get("position"),
                "member_type": s.get("memberType") or s.get("staffType") or s.get("type") or s.get("workerType"),
                "status": s.get("status") or s.get("memberStatus"),
                "email": s.get("email") or s.get("emailAddress"),
            }
            for s in staff if isinstance(s, dict)
        ],
        "by_member_type": _count_by(staff, ["memberType", "staffType", "workerType"]),
        "by_status": _count_by(staff, ["status", "memberStatus"]),
    }


def strip_shift_list(raw):
    """Strip shift list endpoints — keep id, title, type, status, time, location, client, staff."""
    shifts = _find_records_list(raw)
    total = _find_total(raw) or len(shifts)
    page = 1
    total_pages = None
    if isinstance(raw, dict):
        for k in ("page", "currentPage", "pageNumber"):
            if isinstance(raw.get(k), (int, float)):
                page = int(raw[k])
                break
        for k in ("totalPages", "pages", "lastPage"):
            if isinstance(raw.get(k), (int, float)):
                total_pages = int(raw[k])
                break

    def _strip_shift(s):
        loc = s.get("location") or {}
        if isinstance(loc, dict):
            loc_str = loc.get("address") or _addr_short(loc) or loc.get("name")
        else:
            loc_str = loc
        staff_names = []
        for x in (s.get("staff") or s.get("supportWorkers") or s.get("assignedStaff") or [])[:3]:
            n = _full_name(x) if isinstance(x, dict) else str(x)
            if n:
                staff_names.append(n)
        client = s.get("client") or s.get("participant") or {}
        client_name = _full_name(client) if isinstance(client, dict) else str(client)

        return {
            "id": s.get("id") or s.get("_id") or s.get("shiftId"),
            "title": s.get("title") or s.get("name") or s.get("shiftTitle"),
            "type": s.get("type") or s.get("shiftType") or s.get("serviceType") or s.get("category"),
            "status": s.get("status") or s.get("shiftStatus"),
            "start": s.get("startTime") or s.get("startDate") or s.get("from") or s.get("startAt"),
            "end": s.get("endTime") or s.get("endDate") or s.get("to") or s.get("endAt"),
            "location": loc_str,
            "client": client_name,
            "staff": staff_names,
        }

    return {
        "total": total,
        "showing": len(shifts),
        "page": page,
        "total_pages": total_pages,
        "shifts": [_strip_shift(s) for s in shifts if isinstance(s, dict)],
        "status_breakdown": _count_by(shifts, ["status", "shiftStatus"]),
        "type_breakdown": _count_by(shifts, ["type", "shiftType", "serviceType"]),
    }


def strip_client_detail(raw):
    """Strip single-client detail — keep core profile, drop heavy nested arrays."""
    data = _walk_data(raw)
    if not isinstance(data, dict):
        return raw

    KEEP_FIELDS = {
        "id", "_id", "clientId", "firstName", "lastName", "name", "fullName",
        "email", "emailAddress", "phone", "mobile", "phoneNumber",
        "ndisNumber", "ndis_number", "ndisRegistrationNumber",
        "dateOfBirth", "dob", "gender", "status", "onboardingStatus", "clientStatus",
        "primaryDiagnosis", "diagnosis", "mobility", "mobilityType",
        "address", "primaryAddress", "serviceAddress",
        "communicationPreference", "communicationStyle", "languages",
        "supportCoordinator", "planManagedBy", "planManager",
        "planStartDate", "planEndDate", "planStatus",
        "emergencyContact", "guardian", "guardians",
        "medications", "doctor", "gp",
    }

    stripped = {k: v for k, v in data.items() if k in KEEP_FIELDS}

    # Truncate any oversize list to 5 items
    for k, v in list(stripped.items()):
        if isinstance(v, list) and len(v) > 5:
            stripped[k] = v[:5] + [f"... {len(v) - 5} more (truncated)"]

    return stripped


def strip_staff_detail(raw):
    """Strip single-staff detail — similar approach to client detail."""
    data = _walk_data(raw)
    if not isinstance(data, dict):
        return raw

    KEEP_FIELDS = {
        "id", "_id", "staffId", "firstName", "lastName", "name", "fullName",
        "email", "emailAddress", "phone", "mobile",
        "role", "designation", "position",
        "memberType", "staffType", "workerType",
        "status", "memberStatus",
        "department", "qualifications", "certifications",
        "languages",
    }
    stripped = {k: v for k, v in data.items() if k in KEEP_FIELDS}
    for k, v in list(stripped.items()):
        if isinstance(v, list) and len(v) > 5:
            stripped[k] = v[:5] + [f"... {len(v) - 5} more (truncated)"]
    return stripped


def strip_support_workers_by_client(raw):
    """Strip /organization/support-worker/by-client/{clientId}."""
    data = _walk_data(raw)
    if isinstance(data, dict):
        mappings = data.get("supportWorkers") or data.get("mappings") or data.get("items") or []
        total = data.get("total") or len(mappings)
    else:
        mappings = data if isinstance(data, list) else []
        total = len(mappings)

    return {
        "total": total,
        "support_workers": [
            {
                "id": m.get("id") or m.get("_id") or m.get("supportWorkerId"),
                "name": _full_name(m.get("supportWorker") or m),
                "role": m.get("role") or (m.get("supportWorker") or {}).get("role"),
                "status": m.get("status"),
                "assigned_from": m.get("assignedFrom") or m.get("startDate"),
                "assigned_to": m.get("assignedTo") or m.get("endDate"),
            }
            for m in mappings if isinstance(m, dict)
        ],
    }


# ---- Generic fallback ----

def strip_generic(raw, max_depth=6, max_array_len=15, max_str_len=500):
    """Generic depth-limited truncator for unmapped endpoints."""
    def _walk(node, depth):
        if depth > max_depth:
            return "..."
        if isinstance(node, dict):
            return {k: _walk(v, depth + 1) for k, v in node.items()}
        if isinstance(node, list):
            if len(node) > max_array_len:
                head = [_walk(x, depth + 1) for x in node[:max_array_len]]
                return head + [f"... {len(node) - max_array_len} more (truncated)"]
            return [_walk(x, depth + 1) for x in node]
        if isinstance(node, str) and len(node) > max_str_len:
            return node[:max_str_len] + "…"
        return node
    return _walk(raw, 0)


# ---- Path → stripper dispatch ----
# Ordered: most-specific patterns first. Patterns use re.search (substring match).

STRIPPERS = [
    # Client lists
    (re.compile(r"/organization/client/list/all-clients$"), strip_client_list),
    (re.compile(r"/organization/client/my-clients$"), strip_client_list),
    (re.compile(r"/organization/client/list$"), strip_client_list),
    (re.compile(r"/organization/client/board-view$"), strip_client_list),
    (re.compile(r"/organization/client/search$"), strip_client_search),
    # Staff lists
    (re.compile(r"/organization/staff/get-all-staff-members$"), strip_staff_list),
    (re.compile(r"/organization-member/team/get-all-staff-members$"), strip_staff_list),
    (re.compile(r"/organization/shift/staff/support-worker$"), strip_staff_list),
    (re.compile(r"/organization/shift/staff/in-office$"), strip_staff_list),
    # Shift lists / calendar
    (re.compile(r"/organization-member/shift/list-view$"), strip_shift_list),
    (re.compile(r"/organization-member/shift/calendar-view$"), strip_shift_list),
    (re.compile(r"/organization-member/shift/ongoing-shifts$"), strip_shift_list),
    (re.compile(r"/organization/shift/list-view/type$"), strip_shift_list),
    (re.compile(r"/organization/shift/ongoing$"), strip_shift_list),
    (re.compile(r"/organization/shift/clients$"), strip_shift_list),
    (re.compile(r"/isw/shift/list-view$"), strip_shift_list),
    (re.compile(r"/isw/shift/ongoing-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/staff-shift/all-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/staff-shift/this-week-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/client-shift/all-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/client-shift/this-week-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/client-shift/calendar-view$"), strip_shift_list),
    (re.compile(r"/mobile/isw-shift/this-week-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/organization-member/my-ongoing-shifts$"), strip_shift_list),
    (re.compile(r"/mobile/client/my-ongoing-shifts$"), strip_shift_list),
    # Client details by ID
    (re.compile(r"/organization/client/get/[^/]+$"), strip_client_detail),
    (re.compile(r"/organization/support-coordinator/client/[^/]+$"), strip_client_detail),
    (re.compile(r"/mobile/support-coordinator/clients/[^/]+$"), strip_client_detail),
    (re.compile(r"/mobile/visitor/clients/[^/]+$"), strip_client_detail),
    (re.compile(r"/mobile/client/details$"), strip_client_detail),
    # Staff details
    (re.compile(r"/mobile/organization-member/details$"), strip_staff_detail),
    # Support worker mappings
    (re.compile(r"/organization/support-worker/by-client/[^/]+$"), strip_support_workers_by_client),
    (re.compile(r"/organization/support-coordinator/by-client/[^/]+$"), strip_support_workers_by_client),
]


def _looks_empty(stripped):
    """Heuristic: does the stripped output look suspiciously empty?

    Returns True if a "total" field was found but every list/dict is empty —
    which means the stripper located the response wrapper but missed the actual
    data inside it (wrong key path). True empties (real "zero records" replies)
    don't trigger this because they usually have total=0.
    """
    if not isinstance(stripped, dict):
        return False

    has_any_data = False
    has_positive_total = False
    total_is_zero = False

    for k, v in stripped.items():
        if isinstance(v, list) and len(v) > 0:
            has_any_data = True
        if k in ("total", "totalCount", "count", "showing") and isinstance(v, (int, float)):
            if v > 0:
                has_positive_total = True
            elif v == 0:
                total_is_zero = True
        if isinstance(v, dict) and v:
            has_any_data = True

    # Suspicious case: total claims there ARE records but we found none in the
    # stripped output → wrong data path. Falsely-empty stripper.
    # Legit zero case: total=0 with no records → leave it alone.
    if total_is_zero and not has_positive_total:
        return False  # Genuine empty response
    return has_positive_total and not has_any_data


def strip_api_response(api_path, raw_response, verbose=False):
    """Dispatch to the appropriate stripper. Falls back to generic depth-3 truncation.

    Sanity checks:
    1. Exception in stripper → fallback to generic
    2. Stripped output is suspiciously small (>95% reduction on substantial payload)
       → fallback to generic (likely missed the data path)
    3. Stripped output looks empty (totals present but lists empty) → fallback to generic
    """
    import json as _json

    if not isinstance(raw_response, dict) and not isinstance(raw_response, list):
        return raw_response
    if isinstance(raw_response, dict) and "error" in raw_response:
        return raw_response  # Pass errors through unchanged

    raw_size = len(_json.dumps(raw_response))

    for pattern, stripper in STRIPPERS:
        if pattern.search(api_path):
            try:
                stripped = stripper(raw_response)
                stripped_size = len(_json.dumps(stripped))

                # Sanity check: if stripped output looks empty (totals present but
                # lists empty), the stripper found the wrapper but missed the data.
                # Fall back to generic with bigger depth budget. If THAT also looks
                # empty, pass the raw response through (last resort — better to
                # send too much than nothing).
                if _looks_empty(stripped):
                    print(f"[response-stripper] {api_path}: stripped LOOKS EMPTY — trying generic depth-6", file=sys.stderr)
                    generic = strip_generic(raw_response)
                    generic_size = len(_json.dumps(generic))
                    if _looks_empty(generic) or generic_size < 200:
                        print(f"[response-stripper] {api_path}: generic also empty — passing RAW ({raw_size} bytes)", file=sys.stderr)
                        return raw_response  # Last resort — let LLM see everything
                    return generic

                # Sanity check: suspicious 95%+ reduction on a sizable payload
                # → try generic first (depth 6 captures most shapes), then raw
                if raw_size > 1000 and stripped_size < (raw_size * 0.03):
                    pct = int((1 - stripped_size / raw_size) * 100) if raw_size else 0
                    print(f"[response-stripper] {api_path}: SUSPICIOUS {pct}% reduction ({raw_size}→{stripped_size}) — trying generic depth-6", file=sys.stderr)
                    generic = strip_generic(raw_response)
                    generic_size = len(_json.dumps(generic))
                    if generic_size < 500 and raw_size > 5000:
                        print(f"[response-stripper] {api_path}: generic STILL too small ({generic_size}B) — passing RAW truncated to 30KB", file=sys.stderr)
                        # Truncate raw to ~30KB so we don't blow up the prompt
                        if raw_size > 30000:
                            return strip_generic(raw_response, max_depth=10, max_array_len=20)
                        return raw_response
                    return generic

                if verbose:
                    pct = int((1 - stripped_size / raw_size) * 100) if raw_size else 0
                    print(f"[response-stripper] {api_path}: {raw_size}→{stripped_size} bytes ({pct}% reduction)", file=sys.stderr)
                return stripped
            except Exception as e:
                print(f"[response-stripper] {api_path} stripper FAILED ({type(e).__name__}: {e}) — falling back to generic", file=sys.stderr)
                return strip_generic(raw_response)

    # No specific mapping → generic fallback
    return strip_generic(raw_response)
