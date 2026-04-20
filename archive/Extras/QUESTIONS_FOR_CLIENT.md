# Questions for Client (Sandeep / Nishant / Jill)

> These are questions the AI team CANNOT answer alone. They require input from the client's platform team before we can make architectural decisions or begin implementation.
>
> **Status key:** OPEN = unanswered | ANSWERED = resolved | BLOCKED = waiting on something else first

---

## 1. Integration & API Contracts

### 1.1 How does the AI layer integrate with the platform? [OPEN] [CRITICAL]
**Who to ask:** Nishant (backend manager)

The AI team needs to call or be called by the platform. Two options:

- **Option A:** Platform exposes REST APIs — AI services call those APIs to read/write data (e.g., save onboarding form fields, retrieve case notes). AI team has its own database for AI-specific data only (vectors, embeddings, processing queues).
- **Option B:** AI services get direct read/write access to specific tables in the shared Postgres database.

**Why this matters:** This determines how every AI module interacts with the platform. It's the single most important integration decision.

**Our recommendation:** Option A (API-based integration) — cleaner separation, fewer risks of breaking each other's systems. But requires Nishant's team to expose APIs.

**Question for Nishant:** "Will your backend expose APIs that our AI services can call to read/write data, or should we plan for direct database access?"

---

### 1.2 What is the platform's API gateway / routing setup? [OPEN]
**Who to ask:** Nishant

- How do mobile/web apps currently reach the platform backend? (e.g., `api.sena.com/v1/...`)
- Will AI services sit behind the SAME API gateway, or do we need a separate one?
- Is there an existing service mesh or load balancer?

**Why this matters:** Determines how we expose our endpoints and whether the client's frontend team (Jill) calls us directly or through an intermediary.

---

### 1.3 What database does the platform use and what's the schema? [OPEN]
**Who to ask:** Nishant

- What database engine? (Postgres, MySQL, etc.)
- Can we get the current schema (or planned schema) for: clients/participants, staff/support workers, shifts, case notes, policies, registers?
- Is multi-tenancy already enforced at the DB level? If so, how? (tenant_id column, separate schemas, separate DBs?)

**Why this matters:** Our multi-tenancy model must align with theirs. If they use `org_id` and we use `tenant_id`, we have a mismatch.

---

## 2. Authentication & Authorization

### 2.1 What auth system does the platform use? [OPEN] [CRITICAL]
**Who to ask:** Nishant

- Is there an existing auth provider? (Firebase Auth, Auth0, Keycloak, custom JWT?)
- What claims are in the token? (user ID, org/tenant ID, role?)
- Can our AI services validate the same tokens?

**Why this matters:** Our AI services need to know which tenant a request belongs to. We should consume the platform's auth tokens — not build a separate auth system. This is the foundation of multi-tenant data isolation.

**Question for Nishant:** "What authentication system are you using, and does the JWT/token include an organization or tenant identifier?"

---

### 2.2 What roles and permissions exist in the system? [OPEN]
**Who to ask:** Sandeep / Nishant

From the kickoff, we heard: service provider admin, manager, support coordinator, support worker, participant/client.

- What can each role do in the AI context? (e.g., can a support worker use the RAG chatbot, or only managers?)
- Who can approve AI-generated outputs? (human-in-the-loop requirement)
- Are there org-level admins vs. Sena platform-level admins?

**Why this matters:** Determines what authorization checks our AI endpoints need to enforce.

---

## 3. Data & Documents

### 3.1 Can we get sample NDIS policy documents? [OPEN] [BLOCKS RAG MODULE]
**Who to ask:** Sandeep

- The RAG chatbot needs NDIS regulatory documents and sample org-level policies to build and test against.
- Are NDIS documents publicly available, or does the client have specific versions they use?
- Can Sandeep provide 2-3 sample organization-level policy documents (even dummy/template ones)?

**Why this matters:** Cannot build, test, or demo the RAG chatbot without documents to ingest. Also needed to validate our chunking strategy — NDIS docs with tables, numbered sections, and nested headings need to be tested to ensure our parsing preserves document structure correctly.

