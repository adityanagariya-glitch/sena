# Remaining Questions & Follow-Ups for Client

> **Context**: These are all open questions that block or impact our development. Organized by **who needs to answer** and **when we need the answer**.
>
> **Status key**: 🔴 BLOCKER (cannot proceed without) | 🟡 HIGH (impacts architecture) | 🟢 MEDIUM (can work around temporarily)
>
> **Source key**: [ORIGINAL] = from first questions doc, still unanswered | [NEW] = new question from revised v3 plan

---

## Questions for Nishant (Backend Manager)

### 🔴 BLOCKER — Need Before Sprint 0 Completes

#### 1. Authentication & Authorization System [ORIGINAL — NOT ANSWERED]

This was flagged as CRITICAL in our first meeting and remains completely unanswered. **We cannot build real security without this.**

**What we need to know:**

- **a)** What auth provider does the platform use? (AWS Cognito, Firebase Auth, Auth0, Keycloak, custom JWT, session-based?)
- **b)** What does the JWT/token contain? Specifically:
  - Is there a `user_id` field?
  - Is there an `org_id` or `tenant_id` field? (**Critical for multi-tenant isolation**)
  - Is there a `role` field? (e.g., "support_worker", "manager", "admin")
  - What is the token format? (JWT? Opaque token? Session cookie?)
- **c)** How do we validate these tokens? (Public key URL? Shared secret? API call to auth service?)
- **d)** Is there a token refresh mechanism? (Refresh tokens? Token expiry duration?)

**Why this blocks us**: Every AI endpoint needs to know which tenant/org a request belongs to. We cannot enforce data isolation without this. We're currently using a **hardcoded dev-mode auth bypass** — this CANNOT go to production.

**Our temporary workaround**: Dev middleware that accepts `X-Tenant-ID` and `X-User-Role` headers. Works for development but zero security.

---

#### 2. Database Schema [NEW — CRITICAL]

Since the client chose **direct database access** (Option B), we need the actual schema to build our data layer.

**What we need:**

- **a)** Complete table list with columns for:
  - `participants` / `clients` table (what's the actual table name? What columns? Is NDIS number stored here?)
  - `organizations` / `tenants` table (what's the multi-tenancy column? `org_id`? `tenant_id`? `organization_id`?)
  - `staff` / `support_workers` table
  - `shifts` table (with shift-participant-worker relationships)
  - `case_notes` table (if it exists already — or are we creating it?)
  - `medications` table
  - `policies` table
  - `registers` table
- **b)** What is the **multi-tenancy column name**? (We use `tenant_id` throughout our plan — if theirs is `org_id` or `organization_id`, we need to align)
- **c)** Are there any **foreign key relationships** we should be aware of?
- **d)** Which tables are **read-only** for us vs. which can we **write to**?
- **e)** Is the database using **UUIDs** or **integer IDs** as primary keys?
- **f)** What PostgreSQL version is running? (We need version 16+ for optimal pgvector support on our AI DB)
- **g)** Is **Row-Level Security (RLS)** enabled on their DB? If so, how is it configured?
- **h)** Database connection details — can we get a read-only user account for dev?

**Ideal format**: A database dump (`pg_dump --schema-only`) or an ER diagram would be perfect. Even a screenshot of their ORM models would work.

---

#### 3. AWS Account Access [NEW]

- **a)** Do we get our own **AWS sub-account** under their organization? Or do we set up an entirely separate AWS account?
- **b)** If sub-account: what IAM permissions will we have? Do we get admin access to provision our own resources (RDS, ECS, ElastiCache, S3, SQS)?
- **c)** If separate account: how do we connect to their EC2 Postgres from our AWS account? (VPC peering? Transit Gateway? Public endpoint with IP whitelist?)
- **d)** Is there an existing VPC we should deploy into, or do we create our own?
- **e)** Are there any **compliance restrictions** on what AWS services we can use? (Some enterprises restrict to approved service lists)
- **f)** What AWS region are they using? (We assume `ap-southeast-2` / Sydney — need to confirm)

---

#### 4. Database Connection & Network [NEW]

- **a)** How do we connect to their Postgres from our services? (VPC internal? SSH tunnel? Public endpoint?)
- **b)** Is there a **connection pool** (like PgBouncer) in front of their Postgres, or do we connect directly?
- **c)** What are the **connection limits**? (Max concurrent connections available for our AI services)
- **d)** Is there a **read replica** we should use for heavy queries (like report generation)? Or do we query the primary?
- **e)** What is the DB backup strategy? (Important because we're now writing to their DB)
- **f)** Who do we contact if there's a DB issue? (Ops contact for incidents)

