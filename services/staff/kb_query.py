"""Multi-KB RAG helper.

Implements Option B from the multi-KB plan: parallel `retrieve` across all
configured Bedrock Knowledge Bases, merge top-K chunks by score, then a single
streaming generate call with the merged context.

Latency profile (~2 KBs):
  - retrieve (parallel)        ≈ 400 ms  (max of the two)
  - merge / dedupe             ≈ 10 ms
  - converse_stream generate   ≈ 1.5–3 s
  - total                      ≈ 2.0–3.5 s  (same as single-KB baseline)

Cost: ~1.1× single-KB (extra retrieve calls are cheap; one generate stays).
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from config import (
    VERBOSE,
    BEDROCK_KB_IDS,
    bedrock_agent_runtime,
)
from bedrock_client import call_bedrock, call_bedrock_stream


# Top-N chunks to keep per KB before merging
_PER_KB_TOP_K = 5
# Top-N final merged chunks (across all KBs) fed to the generate call
_FINAL_TOP_K = 8


def _rewrite_query_for_retrieval(question: str) -> str:
    """Rewrite a possibly-conversational question into a self-contained search
    query, using recent conversation history for context.

    Equivalent to what Bedrock's orchestrationConfiguration.promptTemplate did
    under the single-KB retrieve_and_generate API. e.g. "what about that policy?"
    becomes "sleepover shift pay policy" when the prior turn discussed sleepovers.

    Falls back to the original question on any error — never breaks the flow.
    """
    try:
        # Lazy import to avoid circular deps (state imports config which imports this indirectly)
        from state import conversation_history

        if not conversation_history:
            return question

        history_lines = []
        for turn in conversation_history[-4:]:
            role = (turn.get("role") or "").upper()
            for part in turn.get("content") or []:
                if isinstance(part, dict) and part.get("text"):
                    text = part["text"]
                    if len(text) > 400:
                        text = text[:400] + "…"
                    history_lines.append(f"{role}: {text}")
        if not history_lines:
            return question

        system_prompt = (
            "You rewrite a user's latest question into a concise, self-contained "
            "search query for an NDIS policy/procedure knowledge base. Use the "
            "recent conversation only to resolve references (e.g. 'that policy', "
            "'it', 'them'). Preserve every concrete detail (names, dates, topics). "
            "Return ONLY the rewritten query — one short line, no quotes, no preamble."
        )
        history_block = "\n".join(history_lines)
        messages = [{
            "role": "user",
            "content": [{
                "text": f"Recent conversation:\n{history_block}\n\nLatest question: {question}\n\nRewritten search query:",
            }],
        }]
        rewritten = call_bedrock(messages, system_prompt, use_guardrail=False)
        rewritten = (rewritten or "").strip().strip('"').strip("'")
        # Sanity: don't accept an absurdly long rewrite, fallback to original
        if rewritten and 3 <= len(rewritten) <= 500:
            if VERBOSE:
                print(f"[kb-query] rewrite: {question!r} → {rewritten!r}", file=sys.stderr)
            return rewritten
    except Exception as e:
        if VERBOSE:
            print(f"[kb-query] rewrite failed ({type(e).__name__}: {e}) — using original", file=sys.stderr)
    return question


def _retrieve_one(kb_id: str, question: str) -> list[dict]:
    """Vector-search a single KB. Returns a list of {text, score, kb_id, location}."""
    try:
        resp = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": question},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": _PER_KB_TOP_K},
            },
        )
    except Exception as e:
        if VERBOSE:
            print(f"[kb-query] retrieve failed on {kb_id}: {type(e).__name__}: {e}", file=sys.stderr)
        return []

    results = []
    for r in resp.get("retrievalResults", []) or []:
        content = (r.get("content") or {}).get("text", "") or ""
        if not content.strip():
            continue
        results.append({
            "text": content,
            "score": float(r.get("score", 0.0)),
            "kb_id": kb_id,
            "location": r.get("location"),
        })
    return results


def _retrieve_parallel(question: str, kb_ids: Iterable[str]) -> list[dict]:
    """Fan-out retrieve across all KBs; gather results."""
    kb_ids = list(kb_ids)
    if not kb_ids:
        return []
    if len(kb_ids) == 1:
        return _retrieve_one(kb_ids[0], question)

    chunks: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(kb_ids)) as ex:
        futures = {ex.submit(_retrieve_one, kb, question): kb for kb in kb_ids}
        for fut in as_completed(futures):
            chunks.extend(fut.result())
    return chunks


def _merge_top_k(chunks: list[dict], k: int = _FINAL_TOP_K) -> list[dict]:
    """Sort by score descending, dedupe near-identical texts, return top K."""
    seen_prefixes: set[str] = set()
    deduped: list[dict] = []
    chunks_sorted = sorted(chunks, key=lambda c: c["score"], reverse=True)
    for c in chunks_sorted:
        prefix = c["text"][:120].strip().lower()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        deduped.append(c)
        if len(deduped) >= k:
            break
    return deduped


def _format_chunks_for_prompt(chunks: list[dict]) -> str:
    """Render merged chunks into the $search_results$ replacement block."""
    if not chunks:
        return "(no relevant reference material found)"
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(f"[ref {i}]\n{c['text'].strip()}")
    return "\n\n".join(lines)


def query_kbs(question: str, system_prompt: str, kb_ids: Iterable[str] | None = None) -> tuple[str, list[dict]]:
    """Run multi-KB RAG: parallel retrieve + merged single generate.

    Returns (answer_text, merged_chunks). `answer_text` is the full reply
    (already streamed to stdout via call_bedrock_stream).
    """
    if kb_ids is None:
        kb_ids = BEDROCK_KB_IDS

    kb_ids = [k for k in (kb_ids or []) if k]
    if not kb_ids:
        return "", []

    # Rewrite the user's question into a self-contained search query using
    # conversation context (same job the old orchestration_template did).
    search_query = _rewrite_query_for_retrieval(question)

    if VERBOSE:
        print(f"[kb-query] retrieving from {len(kb_ids)} KB(s) in parallel", file=sys.stderr)

    all_chunks = _retrieve_parallel(search_query, kb_ids)
    merged = _merge_top_k(all_chunks)

    if VERBOSE:
        per_kb = {}
        for c in all_chunks:
            per_kb[c["kb_id"]] = per_kb.get(c["kb_id"], 0) + 1
        print(f"[kb-query] retrieved {len(all_chunks)} chunks ({per_kb}), kept top {len(merged)}", file=sys.stderr)

    if not merged:
        return "", []

    # Embed merged chunks in the system prompt (replaces $search_results$)
    chunk_block = _format_chunks_for_prompt(merged)
    final_system_prompt = (
        f"{system_prompt}\n\n"
        f"Internal reference material (do not mention to the user):\n{chunk_block}"
    )

    messages = [{"role": "user", "content": [{"text": question}]}]
    # KB reference material is trusted vetted content — skip guardrails on the
    # internal text (the call_bedrock_stream still applies guardrails on the
    # final output). Use streaming so the user sees tokens as they arrive.
    answer = call_bedrock_stream(messages, system_prompt=final_system_prompt, use_guardrail=True)
    return answer or "", merged