---

### 3.2 What government ID documents does OCR need to handle? [OPEN] [BLOCKS OCR MODULE]
**Who to ask:** Sandeep

- Which specific document types? (Australian driver's license, Medicare card, passport, NDIS participant card, Working with Children Check, etc.)
- Are there sample images we can test with?
- What fields need to be extracted from each document type?

**Why this matters:** Different document types need different extraction strategies. We need to know the full list before building.

---

### 3.3 What is the case note structure? [OPEN]
**Who to ask:** Sandeep / Nishant

From the kickoff, case notes are filled after a shift and include many fields. We need:
- The complete list of fields in a case note
- Which fields are mandatory vs. optional
- What a "good" case note looks like (2-3 examples)
- What constitutes a "flag" — the exact NDIS criteria for flagging incidents

**Why this matters:** Blocks Case Note Drafting (Module 2 after starter), Risk Flagging, and Restrictive Practices modules.

---

### 3.4 What does the report format look like? [OPEN]
**Who to ask:** Sandeep (mentioned he would share the report document)

- Sandeep mentioned a specific document showing how reports should look.
- Has this been shared? If not, we need it before planning the Reporting module.

---

### 3.5 When will real data be available in the system? [OPEN]
**Who to ask:** Sandeep

- Sandeep mentioned "approximately end of March" for real data.
- Does this mean the onboarding flow will be live and generating real participant data?
- Until then, can we get realistic mock data to develop against?

---

## 4. Voice Onboarding (Module 3 — Future)

### 4.1 What is the exact onboarding form flow? [OPEN]
**Who to ask:** Jill (frontend lead) / Sandeep

- Complete list of onboarding screens and their fields (personal details, medication, stakeholders, communication, risk, documentation)
- Which fields are required vs. optional?
- Field types (text, date, dropdown with options, file upload)?
- Are there conditional fields? (e.g., "if yes to medication, show medication details")

**Why this matters:** The voice assistant needs to know exactly what to ask and in what order.

---

### 4.2 How does the voice assistant interact with the mobile app? [OPEN]
**Who to ask:** Jill (frontend lead)

- When the voice assistant fills a field, does the mobile app update in real time?
- Can the user manually override a voice-filled field?
- What happens if the user navigates away mid-conversation?
- Is the voice icon/UI already being built, or do we need to spec it?

**Why this matters:** This is a two-way sync problem. The voice agent and the mobile UI need to stay in lockstep.

---

## 5. Infrastructure & Environment

### 5.1 What cloud provider is the platform team using? [OPEN]
**Who to ask:** Nishant

- AWS, GCP, Azure, or something else?
- Is there an existing cloud account we should deploy into, or do we set up our own?
- Are there any enterprise agreements or credits with a specific provider?

**Why this matters:** Ideally the AI layer runs in the same cloud as the platform to minimize latency and data transfer costs. If they're on AWS and we choose GCP, we're paying for cross-cloud communication.

---

### 5.2 What is the expected scale? [OPEN]
**Who to ask:** Sandeep

- How many service provider organizations at launch? (10? 50? 200?)
- How many support workers per organization on average?
- How many shifts per day across the platform?
- What's the peak concurrent usage pattern? (e.g., shift changeover times)

**Why this matters:** Determines infrastructure sizing, cost estimates, and whether we need auto-scaling from day one.

---

## Summary: Priority for Next Client Meeting

**Must answer before ANY development starts:**
1. Integration approach (1.1) — API-based or shared DB?
2. Auth system (2.1) — What tokens exist and what's in them?
3. Cloud provider (5.1) — Where does the platform run?

**Must answer before Module 1 (OCR):**
4. Document types for OCR (3.2)

**Must answer before Module 2 (RAG):**
5. Sample NDIS policy documents (3.1)

**Can wait until later:**
- Everything in sections 4 (Voice) and rest of 3 (Case notes, reports)
