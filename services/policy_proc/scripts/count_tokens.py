#!/usr/bin/env python3
"""
Token profiler for a single RAG pipeline query.

Runs every LLM step of the pipeline against the real APIs and reports
input/output token counts per step and the overall total.

Notes:
- KB vector retrieval does not use an LLM — it uses the embedding model.
  Token counts are not returned by the retrieve API.
- Amazon native reranker (ap-northeast-1) does not expose token counts
  via the rerank API. Character count and an estimated token count are
  shown instead (est. = chars / 4).
- Nova reranker prompt mirrors nova_reranker.py — update both if that
  prompt changes.

Usage:
    python scripts/count_tokens.py "what is the safeguarding policy?"
    python scripts/count_tokens.py "what is the leave policy?" --org-id org_sunrise
    python scripts/count_tokens.py "what is the incident policy?" --org-id org_horizons --role coordinator
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

import boto3

from config import (
    REGION,
    RERANK_REGION,
    CLASSIFIER_MODEL,
    REWRITER_MODEL,
    RERANKER_MODEL,
    GENERATION_MODEL,
    AMAZON_RERANK_MODEL_ID,
    AMAZON_RERANK_MODEL_ARN,
    KB_ID,
    NUM_RESULTS,
    RERANK_TOP,
    EMBED_MODEL,
    MESSAGES,
)
from classifier import CLASSIFIER_PROMPT
from rewriter import REWRITER_PROMPT
from retriever import build_filter, boost_org_chunks, is_noise_chunk
from prompt import SYSTEM_PROMPTS, ACTIVE_PROMPT_VERSION


# ── Data ───────────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    note: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ── Args ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Token profiler for a single RAG pipeline query.")
    p.add_argument("question", help="The question to profile.")
    p.add_argument("--org-id", default=None, help="Org ID (e.g. org_sunrise, org_horizons, ndis).")
    p.add_argument("--role", default=None, help="User role (e.g. coordinator, support_worker).")
    p.add_argument("--recent-turns", default="", help="Recent conversation context as plain text.")
    return p.parse_args()


# ── Step functions ─────────────────────────────────────────────────────────────

def run_classify(question: str, recent_turns: str, client) -> StepResult:
    ctx = f"\nRecent conversation context:\n{recent_turns}\n" if recent_turns else ""
    prompt = f"{CLASSIFIER_PROMPT}\n{ctx}\nUser message: {question}\n\nClassification:"
    resp = client.converse(
        modelId=CLASSIFIER_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    u = resp.get("usage", {})
    return StepResult(
        "Classifier", CLASSIFIER_MODEL,
        u.get("inputTokens", 0), u.get("outputTokens", 0),
    )


def run_rewrite(question: str, recent_turns: str, client) -> tuple[str, StepResult]:
    ctx = f"\nRecent conversation context:\n{recent_turns}\n" if recent_turns else ""
    prompt = f"{REWRITER_PROMPT}\n{ctx}\nUser question: {question}\n\nRewritten search query:"
    resp = client.converse(
        modelId=REWRITER_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 30, "temperature": 0.0},
    )
    u = resp.get("usage", {})
    rewritten = resp["output"]["message"]["content"][0]["text"].strip()
    return rewritten, StepResult(
        "Query Rewriter", REWRITER_MODEL,
        u.get("inputTokens", 0), u.get("outputTokens", 0),
    )


def run_retrieve(question: str, org_id: str | None, agent_client) -> tuple[list, StepResult]:
    cfg: dict = {"vectorSearchConfiguration": {"numberOfResults": NUM_RESULTS}}
    doc_filter = build_filter(org_id)
    if doc_filter:
        cfg["vectorSearchConfiguration"]["filter"] = doc_filter

    resp = agent_client.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration=cfg,
    )
    raw_chunks = resp.get("retrievalResults", [])
    content_chunks = [c for c in raw_chunks if not is_noise_chunk(c)]
    boosted = boost_org_chunks(content_chunks, org_id)

    note = (
        f"{len(raw_chunks)} raw → {len(content_chunks)} after noise filter "
        f"→ {len(boosted)} boosted | vector search, no LLM tokens"
    )
    return boosted, StepResult("KB Retrieval", EMBED_MODEL, note=note)


def run_amazon_rerank(question: str, chunks: list, rerank_client) -> tuple[list, StepResult]:
    if not chunks:
        return [], StepResult("Amazon Reranker", AMAZON_RERANK_MODEL_ID, note="skipped — no chunks")

    top_n = min(RERANK_TOP, len(chunks))
    sources = []
    total_chars = 0
    for c in chunks:
        uri = c.get("location", {}).get("s3Location", {}).get("uri", "")
        text = c.get("content", {}).get("text", "")
        body = f"Source: {uri}\n\n{text}"
        total_chars += len(body)
        sources.append({
            "type": "INLINE",
            "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": body}},
        })

    resp = rerank_client.rerank(
        queries=[{"type": "TEXT", "textQuery": {"text": question}}],
        sources=sources,
        rerankingConfiguration={
            "type": "BEDROCK_RERANKING_MODEL",
            "bedrockRerankingConfiguration": {
                "modelConfiguration": {"modelArn": AMAZON_RERANK_MODEL_ARN},
                "numberOfResults": top_n,
            },
        },
    )
    reranked = []
    for item in resp.get("results", []):
        chunk = dict(chunks[item["index"]])
        chunk["amazon_rerank_score"] = item.get("relevanceScore")
        reranked.append(chunk)

    note = (
        f"API does not expose token counts | {len(chunks)} sources sent | "
        f"~{total_chars:,} chars | ~{total_chars // 4:,} est. tokens"
    )
    return reranked, StepResult("Amazon Reranker", AMAZON_RERANK_MODEL_ID, note=note)


def run_nova_rerank(question: str, chunks: list, client) -> tuple[list, StepResult]:
    # Prompt mirrors nova_reranker.py — keep in sync if that prompt changes.
    if not chunks:
        return [], StepResult("Nova Reranker", RERANKER_MODEL, note="skipped — no chunks")

    top_n = min(RERANK_TOP, len(chunks))
    chunk_texts = "\n\n".join([
        f"[{i}] {c['content']['text'][:500]}"
        for i, c in enumerate(chunks)
    ])
    prompt = f"""You are a relevance ranker for an NDIS policy assistant.

