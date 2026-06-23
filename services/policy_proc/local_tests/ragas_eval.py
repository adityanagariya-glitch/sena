"""
RAGAs Evaluation Script — Bedrock KB + Claude as Judge
=======================================================
Metrics (all LLM-judged, no token overlap):
  - Faithfulness         : Is the answer grounded in the retrieved context?
  - Answer Relevancy     : Is the answer relevant to the question?
  - Context Precision    : Are retrieved chunks relevant to the question?
  - Context Recall       : Did retrieval capture everything needed from ground truth?
  - Answer Correctness   : Is the answer factually correct vs ground truth?

Sheets evaluated:
  - Bedrock Eval Dataset     (13 primary questions)
  - Negative Test Cases      (13 adversarial questions)
  - Paraphrased Variants     (robustness test)

Install:
    pip install ragas langchain-aws langchain pandas openpyxl

Run:
    python rag_ragas_eval.py
"""
import json
from datetime import datetime
import boto3
import pandas as pd
import time
import warnings
warnings.filterwarnings("ignore")

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scripts.pipeline import run_pipeline
from scripts.config import REGION, KB_ID, GENERATION_MODEL, JUDGE_MODEL, EMBED_MODEL

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness,)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_aws import ChatBedrock, BedrockEmbeddings
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# ── CONFIG ────────────────────────────────────────────────────────────────────
RAG_MODEL_ID  = GENERATION_MODEL      # model that answers questions
JUDGE_MODEL_ID = JUDGE_MODEL          # model that judges answers
EMBED_MODEL_ID = EMBED_MODEL          # for answer relevancy metric
NUM_RESULTS   = 5
SLEEP_BETWEEN = 10                                   # seconds between RAG calls
INPUT_FILE    = r"C:\Users\BAPS\Documents\SENA_RAG\gt_eval_dataset\gold_dataset_v2.xlsx"
OUTPUT_FILE   = r"C:\Users\BAPS\Documents\SENA_RAG\ragas_outputs\ragas_results_gold_dataset_v2.xlsx"

SYSTEM_PROMPT = """You are a knowledgeable and caring policy assistant for an NDIS (National Disability Insurance Scheme) support organisation in Australia. You help staff and stakeholders understand NDIS guidelines and organisation-level policies.

## Scope
You ONLY answer questions based on the NDIS policies and organisation procedures in your knowledge base.
If a question is not related to NDIS, disability support, or this organisation's policies — respond with:
"I can only help with NDIS policies and organisation procedures. Please ask a relevant question."
Do not answer general knowledge, technology, or any out-of-scope questions even if you know the answer.

When answering, follow this priority order:
## Source Priority
1. **Organisation policy is the ONLY source** — if the question can be answered from the organisation's own policy documents, answer from those only. Never supplement with NDIS docs even if the org answer is incomplete.
2. **Incomplete org answer** — if the org policy covers the topic but lacks detail, answer only what is explicitly stated. Do not fill gaps with NDIS knowledge. Say: "Your organisation's policy covers this but doesn't provide further detail. Check with your supervisor for more information."
3. **NDIS as fallback only** — use NDIS docs ONLY if the org has no policy on this topic at all. When using NDIS, always say: "Your organisation doesn't appear to have a specific policy on this. Based on NDIS guidelines: [answer]. Check with your supervisor if your organisation has its own procedure."
4. **Contradictions** — always follow organisation policy over NDIS.
Never mix sources without clearly indicating which source the information comes from.

## Memory and Conversation Context
You may be provided with:
- Recent conversation history — use it to understand follow-up questions and maintain continuity
- Facts about the user from past sessions — use these to personalise responses appropriately

When conversation history is present:
- Refer back naturally — "As we discussed..." or "Building on what I mentioned..."
- Never repeat information already covered unless the user asks
- Resolve ambiguous references using context — "that policy" or "it" should be resolved from history
- If context is missing or unclear, ask one focused clarifying question

## Australian Style
- Use Australian English spelling — organisation, recognise, behaviour, programme, practitioner, authorised
- Be warm and direct — Australians value straight talk without corporate fluff
- Use "get in touch" not "reach out", "staff" not "team members", "organisation" not "organization"
- Use inclusive, person-first language consistent with NDIS values — "person with disability" not "disabled person"
- Never make assumptions about a user's background, culture, or identity
- Be professional but conversational — like a knowledgeable colleague, not a helpdesk robot
- Use "you" and "your" naturally — "Here's what you need to do" not "The following steps should be taken"

## Response Format — Adapt Intelligently
Match the format to the question type:

**Simple factual question** (e.g. "What is the notice period?")
→ One or two sentences. No headers. No bullets. Just the answer.

**Process or how-to question** (e.g. "How do I submit an incident report?")
→ Short numbered steps. Bold the action. One sentence per step.
→ End with a clear next step the user should take right now.

**Explanation or clarification** (e.g. "What does this policy mean?")
→ Brief conversational prose. Plain English. No jargon.
→ One short paragraph maximum unless complexity requires more.

**Comparison or multi-part question**
→ Use bullet points or a simple table only where it genuinely aids clarity.
→ Keep each point to one sentence.

**Distress or urgent situation** (e.g. "I made a mistake and don't know what to do")
→ Lead with acknowledgement — be warm and calm first
→ Then give clear, actionable steps
→ End with encouragement and a next step

## Formatting Rules
- Never use headers (##) for simple answers — only for multi-section responses
- Never pad with "Great question!", "Certainly!", or "According to the policy document..."
- Never repeat the question back
- Never use bold for entire sentences — only for key terms or action words
- Keep responses concise — say everything needed, nothing more
- If a policy has a specific reference number or section, mention it briefly
- Always use Australian English spelling throughout
- If the answer requires action, always end with a clear next step
- Never end with "Would you like me to..." or offer to elaborate unprompted

## Accuracy Rules
- Only answer based on what is explicitly stated in the retrieved policy context
- Do not infer, extrapolate, or use general NDIS knowledge outside what is provided
- If the answer is not clearly in the context, say: "This isn't covered in the policies I have access to. You may want to check directly with your supervisor or the NDIS Commission."
- Never guess or make up policy details
- If a question has multiple valid answers depending on context, acknowledge this briefly

## Context
You have access to NDIS guidelines and organisation-specific policies. Always prioritise organisation policy over general NDIS guidance when they differ."""


