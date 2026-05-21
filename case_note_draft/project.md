# SENA — Full Project Context for AI Agents

> **Purpose:** This document is the authoritative context file for AI agents working on the SENA platform.
> It synthesises domain knowledge, actor maps, data isolation rules, all AI modules (planned + built),
> and architectural constraints. Read this before any design or implementation work.
>
> **Source:** Synthesised from `document.pdf` (POC meeting notes), `.planning/PROJECT.md`,
> `.planning/REQUIREMENTS.md`, `wiki/overview.md`, and `CLAUDE.md`.

---

## 1. Domain Context — What SENA Is

SENA is a multi-tenant SaaS platform that connects **NDIS-funded disability service providers** with
**disabled participants (clients)** in Australia. The NDIS (National Disability Insurance Scheme) is
the Australian government's insurance program that funds disability support. NDIS pays service
providers to deliver physical, social, and daily-living support to participants.

### Why This Is Complex

- Service providers are independent organisations (like NGOs), each with their **own internal policies**
  on top of mandatory NDIS/government regulations.
- A single client may receive services from **multiple providers simultaneously** — each provider
  must see only their own data, even though the client is shared.
- All AI outputs that affect a participant's record require **human-in-the-loop approval** — this is
  both an NDIS requirement and an Australian Privacy Act requirement.
- **Data isolation is legally mandated**, not just a best practice. Cross-tenant data leakage is a
  legal liability.

### Platform Scope

The platform covers the full operational lifecycle of a service provider:

| Module | Description |
|--------|-------------|
| HR System | Staff records, credentials, onboarding |
| Workforce Management | Shift scheduling, assignment, attendance |
| Client Management | Participant onboarding, care plans, NDIS goals |
| Billing | Client pays per service received; NDIS-funded |
| Payroll | Revenue sharing within the service provider organisation |
| AI Layer | This repository — AI assistance across all above modules |

**Important split:** The client team (separate engineering team) owns the web app, mobile app,
HR/payroll/shift/billing modules, and the primary database. This repo owns only the **AI/ML backend
layer**. API contracts between the two teams live in `api_contracts.py`.

---

## 2. Actor Map

| Actor | Platform | Role | AI Interaction |
|-------|----------|------|----------------|
| **Service Provider Admin** | Web | Manages the org: staff, clients, compliance | Web-Sena AI chatbot (policies, reports, audits) |
| **Support Worker (Ground Staff)** | Mobile | Visits client physically, delivers care | Voice case note drafting, AI shift briefing |
| **Manager / Support Coordinator** | Web + Mobile | Oversees support workers, approves outputs | Reviews AI-drafted notes, approves/rejects |
| **Client (Participant)** | Mobile | Disabled person receiving support | Voice-guided onboarding assistant |
| **NDIS / Government** | External | Funds the scheme, sets mandatory policies | Source of policy documents for RAG knowledge base |

---

## 3. Critical Isolation Rules (Non-Negotiable)

These rules govern every AI module. An AI agent must never violate them.

### Tenant Isolation (Organisation-Level)
- All data is scoped to a `tenant_id` (one service provider = one tenant)
- PostgreSQL: Row-Level Security (RLS) enforced on every table
- Redis: all keys prefixed `{tenant_id}:`
- LiveKit: rooms named `sena:{tenant_id}:{session_id}`
- AI chatbot knowledge base: per-tenant vector index, never shared
- Cross-tenant queries: trigger audit log + alert

### Employee-Level Isolation (Within a Tenant)
- Shift schedules and personal data visible only to the assigned employee
- A support worker sees only their own shifts, not their colleagues'
- Manager/admin can see all workers within their tenant

### Client-Level Isolation
- Participant data scoped per service provider, even if client has multiple providers
- Client AI onboarding assistant cannot access any other client's record
- Report generation scoped to a specific client selected by admin

---

## 4. AI Modules — Full Map

### 4.1 Already Implemented (Active in Codebase)