Given a question and {len(chunks)} text chunks, return the indices of the {top_n} most relevant chunks in order of relevance (most relevant first).

PRIORITY RULES:
1. Chunks from organisation-specific policy documents are MORE relevant than general NDIS documents when the question asks about a specific organisation's policy or procedure.
2. If the question mentions a specific organisation (e.g. "Horizons", "Sunrise"), rank that organisation's chunks highest even if NDIS chunks appear more semantically similar.
3. Only rank NDIS chunks first if the question is clearly about general NDIS guidelines with no org-specific context.
4. Never rank a chunk from Organisation A above a chunk from Organisation B if the question specifically asks about Organisation B.

Return ONLY a JSON array of indices like: [3, 0, 7, 2, 5]
No explanation, no other text.

Question: {question}

Chunks:
{chunk_texts}"""

    resp = client.converse(
        modelId=RERANKER_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    u = resp.get("usage", {})
    raw = resp["output"]["message"]["content"][0]["text"].strip()
    try:
        indices = json.loads(raw)
        reranked = [chunks[i] for i in indices if i < len(chunks)]
    except Exception:
        reranked = chunks[:top_n]

    return reranked, StepResult(
        "Nova Reranker", RERANKER_MODEL,
        u.get("inputTokens", 0), u.get("outputTokens", 0),
    )


def run_generate(question: str, chunks: list, recent_turns: str, client) -> StepResult:
    if not chunks:
        return StepResult("Generator", GENERATION_MODEL, note="skipped — no context retrieved")

    context = "\n\n".join([c["content"]["text"] for c in chunks])
    mem = f"\n## Recent conversation\n{recent_turns}\n" if recent_turns else ""

    user_msg = f"""
You must ONLY use the information explicitly provided in the policy context below to answer the question.

STRICT RULES:
- If the answer is clearly in the context → answer from it
- If the answer is partially in the context → answer only what is covered, say the rest isn't available
- If the answer is NOT in the context at all → respond exactly with: "{MESSAGES['NOT_IN_KB']}"
- NEVER use your own knowledge, training data, or general understanding to answer
- NEVER make assumptions or inferences beyond what is explicitly stated
- NEVER generate salary figures, timeframes, or policy details that aren't in the context

Source rules:
- Answer ONLY from the policy context provided below
- Do not mention NDIS guidelines vs organisation policy distinction
- Do not suggest the user check other sources unless the answer is genuinely incomplete
- The context you receive is already scoped to the correct source for this user and question, so always answer from it without caveats.

{mem}

## Policy context
{context}

## Current question
{question}