# ── AWS CLIENTS ───────────────────────────────────────────────────────────────
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
bedrock_runtime       = boto3.client("bedrock-runtime",       region_name=REGION)

# ── RAGAs JUDGE SETUP ─────────────────────────────────────────────────────────
judge_llm = ChatBedrock(
    model_id=JUDGE_MODEL_ID,
    client=bedrock_runtime,
    model_kwargs={"temperature": 0, "max_tokens": 3000}
)
embeddings = BedrockEmbeddings(
    model_id=EMBED_MODEL_ID,
    client=bedrock_runtime
)
ragas_llm    = LangchainLLMWrapper(judge_llm)
ragas_embeds = LangchainEmbeddingsWrapper(embeddings)

METRICS = [
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness,
]


# ── RAG PIPELINE ──────────────────────────────────────────────────────────────
def run_rag(question):
    retrieve_resp = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": NUM_RESULTS}
        }
    )
    chunks = retrieve_resp["retrievalResults"]
    contexts = [c["content"]["text"] for c in chunks]
    context_text = "\n\n".join(contexts)

    user_message = f"""Use the following policy context to answer the question.

Context:
{context_text}

Question: {question}"""

    response = bedrock_runtime.converse(
        modelId=RAG_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user_message}]}]
    )
    answer = response["output"]["message"]["content"][0]["text"]
    return answer, contexts


# ── PROCESS A SHEET ───────────────────────────────────────────────────────────
def process_sheet(df, question_col="prompt"):
    questions, answers, contexts_list, ground_truths = [], [], [], []
    total = len(df)

    for i, row in df.iterrows():
        question     = str(row.get(question_col, ""))
        ground_truth = str(row.get("ground_truth", ""))

        print(f"  [{i+1}/{total}] {question[:70]}...")

        try:
            result = run_pipeline(question)

            if result["blocked"]:
                answer   = result["answer"]
                contexts = [""]
            else:
                answer   = result["answer"]
                contexts = [c for c in result.get("sources", [])] or [""]

                # get actual chunk texts from retriever directly for RAGAs
                from scripts.retriever import retrieve
                _, context_text, _ = retrieve(question)
                contexts = [context_text] if context_text else [""]

        except Exception as e:
            print(f"    Error: {e}")
            answer   = f"ERROR: {e}"
            contexts = [""]

        questions.append(question)
        answers.append(answer)
        contexts_list.append(contexts)
        ground_truths.append(ground_truth)
        time.sleep(SLEEP_BETWEEN)

    dataset = Dataset.from_dict({
        "question":     questions,
        "answer":       answers,
        "contexts":     contexts_list,
        "ground_truth": ground_truths,
    })

    print("  🔍 Running RAGAs evaluation (LLM-as-judge)...")
    result = evaluate(
        dataset,
        metrics=METRICS,
        llm=ragas_llm,
        embeddings=ragas_embeds,
        raise_exceptions=False,
    )

    result_df = result.to_pandas()
    result_df.insert(0, "question",     questions)
    result_df.insert(1, "ground_truth", ground_truths)
    result_df.insert(2, "answer",       answers)

    return result_df

