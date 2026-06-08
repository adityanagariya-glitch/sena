# bulk_reingest.py
# Re-ingests all existing documents with updated metadata (org_id + doc_type).
# Run from project root after FastAPI is running on port 8000.
#
# Usage:
#   python bulk_reingest.py

import requests
import json
import time

API_BASE    = "http://localhost:8000"
INTERNAL_API_KEY = ""   # leave empty if not configured

# Get superadmin token at startup
def _get_admin_token() -> str:
    r = requests.post(
        f"{API_BASE}/auth/login",
        json={"login_id": "ndis\\admin.super", "password": "Admin@9999"},
        timeout=10
    )
    r.raise_for_status()
    token = r.json().get("token")
    if not token:
        raise RuntimeError("Could not get superadmin token")
    print(f"Logged in as superadmin ✓\n")
    return token

def _make_headers(token: str) -> dict:
    h = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    if INTERNAL_API_KEY:
        h["x-api-key"] = INTERNAL_API_KEY
    return h

# ── Document manifest ─────────────────────────────────────────────────────────
# Format: (s3_key, org_id, doc_type)
# POL = policy, PROC = procedure, ndis = shared NDIS baseline

DOCUMENTS = [

    # ── NDIS baseline docs (shared, no org) ───────────────────────────────────
    ("sena/misty/orgs/ndis/Code_of_Conduct_Workers_Draft_May_2018.pdf",                              "ndis", "policy"),
    ("sena/misty/orgs/ndis/Complaints-policy-PDF.pdf",                                               "ndis", "policy"),
    ("sena/misty/orgs/ndis/Compliance and enforcement _ NDIS Quality and Safeguards Commission.pdf", "ndis", "policy"),
    ("sena/misty/orgs/ndis/NDIS Reportable Incidents Guide.pdf",                                     "ndis", "procedure"),
    ("sena/misty/orgs/ndis/PB Enquiries Feedback and Complaints Policy.pdf",                         "ndis", "policy"),
    ("sena/misty/orgs/ndis/Participant Safeguarding Policy.pdf",                                     "ndis", "policy"),
    ("sena/misty/orgs/ndis/Privacy _ NDIS Quality and Safeguards Commission.pdf",                   "ndis", "policy"),
    ("sena/misty/orgs/ndis/Understanding your Obligations to the NDIS Code of Conduct ? supporttoyou.pdf", "ndis", "policy"),
    ("sena/misty/orgs/ndis/complainthandlingguidelinesforproviders_0.pdf",                           "ndis", "procedure"),
    ("sena/misty/orgs/ndis/ndis-practice-standards-and-quality-indicators.pdf",                     "ndis", "policy"),

    # ── Horizons ──────────────────────────────────────────────────────────────
    ("sena/misty/orgs/org_horizons/horizons_POL101_rights_decisionmaking_behaviour.pdf",             "org_horizons", "policy"),
    ("sena/misty/orgs/org_horizons/horizons_POL102_workforce_safety_incidents.pdf",                  "org_horizons", "policy"),
    ("sena/misty/orgs/org_horizons/horizons_POL103_services_continuity_governance.pdf",              "org_horizons", "policy"),
    ("sena/misty/orgs/org_horizons/horizons_PROC201-203_emergency_SDM_disclosure.docx",              "org_horizons", "procedure"),
    ("sena/misty/orgs/org_horizons/horizons_PROC204-206_volunteer_transport_databreach.docx",        "org_horizons", "procedure"),
    ("sena/misty/orgs/org_horizons/horizons_PROC207-210_aggression_medication_exit_allowances.docx", "org_horizons", "procedure"),

    # ── Sunrise ───────────────────────────────────────────────────────────────
    ("sena/misty/orgs/org_sunrise/sunrise_POL-NDIS001_ndis_aligned_policy_framework.pdf",            "org_sunrise", "policy"),
    ("sena/misty/orgs/org_sunrise/sunrise_POL001_conduct_rights_professional_standards.pdf",         "org_sunrise", "policy"),
    ("sena/misty/orgs/org_sunrise/sunrise_POL002_participant_rights_empowerment_safeguarding.pdf",   "org_sunrise", "policy"),
    ("sena/misty/orgs/org_sunrise/sunrise_POL003_workforce_whs_service_delivery.pdf",               "org_sunrise", "policy"),
    ("sena/misty/orgs/org_sunrise/sunrise_PROC001-002_safety_hazards_restrictive_practices.docx",   "org_sunrise", "procedure"),
    ("sena/misty/orgs/org_sunrise/sunrise_PROC003-005_disclosures_nearmiss_conflict_cultural.docx", "org_sunrise", "procedure"),
    ("sena/misty/orgs/org_sunrise/sunrise_PROC006-009_workforce_worklogs_transfer_transition.docx", "org_sunrise", "procedure"),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def trigger_ingestion(s3_key: str, org_id: str, doc_type: str, headers: dict) -> dict:
    r = requests.post(
        f"{API_BASE}/admin/trigger_ingestion",
        headers=headers,
        json={
            "s3_key":   s3_key,
            "org_id":   org_id,
            "doc_type": doc_type
        },
        timeout=300   # 5 mins — ingestion can take a while
    )
    return r.status_code, r.json()


def main():
    token   = _get_admin_token()
    headers = _make_headers(token)

    print(f"Re-ingesting {len(DOCUMENTS)} documents with updated metadata\n")
    print(f"{'─' * 70}")

    passed = []
    failed = []

    for i, (s3_key, org_id, doc_type) in enumerate(DOCUMENTS, 1):
        filename = s3_key.split("/")[-1]
        print(f"\n[{i}/{len(DOCUMENTS)}] {filename}")
        print(f"  org_id:   {org_id}")
        print(f"  doc_type: {doc_type}")

        try:
            status_code, response = trigger_ingestion(s3_key, org_id, doc_type, headers)
            status = response.get("status")

            if status == "COMPLETE":
                print(f"  ✅ COMPLETE — job_id: {response.get('job_id')}")
                passed.append(filename)
            else:
                print(f"  ❌ FAILED — {response.get('reason', response)}")
                failed.append((filename, response.get("reason", "unknown")))

        except Exception as e:
            print(f"  ❌ ERROR — {e}")
            failed.append((filename, str(e)))

        # Small delay between jobs to avoid overwhelming Bedrock KB
        if i < len(DOCUMENTS):
            print(f"  Waiting 5s before next doc...")
            time.sleep(5)

    # Summary
    print(f"\n{'─' * 70}")
    print(f"✅ Passed: {len(passed)}/{len(DOCUMENTS)}")
    print(f"❌ Failed: {len(failed)}/{len(DOCUMENTS)}")

    if failed:
        print(f"\nFailed documents:")
        for filename, reason in failed:
            print(f"  ✗ {filename} — {reason}")


if __name__ == "__main__":
    main()