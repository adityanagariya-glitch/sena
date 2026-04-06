# SENA — AI/ML Backend Layer

## Project Overview
Sena is an AI-powered multi-tenant SaaS platform for Australian NDIS (National Disability Insurance Scheme) service providers. Our team owns the **AI/ML backend layer only**. The broader platform (HR, payroll, shifts, client management) is built by a separate client-side team.

## Current Phase
**Sprint 0 scaffold BUILT, not yet tested.** Planning complete. Monorepo created with 40 files. Next step: validate scaffold end-to-end (`docker compose up`, tests, seed data).

## Planning Strategy (Agreed)
1. Get answers — team, priorities, constraints (DONE)
2. Map blockers — what can we build now vs. what's waiting on others
3. Pick 2 starter modules — build, demo, get feedback
4. Layer up — add modules as dependencies unblock
5. Iterate — each module is a sprint prove-it-works cycle

## Client Expectations
- Client wants everything "ready to use" (all 10 modules)
- No defined deadline
- No API contracts exist yet
- Real data expected ~end of March 2026
- This is also an evaluation of the AI team's capability

## Team Structure
- **Our team (AI vendor):**
  - User — AI/ML development lead (senior, owns architecture + implementation)
  - Team lead — 3-4 years experience (supports at every phase)
  - Intern — learning, can handle guided tasks
  - Effective builders: **2 people** (user + team lead, intern as support)
- **Client team:** Sandeep (PM/coordinator), Jill (frontend lead), Nishant (backend manager) — building the core platform
- **Integration status:** No API contracts exist yet between AI team and platform team

## Key Context
- Existing docs (specs, architecture files) were produced by an intern as initial exploration — they are **not** finalized decisions or production-grade specs. Treat them as rough starting points, not constraints.
- Real data expected ~end of March 2026
- Client is in Australia; NDIS compliance and Australian privacy law are hard legal requirements

## AI Modules (Scope)
1. **Voice Onboarding Assistant** — Conversational AI that fills participant onboarding forms via voice (mobile)
2. **Case Note Drafting** — Support workers dictate shift notes; AI structures them (mobile, voice)
3. **Case Note Review & Insight Extraction** — Risk flagging, pattern recognition, compliance checks (web + mobile)
4. **Policy/Compliance RAG Chatbot** — Queries against NDIS regulations + per-org policies (web)
5. **Restrictive Practices Drafting** — Pre-draft compliant incident reports (web)
6. **Risk Flagging & Escalation** — Detect clinical risks from case notes, escalation workflow (web + mobile)
7. **Reporting** — Structured reports in client-specified formats (web + mobile)
8. **OCR Document Extraction** — Government ID extraction during staff onboarding (mobile)
9. **Communication Log Analysis** — Sentiment detection, disengagement flags (web + mobile)
10. **Medication & Health Risk Detection** — Flag immediate health risks, weekly tracking (web + mobile)

## Hard Requirements
- **Multi-tenant data isolation** — legally mandated, zero cross-tenant data leakage
- **Human-in-the-loop** — all AI outputs require manager/compliance approval before action
- **Australian data residency** — sensitive data must stay in AU jurisdiction
- **NDIS compliancekt file
## Starter Modules (Decided)
- **Module 1: OCR Document Extraction** — quick win, zero dependencies, builds deployment pipeline
- **Module 2: Policy/Compliance RAG Chatbot** — foundational infra (embeddings, vector store, retrieval), reused by 5+ later modules, tests multi-tenancy early
- **Module 3 (next): Voice Onboarding Assistant** — after OCR + RAG prove the team and infra

## Decisions NOT Yet Made
- Cloud provider, deployment model, LLM provider, OCR pipeline, embedding model, CI/CD — all blocked on client meeting answers.
- See `TECHNICAL_DECISIONS.md` for full details.
- 5 decisions already DECIDED: Python+FastAPI, RLS, pgvector, hybrid search, structure-aware chunking.

## File Index
- `CONTEXT_HANDOFF.md` — **THE master context document. Read this first in any new session.**
- `sena_meeting_notes.md` — Summarized meeting/kickoff notes
- `AI Planning & R&D Kickoff Transcript.txt` — Full transcript of kickoff call with Sandeep
- `prompt.txt` — Running context and conversation state
- `docs/architecture/` — Intern's initial spec drafts (treat as rough exploration, not finalized)
- `QUESTIONS_FOR_CLIENT.md` — Questions that need answers from Sandeep/Nishant/Jill before we can proceed
- `TECHNICAL_DECISIONS.md` — Internal technical decisions to make with senior/architect guidance
- `SPRINT_0_PLAN.md` — Sprint 0 definition with 3 tracks, task assignments, and definition of done
- `sena-ai/` — Monorepo scaffold (40 files, the Sprint 0 Track A deliverable)