# ── FORMATTING ────────────────────────────────────────────────────────────────
def style_results_sheet(ws):
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    body_font   = Font(name="Arial", size=10)
    score_cols  = ["D", "E", "F", "G", "H"]   # RAGAs metric columns

    for cell in ws[1]:
        cell.fill      = header_fill
        cell.font      = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font      = body_font
            cell.alignment = Alignment(
                horizontal="center" if cell.column > 3 else "left",
                vertical="center",
                wrap_text=True
            )
            if cell.column_letter in score_cols and cell.value not in (None, ""):
                try:
                    val = float(cell.value)
                    if val >= 0.75:
                        cell.fill = PatternFill("solid", fgColor="C6EFCE")
                    elif val >= 0.5:
                        cell.fill = PatternFill("solid", fgColor="FFEB9C")
                    else:
                        cell.fill = PatternFill("solid", fgColor="FFC7CE")
                except:
                    pass

    col_widths = {1: 45, 2: 45, 3: 50, 4: 16, 5: 16, 6: 16, 7: 16, 8: 18}
    for col_num, width in col_widths.items():
        if col_num <= ws.max_column:
            ws.column_dimensions[get_column_letter(col_num)].width = width

    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"


def add_summary(wb, primary_df, negative_df, para_df):
    ws = wb.create_sheet("Summary")

    metric_cols = [
        "faithfulness", "answer_relevancy",
        "context_precision", "context_recall", "answer_correctness"
    ]

    def avg(df, col):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            return round(vals.mean(), 4) if len(vals) else "N/A"
        return "N/A"

    headers = ["Metric", "Primary (13 Qs)", "Negative (13 Qs)", "Paraphrase Variants"]
    ws.append(headers)

    for m in metric_cols:
        ws.append([m, avg(primary_df, m), avg(negative_df, m), avg(para_df, m)])

    # What each metric means
    ws.append([])
    ws.append(["Metric", "What it measures", "Ideal score"])
    explanations = [
        ["faithfulness",       "Is the answer grounded in retrieved context? (no hallucination)", ">= 0.85"],
        ["answer_relevancy",   "Is the answer relevant to the question asked?",                   ">= 0.80"],
        ["context_precision",  "Are retrieved chunks actually useful for the question?",           ">= 0.80"],
        ["context_recall",     "Did retrieval capture everything needed from ground truth?",       ">= 0.75"],
        ["answer_correctness", "Is the answer factually correct vs ground truth?",                ">= 0.75"],
    ]
    for row in explanations:
        ws.append(row)

    # Style
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", name="Arial", size=11)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for col in ["A", "B", "C", "D"]:
        ws.column_dimensions[col].width = 30
    ws.freeze_panes = "A2"

#---logging---------------------------------------------------------------
def log_eval_run(primary_df, run_notes=""):
    """Logs eval scores to a JSON file for tracking improvement over time."""
    
    log_file = "ragas_outputs/eval_history_v2-1.json"
    
    # Load existing history
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    # Compute scores
    metrics = ["faithfulness", "answer_relevancy", "context_precision", 
               "context_recall", "answer_correctness"]
    
    scores = {}
    for m in metrics:
        if m in primary_df.columns:
            vals = pd.to_numeric(primary_df[m], errors="coerce").dropna()
            scores[m] = round(vals.mean(), 4) if len(vals) else None

    # Log entry
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": run_notes,
        "scores": scores
    }

    history.append(entry)

    with open(log_file, "w") as f:
        json.dump(history, f, indent=2)

    print(f"\n📝 Logged to eval_history.json")
    print(f"   Run: {entry['timestamp']} — {run_notes}")
    for m, s in scores.items():
        print(f"   {m}: {s}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("Reading eval dataset...")
    sheets      = pd.read_excel(INPUT_FILE, sheet_name=None)
    primary_df  = sheets["Gold Eval Dataset"]
    # negative_df = sheets["Negative Test Cases"]
    # para_df     = sheets["Paraphrased Variants"]

    print(f"\n PRIMARY eval ({len(primary_df)} questions)...")
    primary_results = process_sheet(primary_df, question_col="prompt")

    # print(f"\n NEGATIVE eval ({len(negative_df)} questions)...")
    # negative_results = process_sheet(negative_df, question_col="prompt")

    # print(f"\n PARAPHRASE eval ({len(para_df)} questions)...")
    # para_results = process_sheet(para_df, question_col="prompt_variant")

    print("\n Building results Excel...")
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        primary_results.to_excel(writer, sheet_name="Primary Results", index=False)

    wb = load_workbook(OUTPUT_FILE)
    style_results_sheet(wb["Primary Results"])
    wb.save(OUTPUT_FILE)

    print(f"\n Done! Saved to: {OUTPUT_FILE}")
    print("\n=== RAGAS SUMMARY (Primary) ===")
    for col in ["faithfulness", "answer_relevancy", "context_precision",
                "context_recall", "answer_correctness"]:
        if col in primary_results.columns:
            vals = pd.to_numeric(primary_results[col], errors="coerce").dropna()
            if len(vals):
                print(f"  {col}: {vals.mean():.4f}")

    log_eval_run(primary_results, run_notes="fixed classifier Q1/Q10 + Nova Micro reranker")

if __name__ == "__main__":
    main()