---

### 🟡 HIGH — Need Before Sprint 1-2

#### 5. Roles & Permissions [ORIGINAL — NOT ANSWERED]

From the kickoff, we heard these roles: service provider admin, manager, support coordinator, support worker, participant/client.

- **a)** What can each role do in the AI context? For example:
  - Can a support worker use the RAG chatbot, or only managers?
  - Can a support worker trigger voice onboarding, or only coordinators?
  - Who can upload policy documents? (We recommend admin/compliance officer only — is that right?)
- **b)** Who can **approve** AI-generated outputs in the approval queue? (Managers only? Coordinators too?)
- **c)** Are there **org-level admins** (manage one organization) vs. **Sena platform-level admins** (manage the whole platform)?
- **d)** Can roles be customized per organization, or are they fixed across the platform?

---

#### 6. How Does Our AI API Integrate with Their Frontend? [NEW]

Client confirmed a **separate API gateway** for AI services. But we need clarity on how this works in practice:

- **a)** How does their frontend (mobile app / web app) call our AI services?
  - Direct call to our API gateway? (e.g., `ai-api.sena.com/v1/...`)
  - Through their backend as a proxy? (Frontend → Their backend → Our AI API)
- **b)** Do they need us to provide an **API spec / Swagger / OpenAPI doc** for Jill's frontend team?
- **c)** For real-time features (voice, RAG streaming):
  - Does their frontend support **WebSocket** connections? (For voice via LiveKit)
  - Does their frontend support **Server-Sent Events (SSE)**? (For RAG streaming)
- **d)** What is the **CORS** situation? Will the frontend call us from a different domain?
- **e)** Is there a shared domain we should deploy under? (e.g., `api.sena.com/ai/...` vs `ai.sena.com/...`)

---

#### 7. Database Migration Coordination [NEW]

Since we're both writing to the same Postgres database:

- **a)** How do they manage database migrations? (Alembic? Flyway? Django migrations? Manual SQL?)
- **b)** Do they have a **staging/dev database** we can develop against? Or do we need to create our own copy?
- **c)** How do we coordinate schema changes? (Who approves? What's the process?)
- **d)** Are there any **triggers, stored procedures, or views** on their tables that we should know about?
- **e)** Is there a scheduled maintenance window when the DB might be unavailable?

---

## Questions for Jill (Frontend Lead)

### 🔴 BLOCKER — Need Before Sprint 1

#### 8. Onboarding Form Flow [ORIGINAL — NOT ANSWERED, NOW CRITICAL]

This was originally categorized as "can wait until later" but is now **our #1 priority** since the client wants voice onboarding built first.

**We need the complete specification:**

- **a)** Full list of **onboarding screens/sections** (e.g., Personal Details, Medical Info, Stakeholders, Communication Preferences, Risk Assessment, Documentation)
- **b)** For each section, the complete list of **fields** with:
  - Field name (exactly as stored in DB)
  - Display label
  - Field type (text, date, dropdown, multi-select, file upload, yes/no, etc.)
  - Required vs optional
  - Validation rules (e.g., Medicare number format: `XXXX XXXXX X`, date format, phone format)
  - Dropdown options (if applicable — e.g., gender options, language options, communication preferences)
- **c)** Are there **conditional fields**? (e.g., "If participant takes medication → show medication details fields")
- **d)** What is the **section order**? Can the voice assistant ask questions in any order, or must it follow the screen sequence?
- **e)** What happens when a field is filled via voice? Does the frontend form update **in real time** (via data channel), or on form submission?
- **f)** Can the user **manually override** a voice-filled field on the screen?
- **g)** What is the expected **number of fields** total? (Rough count helps us estimate session duration)

**Ideal format**: Screenshots of the onboarding screens, or a Figma/design link, or even a spreadsheet listing all fields.

---

### 🟡 HIGH — Need Before Sprint 1

#### 9. Voice Assistant UX in Mobile App [ORIGINAL — NOT ANSWERED, NOW HIGH PRIORITY]