## Special instruction
If the question is a greeting or conversational message (hi, hello, good morning, thanks, etc.)
with no policy context available — respond warmly in 1 sentence and invite a policy question.
Do not use the NOT_IN_KB message for greetings.
"""

    resp = client.converse(
        modelId=GENERATION_MODEL,
        system=[{"text": SYSTEM_PROMPTS[ACTIVE_PROMPT_VERSION]}],
        messages=[{"role": "user", "content": [{"text": user_msg}]}],
        inferenceConfig={"temperature": 0.3, "maxTokens": 1024},
    )
    u = resp.get("usage", {})
    return StepResult(
        "Generator", GENERATION_MODEL,
        u.get("inputTokens", 0), u.get("outputTokens", 0),
    )


# ── Report ─────────────────────────────────────────────────────────────────────

def print_report(question: str, rewritten: str, steps: list[StepResult]) -> None:
    W = 96
    BAR = "─" * W

    print()
    print("═" * W)
    print("  TOKEN PROFILE")
    print(f"  Query    : {question}")
    if rewritten and rewritten != question:
        print(f"  Rewritten: {rewritten}")
    print("═" * W)
    print(f"  {'Step':<26} {'Model':<38} {'Input':>9} {'Output':>9} {'Total':>9}")
    print(f"  {BAR}")

    total_in = total_out = 0
    for i, s in enumerate(steps, 1):
        has_tokens = s.input_tokens or s.output_tokens
        if has_tokens:
            tcols = f"{s.input_tokens:>9,} {s.output_tokens:>9,} {s.total_tokens:>9,}"
        else:
            tcols = f"{'—':>9} {'—':>9} {'—':>9}"
        label = f"{i}. {s.name}"
        print(f"  {label:<26} {s.model:<38} {tcols}")
        if s.note:
            print(f"     └─ {s.note}")
        total_in += s.input_tokens
        total_out += s.output_tokens

    total = total_in + total_out
    print(f"  {BAR}")
    print(
        f"  {'TOTAL (LLM steps)':<26} {'':38} "
        f"{total_in:>9,} {total_out:>9,} {total:>9,}"
    )
    print("═" * W)
    print()


# ── Save ───────────────────────────────────────────────────────────────────────

def save_result(question: str, rewritten: str, steps: list[StepResult]) -> Path:
    out_dir = ROOT / "logs" / "tokens"
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path = out_dir / "token_history.json"

    total_in = sum(s.input_tokens for s in steps)
    total_out = sum(s.output_tokens for s in steps)

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "question": question,
        "rewritten": rewritten if rewritten != question else None,
        "steps": [
            {
                "name": s.name,
                "model": s.model,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "total_tokens": s.total_tokens,
                **({"note": s.note} if s.note else {}),
            }
            for s in steps
        ],
        "totals": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
        },
    }

    history: list = []
    if history_path.exists():
        with open(history_path, encoding="utf-8") as f:
            history = json.load(f)
    history.append(entry)
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    return history_path


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    question = args.question.strip()

    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    agent = boto3.client("bedrock-agent-runtime", region_name=REGION)
    reranker = boto3.client("bedrock-agent-runtime", region_name=RERANK_REGION)

    steps: list[StepResult] = []
    rewritten = question
    chunks: list = []

    print(f"\nProfiling: {question!r}\n")

    try:
        print("  [1/5] Classifier...")
        steps.append(run_classify(question, args.recent_turns, bedrock))
    except Exception as e:
        print(f"        ERROR: {e}")
        steps.append(StepResult("Classifier", CLASSIFIER_MODEL, note=f"error: {e}"))

    try:
        print("  [2/5] Query Rewriter...")
        rewritten, rw_step = run_rewrite(question, args.recent_turns, bedrock)
        steps.append(rw_step)
        if rewritten != question:
            print(f"        → {rewritten!r}")
    except Exception as e:
        print(f"        ERROR: {e}")
        steps.append(StepResult("Query Rewriter", REWRITER_MODEL, note=f"error: {e}"))

    try:
        print("  [3/5] KB Retrieval...")
        chunks, ret_step = run_retrieve(rewritten, args.org_id, agent)
        steps.append(ret_step)
        print(f"        → {len(chunks)} usable chunks")
    except Exception as e:
        print(f"        ERROR: {e}")
        steps.append(StepResult("KB Retrieval", EMBED_MODEL, note=f"error: {e}"))

    print("  [4/5] Reranker (Amazon primary → Nova fallback)...")
    reranked_chunks: list = chunks
    try:
        reranked_chunks, amz_step = run_amazon_rerank(question, chunks, reranker)
        steps.append(amz_step)
        print("        → Amazon reranker succeeded")
    except Exception as e:
        print(f"        Amazon failed ({e}), falling back to Nova...")
        steps.append(StepResult("Amazon Reranker", AMAZON_RERANK_MODEL_ID, note=f"failed: {e} → Nova fallback used"))
        try:
            reranked_chunks, nova_step = run_nova_rerank(question, chunks, bedrock)
            nova_step.note = "fallback — Amazon reranker failed"
            steps.append(nova_step)
            print("        → Nova fallback succeeded")
        except Exception as e2:
            print(f"        Nova also failed ({e2}), using original order")
            steps.append(StepResult("Nova Reranker", RERANKER_MODEL, note=f"fallback also failed: {e2}"))

    try:
        print("  [5/5] Generator...")
        steps.append(run_generate(question, reranked_chunks, args.recent_turns, bedrock))
    except Exception as e:
        print(f"        ERROR: {e}")
        steps.append(StepResult("Generator", GENERATION_MODEL, note=f"error: {e}"))

    print_report(question, rewritten, steps)
    saved = save_result(question, rewritten, steps)
    print(f"  Results saved → {saved}\n")


if __name__ == "__main__":
    main()