| Module | Service | Status | Description |
|--------|---------|--------|-------------|
| Case Note Dictation (Flow B) | `services/voice/` | **Active** | Voice → AWS Bedrock → draft case note. HTTP turn-based. Currently being migrated to LiveKit Agents + Gemini Live |
| Participant Onboarding Voice | `services/onboarding/` | **Active** | Voice-guided form filling via Gemini Live. 7-screen gated schema. Tool-driven field updates |
| OCR (Staff Onboarding) | `services/ocr/` | **Scaffolded, not implemented** | Extract info from government IDs (driver's licence) during staff onboarding. Must allow edit after extraction |

---

### 4.2 Phase 2 — Planned AI Modules

These come directly from the Phase 2 AI Module Breakdown table in the client meeting notes.
Each row includes the client's estimated hours (used for scoping reference, not commitments).

#### #48 — Participant Onboarding AI Assistant
- **Platform:** Mobile
- **Purpose:** AI assistant guides the client (disabled participant) through their onboarding
  registration end-to-end via voice
- **Key behaviours:**
  - Natural, conversational tone — must NOT sound like a typical AI chatbot
  - Screen-aware: AI fills fields autonomously page by page ("What is your name?")
  - Barge-in / interruption supported at any point
  - Clarifying questions when misunderstood — but not repetitively
  - Continues until full onboarding complete
- **Constraint:** Subject to LLM capability for NDIS understanding
- **Hours estimate:** Design 0, FE 20, BE 8, AI 40

#### #49 — Case Notes Register (Review & Insight Extraction)
- **Platform:** Web + Mobile
- **Purpose:** Analyse submitted case notes to identify progress, risks, and patterns
- **Web features:** Full document analysis, highlighted excerpts, confidence scores,
  approve/dismiss workflow, report generation
- **Mobile features:** View AI summary and flagged highlights only (read-only)
- **Human Control:** Manager / Compliance officer approval required before any action
- **Hours estimate:** Design 10, FE 8, BE 24, AI 16

#### #50 — Case Note Drafting (Mobile)
- **Platform:** Mobile (primary), Web (review)
- **Purpose:** Support worker drafts case note via voice immediately after a shift
- **Why this matters:** Workers have back-to-back shifts — if they don't draft immediately,
  they forget critical details. Voice removes the friction of typing.
- **Mobile flow:**
  1. AI asks about shift activities via voice
  2. Prompts for missing details: goals, behaviours, risks, incidents
  3. Generates structured draft case note
  4. Support worker reviews, edits, approves before submission
- **Web flow:** Manager reviews, compliance-checks, approves AI-drafted notes
- **Human Control:** Support worker MUST review and approve before submission
- **Hours estimate:** Design 10, FE 20, BE 8, AI 40

#### #51 — Restrictive Practices
- **Platform:** Web
- **Purpose:** AI pre-drafts compliant Incident & Restrictive Practice reports
- **What are restrictive practices?** Actions that restrict the rights or freedom of movement of
  a person with disability. Tightly regulated under NDIS. Reference document:
  `Regulated Restrictive Practices Guide (regulated-restrictive-practice-guide-rrp-20200.pdf)`
- **Web features:** Full draft generation, editing, validation checks, approval workflow
- **Mobile:** Draft preview only, no submission
- **Human Control:** Human sign-off is **mandatory** before any submission
- **RAG requirement:** Knowledge base built from NDIS Restrictive Practices documents
- **Hours estimate:** Design 8, FE 16, AI 50 (RAG knowledge base)

#### #52 — Shift AI Recommendations
- **Platform:** Web
- **Purpose:** AI-driven shift planning recommendations
- **Inputs used:**
  - Client's submitted NDIS goals
  - Prior shift activities and outcomes
  - Support worker feedback and history
- **Hours estimate:** Design 10, FE 15, AI 20

#### #53 — Audit (Compliance)
- **Platform:** Web
- **Purpose:** AI-powered compliance audits across all NDIS standards
- **Outputs:** Compliance status, identified risks, mitigation strategies, service improvement
  recommendations
- **Note:** Scope considered within #49 (Case Note Review & Insight Extraction)

#### #54 — Risk Flagging & Escalation Detection
- **Platform:** Web + Mobile
- **Purpose:** Detect critical or emerging risks from case notes and shift data
- **Web:** Risk dashboard, trend analysis, evidence trail, escalation controls
- **Mobile:** Push alerts + read-only risk summary
- **Human Control:** Manager decides all escalation actions
- **Note:** Scope considered within #49

#### #56 — AI Support Worker Briefing
- **Platform:** Web (create), Mobile (consume)
- **Purpose:** Translate client care plans into practical shift-level guidance for workers
- **Web:** Manager creates, edits, and tailors briefings
- **Mobile:** Primary platform for workers to consume shift guidance before arriving at client
- **Human Control:** Manager controls all content before it reaches workers
- **Note:** Scope considered within #49

#### #57 — AI Search & Pattern Recognition
- **Platform:** Web
- **Purpose:** Identify service-wide trends across case notes, clients, and outcomes
- **Features:** Advanced filters, analytics dashboards, audit preparation
- **Mobile:** Not available
- **Note:** As of 15-12-2025 meeting, considered within #49

#### #58 — AI Communication Log Analysis
- **Platform:** Web + Mobile
- **Purpose:** Detect sentiment, communication breakdowns, and disengagement signals
- **Web:** Full conversation analysis, risk tagging
- **Mobile:** Alert-only notifications
- **Human Control:** Human interpretation required — AI flags, human decides
- **Hours estimate:** BE 12, AI 24

#### #59 — AI Medication & Health Risk Detection
- **Platform:** Web + Mobile
- **Purpose:** Flag immediate health risks from care notes and medication records
- **Web:** Immediate flag + escalation workflow
- **Mobile:** Instant alert to management
- **Human Control:** Clinical judgment remains with humans — AI only flags
- **Open question:** Which specific health risks to detect? Weekly updated client health data
  should be included
- **Hours estimate:** BE 16, AI 8

#### #60 — AI Monthly Reports & Progress Summaries
- **Platform:** Web + Mobile
- **Purpose:** Consolidate participant progress into structured monthly reports
- **Web:** Report creation, editing, export for stakeholders
- **Mobile:** Read-only summary view
- **Human Control:** Manager approves before sharing
- **Format:** Client provides exact LaTeX report template — output must match exactly
- **Hours estimate:** Design 30, BE 40, AI 80

---

## 5. Web-Sena AI Chatbot — Detailed Module Breakdown

This is the AI assistant embedded in the web app (used by service provider admins and employees).
It is **tenant-isolated** — each service provider has a separate knowledge scope.
NDIS government policies are **shared across all tenants** (common layer).
Company-specific policies are **per-tenant** (isolated layer).

### 5.1 Policies Module
- Answer questions about NDIS government regulations
- Answer questions about the service provider's internal policies
- Explain policy updates when they occur
- Policy sources: PDF documents + portal-entered policies (must fetch dynamically from DB)
- Accuracy requirement: client expects **near 100% accuracy** — RAG with high-confidence retrieval

### 5.2 Shift-Check Module
- Answer employee questions about their own scheduled shifts and internal meetings
- Shift data must be **employee-scoped** — only their own data visible
- Also answer manager questions about team schedules (manager scope = full team)

### 5.3 Procedures Module
- AI assistant for operational registers (library records for specific categories)
- Key registers:
  | Register | Purpose |
  |----------|---------|
  | Asset Register | Organisation's physical assets |
  | Documents Register | Documents in the system, who each is assigned to |
  | Risk Management Plan Register | Risk records tied to client service delays or incidents |
- AI should be able to query, explain, and update registers via conversation

### 5.4 Client Information Module
- AI should have knowledge of all clients onboarded per service provider (tenant-scoped)
- Data changes frequently — AI must handle real-time or near-real-time updates gracefully
- Pattern: database-driven RAG (read from DB, not static documents)

### 5.5 Report Generation Module
- Admin selects a specific client
- AI generates a structured report in exact LaTeX format provided by client
- Report template PDF will be supplied by client team
- Generation is via the same Web-Sena AI chatbot interface

---

## 6. Support Worker Mobile Flow (Detailed)

This flow describes exactly what happens on the mobile app for a support worker.

### Shift View
1. Worker opens mobile app, sees next scheduled shift
2. Shift details: client name, service type, location, agenda (sleepover / 24-hour care / etc.)
3. **AI Past Shift Summary** (only shown if past shifts exist for this client):
   - AI generates a summary of all past shifts for this specific client
   - Purpose: worker arrives briefed, knows client history
   - If no past shifts → summary not shown

### Post-Shift Case Note Flow
1. Shift ends → worker starts case note on mobile
2. **AI Voice Dictation** (module #50):
   - AI asks structured questions about the shift
   - Prompts for: goals addressed, behaviours observed, risks, incidents
   - Worker answers via voice
   - AI generates structured draft
3. Worker reviews draft, edits if needed, approves
4. **AI Summary Generation**: paragraph-level chunks generated from case note
5. **AI Flagging System**:
   - Each paragraph chunk checked against NDIS rules
   - Rules source: NDIS Regulated Restrictive Practices Guide
   - Examples of flaggable scenarios:
     - Did worker obtain consent before physical contact?
     - Client misbehaviour after proper care delivered
     - Any use of restricted practices (restraint, seclusion, etc.)
   - Flagged items require manager review before submission
6. Worker submits; manager sees flagged items on dashboard

### Incident Reports
- Can be filed separately or alongside case notes
- Can be completed later (not required immediately after shift)

---

## 7. Manager / Support Coordinator Web View

- Sees all support workers under their tenant
- Sees all shifts completed by each worker
- Per-shift AI summary (from case note)
- Combined summary across all shifts (aggregate view)
- Monthly overview report auto-generated when approved (LaTeX format)
- Approval workflow: approve / reject AI-drafted notes and reports

---

## 8. Case Note Flagging — NDIS Compliance Rules Engine

This is a critical compliance subsystem. It is NOT optional.

### What Gets Flagged
- Any documented use of a **regulated restrictive practice** (physical restraint, chemical
  restraint, mechanical restraint, seclusion, environmental restraint)
- Consent violations (touching/assisting without recorded consent)
- Client rights violations
- Incidents that require mandatory reporting under NDIS rules

### How It Works (Architecture)
- AI generates paragraph-level chunks from the case note
- Each chunk is compared against the knowledge base built from:
  - NDIS Regulated Restrictive Practices Guide
  - NDIA Regulated Restrictive Practice Guide PDF (RRP-20200)
- Matching is semantic (RAG), not keyword-only
- Flagged items are tagged with:
  - The specific rule violated
  - Confidence score
  - Recommended action
- Manager reviews flags and decides escalation

### Human Control Point
All flagged items require manager review. AI cannot auto-submit or auto-escalate.

---

## 9. OCR — Staff Onboarding

When a support worker is being onboarded by the organisation:
- They must upload government-issued ID (e.g., Australian driver's licence)
- AI performs OCR to extract: name, DOB, licence number, address, expiry
- Extracted data is pre-filled into the onboarding form
- Worker must have option to **edit** any extracted field before confirming
- Service: `services/ocr/` — scaffolded, implementation pending

---

## 10. AI Architecture Constraints

### Data Freshness
- Client information (module 5.4) is **frequently updated** — the AI pipeline must handle
  incremental updates gracefully (not full re-index on every change)
- Recommended: event-driven RAG update (DB change → embedding update job → vector store)

### Accuracy Requirement
- Client expects **near 100% accuracy** for the policy chatbot
- Implication: RAG must use high-quality chunking, citation tracking, and confidence thresholds
- Low-confidence responses should say so explicitly, not hallucinate

### Multi-Tenant Knowledge Base Architecture
- **Layer 1 (global):** NDIS government policy documents — one shared index, all tenants read
- **Layer 2 (per-tenant):** Service provider policies — separate index per `tenant_id`
- **Layer 3 (per-tenant dynamic):** Live DB data (clients, shifts, registers) — DB-backed RAG

### Human-in-the-Loop (Mandatory for All AI Outputs)
Every AI-generated output that enters a participant's official record must pass through a human
approval step. This is both NDIS policy and Australian Privacy Act requirement. The AI layer must
never bypass this, regardless of confidence score.

### Australian Data Residency
- All audio, transcripts, and PII must transit and be stored within Australian AWS/GCP regions
- Gemini Live: `australia-southeast1` — region support must be confirmed before production
- Fallback stack for audio: Deepgram AU + Claude Sonnet AU + ElevenLabs AU

---

## 11. LLM Provider Strategy

| Use Case | Provider | Model | Reason |
|----------|----------|-------|--------|
| Voice dictation (conversational) | Google Gemini Live | `gemini-3.1-flash-live-preview` | Native audio, single model, lowest latency |
| Case note text post-processing | AWS Bedrock | Claude 3.5 Sonnet | Existing, AU region, good at structured text |
| Onboarding voice form-filling | Google Gemini Live | `gemini-3.1-flash-live-preview` | Same as dictation — tool calling + voice |
| RAG / policy chatbot | TBD | Claude Sonnet or Gemini Flash | Best for grounded retrieval with citations |
| Restrictive practice flagging | TBD (RAG) | Claude Sonnet or Gemini Flash | Need semantic matching against policy docs |
| Report generation (LaTeX) | TBD | Claude Sonnet (best at structured output) | Exact format matching required |
| OCR extraction | Google Document AI or AWS Textract | — | Specialised for government IDs |

---

## 12. What the AI Team Owns vs Client Team

| Concern | AI Team (this repo) | Client Team (separate) |
|---------|---------------------|------------------------|
| Voice transcription + LLM calls | ✓ | |
| Case note draft generation | ✓ | |
| Flagging / compliance checks | ✓ | |
| RAG knowledge base (policies) | ✓ | |
| OCR for document extraction | ✓ | |
| Report generation (content) | ✓ | |
| Report format / LaTeX template | | ✓ (provides template) |
| Primary database (clients, shifts, HR) | Read-only access | ✓ (owns schema) |
| Mobile app UI | | ✓ |
| Web app UI | | ✓ |
| Billing / payroll / HR modules | | ✓ |
| API contracts definition | Joint (`api_contracts.py`) | Joint |

---

## 13. Open Questions (From Meeting Notes)

These were unresolved at the time of the POC meeting:

1. **Screen awareness during onboarding:** Client mentioned AI should "be able to see the screen"
   during participant onboarding — this likely means screen/context injection, not literal screen
   capture. Confirm with client team.
2. **Shift AI query entry point:** Client asked "where will employees ask AI about shifts?" —
   no UI entry point defined yet. Needs UX decision from client team.
3. **Health risk detection scope (#59):** Which specific health risks should be detected?
   Needs clinical input from client.
4. **Report LaTeX templates:** Client to provide sample PDFs. Not yet received.
5. **Real data availability:** Client mentioned real data available by end of March (2026).
6. **Gemini Live AU region:** `australia-southeast1` support for Gemini Live unconfirmed.

---

## 14. Glossary — NDIS Domain Terms

| Term | Definition |
|------|-----------|
| **NDIS** | National Disability Insurance Scheme — Australian federal disability insurance program |
| **NDIA** | National Disability Insurance Agency — government body that administers NDIS |
| **Participant / Client** | Disabled person funded by NDIS to receive support services |
| **Service Provider** | Organisation (like an NGO) that employs support workers and delivers care |
| **Support Worker** | Ground staff who physically visits and assists a participant |
| **Case Note** | Formal record of what happened during a support shift, submitted after every shift |
| **Restrictive Practice** | Any action that limits a participant's rights or movement (heavily regulated) |
| **Incident Report** | Formal record of any unexpected event during a shift |
| **NDIS Goals** | Participant's personal development goals funded under their NDIS plan |
| **Care Plan** | Document detailing the support a participant should receive |
| **Shift Briefing** | Pre-shift notes for the support worker about the client and expected activities |
| **Register** | An operational library/log (asset register, documents register, risk register) |
| **Regulated Restrictive Practice** | Category of restrictive practice requiring NDIS-mandated reporting and authorisation |
| **Support Coordinator** | NDIS-funded role helping participants coordinate their supports (often a manager equivalent) |
| **SOAP Format** | Subjective, Objective, Assessment, Plan — structured case note format |

---

*Generated: 2026-04-27 from POC meeting notes + existing planning context*
*Source document: `case_note_draft/document.pdf` (Sena Cline Meeting Outcomes Clean)*