- **a)** How does the user **start** a voice session? (Tap a mic icon? A dedicated "Start Voice Onboarding" button?)
- **b)** What does the UI look like **during** a voice session? (Full-screen? Overlay? Split-screen with form visible?)
- **c)** When the voice assistant fills a field, what should happen on screen? Options:
  - Field highlights and auto-fills (real-time)
  - A "pending" indicator shows until assistant confirms
  - Form stays static, only updates on session end
- **d)** Can the user **navigate away** mid-conversation? What happens to the session?
- **e)** Is there a **text fallback** for users who can't use voice? (Type instead of speak)
- **f)** Is the voice assistant **always available**, or only on certain screens?
- **g)** **Who is physically speaking** during onboarding? The participant directly? Or a support worker speaking on their behalf? (This affects the AI's conversational tone and prompts)
- **h)** Is the voice UI already being designed/built, or do we need to spec it?

---

#### 10. Case Note Voice Dictation UX [NEW]

Client said case notes and registers use the same voice assistant approach as onboarding:

- **a)** What does the case note entry screen look like? (Fields / free text / both?)
- **b)** Is dictation **free-form** (worker speaks naturally) or **structured** (assistant asks specific questions)?
- **c)** At what point in the workflow does case note entry happen? (End of shift? During shift? Both?)
- **d)** Does the shift context (participant name, shift time, activities) auto-populate, or does the voice assistant need to ask?
- **e)** Is there a section for **incident reporting** within case notes, or is that a separate flow?

---

## Questions for Sandeep (Product Owner)

### 🟡 HIGH — Need Before Sprint 3

#### 11. Case Note Structure [ORIGINAL — NOT ANSWERED]

- **a)** Complete list of fields in a case note
- **b)** Which fields are mandatory vs. optional
- **c)** 2-3 examples of what a "good" case note looks like (even redacted/anonymized)
- **d)** What constitutes a "flag" — the exact NDIS criteria for flagging incidents
- **e)** What are the categories of risk? (Physical, behavioral, medication, neglect, restrictive practice, etc.)

---

#### 12. NDIS Policy Documents [ORIGINAL — PROMISED]

Sandeep said "yes they will provide" — we need to follow up:

- **a)** When can we expect the sample documents?
- **b)** What format are they in? (PDF, Word, HTML?)
- **c)** Are these **publicly available NDIS documents**, or does each organization have custom policies?
- **d)** How many documents roughly? (10? 50? 200? Affects chunking and storage estimates)
- **e)** How often do policies change? (Annually? Quarterly? Triggered by NDIS updates?)
- **f)** Are there different categories? (e.g., NDIS Practice Standards, Pricing Guidelines, state-level policies, org-specific procedures)

---

### 🟢 MEDIUM — Can Wait Until Later Sprints

#### 13. Report Format [ORIGINAL — SANDEEP MENTIONED HE WOULD SHARE]

- **a)** Has Sandeep shared the report template document yet? If not, when?
- **b)** What sections does a typical report contain?
- **c)** Who are the target readers? (NDIS auditors? Families? Internal management?)
- **d)** Is the report format standardized by NDIS, or org-specific?

---

#### 14. Expected Scale [ORIGINAL — NOT ANSWERED]

- **a)** How many service provider organizations at launch? (5? 10? 50?)
- **b)** How many support workers per organization on average?
- **c)** How many shifts per day across the platform?
- **d)** What's the peak concurrent usage pattern? (Shift changeover: 7am, 3pm, 11pm?)
- **e)** Any geographic distribution? (All in one city? Australia-wide?)

---

#### 15. Real Data Timeline [ORIGINAL — NOT ANSWERED]

- **a)** Sandeep mentioned "approximately end of March" for real data in the system — did this happen?
- **b)** Is the onboarding flow live and generating real participant data?
- **c)** Can we get **realistic mock data** to develop against in the meantime?
- **d)** If there's test/staging data already, can we get read access to it?

---

## New Questions from AI Team (Internal Decisions + Client Input Needed)

### 🟡 Architecture Decisions Needing Validation

#### 16. Dual Database Strategy — Client Approval [NEW]

We're proposing a **dual database approach**: read/write their shared Postgres + our own AI-dedicated RDS Postgres for vectors/audit/AI data.

