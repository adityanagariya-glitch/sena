# NDIS Restrictive Practice Detection: AI Pipeline Implementation Guide

## 1. Pipeline Overview
This document outlines the step-by-step implementation of a Hybrid Agentic Workflow designed to detect NDIS regulated restrictive practices from support worker case notes. This architecture prioritizes low latency, cost-efficiency, and strict regulatory compliance by utilizing a multi-stage process: Triage, Targeted Retrieval, LLM Evaluation, and Deterministic Cross-Checking.

## 2. Prerequisites & Tech Stack Recommendations
* **Orchestration:** LangChain, LlamaIndex, or a custom Python-based state machine (e.g., LangGraph) for agentic flow.
* **Triage Model:** A fast, cost-effective LLM (e.g., Gemini 1.5 Flash, Claude 3 Haiku, or GPT-4o-mini).
* **Evaluator Model:** A high-reasoning LLM (e.g., Gemini 1.5 Pro, Claude 3.5 Sonnet, or GPT-4o).
* **Vector Database:** Pinecone, Weaviate, or pgvector for storing chunked NDIS policy documents.
* **Backend Database:** Relational DB (e.g., PostgreSQL) holding client Behaviour Support Plans and provider policies.

---

## 3. Implementation Steps

### Step 1: Document Ingestion & Vector DB Setup (The Knowledge Base)
1.  **Ingest NDIS PDFs:** Extract text from the official NDIS documents (Regulated Restrictive Practices Guide, Safe Transportation Guide, etc.).
2.  **Chunking Strategy:** Use semantic chunking to ensure rules are not split mid-sentence. 
3.  **Metadata Tagging:** Tag each chunk heavily with metadata. This is critical for Targeted RAG.
    * `category`: e.g., "Chemical Restraint", "Seclusion".
    * `document_source`: e.g., "Safe Transportation Guide 2022".
    * `risk_level`: e.g., "High Risk", "Prohibited".
4.  **Embed and Store:** Embed the chunks using a standard embedding model and store them in the Vector DB.

### Step 2: Build the Triage Classifier (Fast & Cheap)
Create a lightweight function to act as the gatekeeper.

* **Input:** Raw case note transcript.
* **System Prompt:** > "You are a triage classifier for NDIS support worker notes. Does the following text mention or imply: holding a person, locking doors, preventing movement, giving medication for behavior/agitation, using harnesses/belts, or restricting access to personal items? Output ONLY 'YES' or 'NO'."
* **Routing Logic:**
    * If `NO`: Save case note normally, exit pipeline.
    * If `YES`: Proceed to Step 3.

### Step 3: Targeted RAG (The Policy Expert)
Extract the specific action and retrieve *only* the relevant policies.

1.  **Action Extraction:** Ask the Triage model to output a 1-sentence summary of the suspicious action (e.g., "Worker administered PRN Diazepam for agitation").
2.  **Query Formulation:** Convert that summary into a query for the Vector DB.
3.  **Metadata Filtering:** Retrieve the top 3-5 chunks, strictly filtering by the relevant categories detected. Do not retrieve the entire manual.

### Step 4: The Evaluator Agent (Strict Formatting)
Run the extracted action against the retrieved policy rules to generate a structured risk assessment.

* **Inputs:** Raw transcript, Extracted Action, Retrieved NDIS Policy Chunks.
* **System Prompt:** > "Evaluate the worker's action against the provided NDIS rules. Determine if a restrictive practice occurred. You must output your response in the following JSON schema."
* **Expected JSON Schema:**
    ```json
    {
      "incident_detected": true,
      "practice_category": "Chemical Restraint",
      "action_summary": "Administered PRN Diazepam in response to pacing and agitation.",
      "policy_violation_risk": "High",
      "reasoning": "Medication was used to control behavior, which constitutes chemical restraint under NDIS guidelines."
    }
    ```

### Step 5: Deterministic Cross-Checking (The Safety Net)
Map the LLM's JSON output to your actual database to determine authorization.

1.  **Parse JSON:** Extract `practice_category` and `client_id`.
2.  **Database Query:** * `SELECT * FROM behaviour_support_plans WHERE client_id = 'XYZ' AND practice_type = 'Chemical Restraint' AND status = 'Active';`
3.  **Final Logic Check:**
    * If query returns NO results -> Flag as **"Unauthorised Restrictive Practice"** -> Trigger Manager Alert.
    * If query returns YES -> Cross-reference dosage/conditions -> Flag as **"Authorised Use (Review Required)"**.

---

## 4. Final Output to Dashboard
Construct a final payload combining the LLM's reasoning and the deterministic database check. Send this payload to the frontend Risk Dashboard for manager review and official NDIS incident reporting if required.
