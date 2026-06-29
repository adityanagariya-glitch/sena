"""
ARCHIVED API ENDPOINTS — Not registered in active Swagger schema.

These endpoints are preserved in the codebase for future use but are currently
disabled. To re-enable them, uncomment their registrations in main.py.

FILES WHERE ARCHIVED ENDPOINTS LIVE:
  - api/routes.py        → Case Review endpoints
  - api/rp_routes.py     → Restrictive Practices endpoints
  - api/voice_routes.py  → Voice WebSocket endpoints

═════════════════════════════════════════════════════════════════════════════════

ARCHIVED ENDPOINTS IN api/routes.py:
────────────────────────────────────────────────────────────────────────────────

  Health
  ──────
  GET  /health/live
       Health check (always returns 'ok')

  GET  /health/ready
       Health readiness (DB check deferred)

  Case Review
  ───────────
  POST /v1/case-review/context
       Rolling case-note summary for the calling staff member + client
       Input: staff_id, client_id, limit
       Returns: summary_text, metadata, notes_included

  POST /v1/case-review/classify
       Classify paragraph into structured case-note fields
       Input: staff_id, client_id, raw_paragraph, attempt (1-2), confirmation_feedback
       Returns: classified_fields, confidence, reask_prompts, status
       Logic: Attempt 1 asks for confirmation if confidence < 0.75
              Attempt 2 saves with client_classify_id_{ddmmyyyy}

  POST /v1/case-review/review
       Analyse case note for risks and compliance flags
       Input: client_classify_id OR client_id
       Returns: risks, restrictive_practices, anomalies, improvements
       Wrapped with: client_review_id_{ddmmyyyy}

  Incident Management
  ───────────────────
  POST /v1/case-review/incident/detect
       Detect if case note describes a reportable incident
       Input: review_session_id
       Returns: incident_detected, incident_draft_id, markers

  POST /v1/case-review/incident/draft
       Autofill NDIS incident report fields from case note
       Input: review_session_id
       Returns: incident_draft_id, draft_fields, status

  PATCH /v1/case-review/incident/{incident_id}/confirm
       Staff confirms AI-drafted incident report
       Input: incident_id
       Returns: status='confirmed'

  Submission
  ──────────
  POST /v1/case-review/submit
       Final submit gate for reviewed case note
       Input: review_session_id, actor_user_id
       Returns: status, submitted_at

═════════════════════════════════════════════════════════════════════════════════

ARCHIVED ENDPOINTS IN api/rp_routes.py:
────────────────────────────────────────────────────────────────────────────────

  Restrictive Practices
  ─────────────────────
  POST /v1/restrictive-practices/evaluate
       Evaluate case note via RSA signature auth (full pipeline)
       Auth: RSA signature (X-Signature header)
       Input: case_note_id, client_id, worker_id, transcript
       Returns: verdict, detected_practice, authorisation, reporting_obligations
       Cache: 24h by transcript hash

  POST /v1/restrictive-practices/draft
       Draft case note from text transcript
       Input: case_note_id, client_id, worker_id, transcript
       Returns: incident_draft_id, draft_fields

  POST /v1/restrictive-practices/draft/audio
       Draft case note from audio recording (transcribes + extracts)
       Input: audio file, worker_id, client_id
       Returns: incident_draft_id, draft_fields, transcript

  Behaviour Support Plans (BSP)
  ──────────────────────────────
  POST /v1/restrictive-practices/bsp
       Register a Behaviour Support Plan
       Auth: JWT Bearer
       Input: client_id, practice_type, status, approved_dosage, etc.
       Returns: id, client_id, practice_type, status, valid_from, valid_until

  GET /v1/restrictive-practices/bsp/{client_id}
       List Behaviour Support Plans for a client
       Auth: JWT Bearer
       Returns: [{id, client_id, practice_type, status, ...}]

  PATCH /v1/restrictive-practices/bsp/{bsp_id}/status
       Update Behaviour Support Plan status
       Auth: JWT Bearer
       Input: status ('Active' | 'Expired' | 'Revoked')
       Returns: {id, status, ...}

  Voice Sessions
  ──────────────
  POST /v1/restrictive-practices/voice/session
       Create voice session for case-note dictation (WebSocket)
       Auth: JWT Bearer
       Input: client_id, worker_id, case_note_id
       Returns: session_id, ws_url, expires_at

  GET /v1/restrictive-practices/health
       Health check for RP service

═════════════════════════════════════════════════════════════════════════════════

ACTIVE ENDPOINTS (registered in Swagger):
────────────────────────────────────────────────────────────────────────────────

  POST /v1/restrictive-practices/incidents/analyze
       UNIFIED ENDPOINT: case-note form + voice transcript → all three screens
       Input: case_note_form (required), voice_transcript (optional)
       Returns: ai_summary, risk_summary, incident_draft, token_usage
       This is the current active API endpoint.
       See: api/unified_incident_routes.py

═════════════════════════════════════════════════════════════════════════════════

TO RE-ENABLE ARCHIVED ENDPOINTS:
────────────────────────────────────────────────────────────────────────────────

  1. Edit main.py (lines ~124-127)
  2. Uncomment:
       app.include_router(router)
       app.include_router(rp_router)
  3. Restart the service
  4. Old endpoints will appear in /docs (Swagger)

═════════════════════════════════════════════════════════════════════════════════
"""

# This file is documentation only.
# The actual archived endpoint code lives in:
#   - api/routes.py
#   - api/rp_routes.py
#   - api/voice_routes.py
#
# None of these are registered in main.py, so they don't appear in the active API.