- **a)** Is the client okay with us spinning up a **separate RDS instance** on their AWS account (or ours)?
- **b)** Are there cost concerns with running an additional database? (~$140/mo for RDS Multi-AZ)
- **c)** Would they prefer everything in one DB? (We'd need to add pgvector extension to their Postgres and coordinate all migrations)

---

#### 17. Voice LLM Strategy [NEW]

Bedrock Claude (our primary LLM) doesn't support native audio I/O. For voice, we need one of:

- **Option A**: AWS Transcribe (STT) + Claude (reasoning) + AWS Polly (TTS) — all AWS, ~965ms per turn
- **Option B**: Google Gemini multimodal (audio in/out, single call) — cross-cloud, ~500ms per turn
- **Option C**: Third party (Deepgram STT + Claude + ElevenLabs TTS) — best quality, ~$0.03/min

**Question for client**: Do they have a preference? Is cross-cloud (using Google for voice only) acceptable? Is voice quality (natural-sounding TTS) a priority, or is functional sufficient?

---

#### 18. Approval Queue — Where Does It Live? [NEW]

The approval queue (where managers review AI outputs before they go live) needs a frontend UI.

- **a)** Does Jill's team build this UI? Or do we need to build an approval dashboard?
- **b)** If Jill's team builds it: we provide the API, they build the screens. Is that agreed?
- **c)** How are managers **notified** of pending approvals? (Push notification? Email? In-app badge? All three?)
- **d)** For **urgent (Tier 3)** items: is there an existing notification system we can hook into, or do we need to set up something?

---

#### 19. Data Residency Verification [NEW]

Client is on AWS. We need to verify:

- **a)** Are ALL their services in `ap-southeast-2` (Sydney)? Or are some in other regions?
- **b)** Is **Amazon Bedrock** with Claude available in `ap-southeast-2`? (Some Bedrock models are US-only — we need to verify)
- **c)** Are there any organizational policies about data residency beyond "use AWS"?
- **d)** Does the client have any existing compliance certifications (ISO 27001, SOC2) that we need to align with?

---

#### 20. Onboarding Scope Clarification [NEW]

Client said "start working on client onboarding" — need to clarify:

- **a)** Is "client onboarding" = **participant onboarding** (adding a new NDIS participant to the system)?
- **b)** Or is it **organization/provider onboarding** (setting up a new service provider on the platform)?
- **c)** Or is it **staff onboarding** (adding a new support worker)?
- **d)** The voice assistant — is it primarily for **participants** to fill in their own details, or for **support workers** to fill in details on behalf of the participant?

---

#### 21. Existing Platform Status [NEW]

Understanding where Nishant's team is helps us plan integration:

- **a)** Is the platform backend **live in production**, or still in development?
- **b)** What framework is the backend built with? (Django? FastAPI? Express? Spring?)
- **c)** Is the mobile app **live**, or still in development?
- **d)** What framework is the mobile app built with? (React Native? Flutter? Swift/Kotlin?)
- **e)** Is there an existing **staging/dev environment** we can integrate with?

---

## Summary: Priority Actions

### This Week (Before Sprint 0 Ends)

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 1 | Schedule call with Nishant re: Auth + DB schema + AWS access | Us → Nishant | ⬜ TODO |
| 2 | Request onboarding form spec from Jill/Sandeep | Us → Jill/Sandeep | ⬜ TODO |
| 3 | Confirm AWS region (ap-southeast-2) and Bedrock availability | Us (research) | ⬜ TODO |
| 4 | Request DB connection details for dev environment | Us → Nishant | ⬜ TODO |

### Next Week (Sprint 1 Start)

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 5 | Get voice UX mockups/spec from Jill | Us → Jill | ⬜ TODO |
| 6 | Follow up on NDIS policy docs from Sandeep | Us → Sandeep | ⬜ TODO |
| 7 | Validate dual-DB approach with client | Us → Nishant/Sandeep | ⬜ TODO |
| 8 | Decide voice STT/TTS strategy (AWS native vs Gemini vs third-party) | Internal team | ⬜ TODO |

### Later (Sprint 3+)

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 9 | Get case note structure from Sandeep | Us → Sandeep | ⬜ TODO |
| 10 | Get report template from Sandeep | Us → Sandeep | ⬜ TODO |
| 11 | Scale/capacity planning discussion | Us → Sandeep | ⬜ TODO |

---

*Generated: 2026-03-31 | Based on: QUESTIONS_FOR_CLIENT.md (original) + client meeting answers + revised_plan.md (v3)*
*Total open questions: 21 (4 blockers, 10 high priority, 7 medium)*
