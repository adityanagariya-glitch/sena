# retriever.py
import boto3
import json
import logging
import os
import re
import time
from langfuse import observe, get_client

langfuse = get_client()

from config import (
    REGION,
    KB_ID,
    NUM_RESULTS,
    RERANK_TOP,
    RERANKER_MODEL,
    RERANK_PROVIDER,
    RERANK_COMPARE,
    RERANK_LOG_PATH,
    AMAZON_RERANK_MODEL_ID,
    AMAZON_RERANK_MODEL_ARN,
    RERANK_REGION,
)
from nova_reranker import rerank_with_nova
from amazon_reranker import rerank_with_amazon

logger = logging.getLogger(__name__)

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
# Legacy inline Nova reranker used this client. Active reranking now lives in
# nova_reranker.py and amazon_reranker.py.
# bedrock_runtime       = boto3.client("bedrock-runtime",       region_name=REGION)

# ── Org doc cache ─────────────────────────────────────────────────────────────
# TTL-based: entries expire after 5 min so new uploads are picked up automatically.
_ORG_DOC_CACHE_TTL = 300  # seconds
_org_doc_cache: dict[str, tuple[bool, float]] = {}  # (has_docs, expires_at)

def content_score(chunk: dict) -> float:
    """
    Scores a chunk by information density — 0.0 (pure header/footer) to 1.0 (pure content).
    
    Three signals:
    1. Metadata line ratio  — lines that look like key:value pairs, dates, version numbers
    2. Average words per line — headers/footers have short fragmentary lines
    3. Policy verb presence — must, shall, should, required, ensure, report etc.
    
    Works for any document format (PDF, DOCX), any org, any language style.
    No hardcoded strings — purely structural and linguistic signals.
    """
    text  = chunk["content"]["text"]
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if not lines:
        return 0.0

    # Signal 1 — metadata line ratio
    # Matches: "Key: Value", pipe-separated table rows, date patterns
    metadata_lines = sum(
        1 for l in lines
        if re.search(
            r"(:\s{1,10}\S)|(^\s*\|)|(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})|"
            r"(v\d+\.\d+)|(doc\s*id)|(version\s*\d)|(page\s+\d+\s+of\s+\d+)",
            l, re.IGNORECASE
        )
    )
    metadata_ratio = metadata_lines / len(lines)

    # Signal 2 — average words per line
    # Content chunks have longer sentences; headers/footers have short fragments
    avg_words = sum(len(l.split()) for l in lines) / len(lines)

    # Signal 3 — policy verb density
    # Real policy content contains action verbs
    policy_verbs = len(re.findall(
        r"\b(must|shall|should|may|required|ensure|report|notify|complete|"
        r"submit|document|record|follow|review|assess|identify|manage|"
        r"provide|maintain|support|contact|escalate|advise)\b",
        text, re.IGNORECASE
    ))

    # Signal 4 — footer signals
    # Page numbers, copyright, URLs, confidentiality notices at chunk end
    last_3_lines = " ".join(lines[-3:]).lower()
    footer_signals = sum(1 for pattern in [
        r"page \d+", r"confidential", r"copyright", r"©",
        r"www\.", r"http", r"all rights reserved", r"internal use only",
        r"printed copies are uncontrolled"
    ] if re.search(pattern, last_3_lines, re.IGNORECASE))
    footer_penalty = min(footer_signals * 0.15, 0.4)

    # Combine signals
    score = (
        (1 - metadata_ratio)        * 0.35 +   # low metadata = higher score
        min(avg_words / 12, 1.0)    * 0.25 +   # longer lines = higher score
        min(policy_verbs / 5, 1.0)  * 0.30 +   # more policy verbs = higher score
        0.10                                    # base score
    ) - footer_penalty

    return round(max(score, 0.0), 3)


def is_noise_chunk(chunk: dict, threshold: float = 0.25) -> bool:
    """
    Returns True if chunk is a header or footer with low information density.
    Threshold 0.25 — tune up (0.35) if filtering too little, down (0.15) if too aggressive.
    """
    score = content_score(chunk)
    src   = chunk.get("location", {}).get("s3Location", {}).get("uri", "").split("/")[-1]
    if score < threshold:
        logger.info(f"Noise chunk filtered (score={score}) | {src}")
    return score < threshold


def clear_org_cache(org_id: str = None):
    """
    Clears the org doc cache.
    org_id given → clears just that org.
    None         → clears entire cache.
    """
    if org_id:
        _org_doc_cache.pop(org_id, None)
        logger.info(f"Cache cleared for {org_id}")
    else:
        _org_doc_cache.clear()
        logger.info("Full org doc cache cleared")


def _org_cache_get(org_id: str):
    """Returns cached bool if entry exists and has not expired, else None."""
    entry = _org_doc_cache.get(org_id)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


def org_has_docs(org_id: str) -> bool:
    """
    Checks if the org has any documents indexed in S3 Vectors.
    Result cached for _ORG_DOC_CACHE_TTL seconds — auto-refreshes after new uploads.
    Returns True if at least one chunk exists for this org.
    """
    cached = _org_cache_get(org_id)
    if cached is not None:
        logger.info(f"org_has_docs cache hit — {org_id}: {cached}")
        return cached

    try:
        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": "policy"},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 1,
                    "filter": {
                        "equals": {"key": "org_id", "value": org_id}
                    }
                }
            }
        )
        result = len(response["retrievalResults"]) > 0
        _org_doc_cache[org_id] = (result, time.time() + _ORG_DOC_CACHE_TTL)
        logger.info(f"org_has_docs — {org_id}: {result} (cached for {_ORG_DOC_CACHE_TTL}s)")
        return result

    except Exception as e:
        logger.warning(f"org_has_docs check failed for {org_id}: {e}")
        return False


def build_filter(org_id: str, doc_type: str = None) -> dict | None:
    """
    Determines the correct metadata filter based on org_id and doc availability.

    Rules:
        superadmin (org_id=ndis) → no filter — sees everything
        org with docs            → org-only filter — never mixed with NDIS
        org without docs         → NDIS-only filter — pure fallback
    """
    if not org_id or org_id == "ndis":
        # Superadmin — no filter
        logger.info("Filter: none (superadmin — all docs)")
        return None

    has_docs = org_has_docs(org_id)
    org_filter = (
        {"equals": {"key": "org_id", "value": org_id}}
        if has_docs
        else {"equals": {"key": "org_id", "value": "ndis"}}
    )

    logger.info(f"Filter: org={'own' if has_docs else 'ndis'} | doc_type={doc_type or 'all'}")

    if not doc_type:
        return org_filter

    return {
        "andAll": [
            org_filter,
            {"equals": {"key": "doc_type", "value": doc_type}}
        ]
    }


def boost_org_chunks(chunks: list, org_id: str) -> list:
    """
    Moves org-specific chunks to the front before reranking.
    Uses org_id from login session — not from question text.
    Ensures org-specific content is prioritised by the reranker
    even when the user doesn't mention their org name in the question.
    """
    if not org_id or org_id == "ndis":
        return chunks

    org_chunks  = [
        c for c in chunks
        if org_id in c.get("location", {}).get("s3Location", {}).get("uri", "")
    ]
    ndis_chunks = [
        c for c in chunks
        if org_id not in c.get("location", {}).get("s3Location", {}).get("uri", "")
    ]

    logger.info(
        f"Chunk boost — org_id: {org_id} | "
        f"org-specific: {len(org_chunks)} | ndis/other: {len(ndis_chunks)}"
    )

    return org_chunks + ndis_chunks


def chunk_key(chunk: dict) -> str:
    src = chunk.get("location", {}).get("s3Location", {}).get("uri", "")
    text = chunk.get("content", {}).get("text", "")
    return f"{src}::{text[:200]}"


def log_rerank_comparison(
    question: str,
    candidates: list,
    nova_chunks: list,
    amazon_chunks: list,
    selected_provider: str
) -> None:
    """
    Writes one JSONL record per query comparing KB rank, Nova rank, and Amazon rank.
    """
    try:
        nova_ranks = {
            chunk_key(chunk): rank
            for rank, chunk in enumerate(nova_chunks, start=1)
        }
        amazon_ranks = {
            chunk_key(chunk): rank
            for rank, chunk in enumerate(amazon_chunks, start=1)
        }
        amazon_scores = {
            chunk_key(chunk): chunk.get("amazon_rerank_score")
            for chunk in amazon_chunks
        }

        records = []
        for kb_rank, chunk in enumerate(candidates, start=1):
            key = chunk_key(chunk)
            src = chunk.get("location", {}).get("s3Location", {}).get("uri", "")
            records.append({
                "source": src.split("/")[-1],
                "source_uri": src,
                "kb_rank": kb_rank,
                "kb_score": chunk.get("score"),
                "nova_rank": nova_ranks.get(key),
                "amazon_rank": amazon_ranks.get(key),
                "amazon_score": amazon_scores.get(key),
                "content_preview": chunk.get("content", {}).get("text", "")[:250]
            })

        payload = {
            "question": question,
            "retrieval_region": REGION,
            "selected_provider": selected_provider,
            "nova_model": RERANKER_MODEL,
            "amazon_model": AMAZON_RERANK_MODEL_ID,
            "amazon_model_arn": AMAZON_RERANK_MODEL_ARN,
            "amazon_region": RERANK_REGION,
            "num_candidates": len(candidates),
            "rerank_top": RERANK_TOP,
            "records": records
        }

        os.makedirs(os.path.dirname(RERANK_LOG_PATH), exist_ok=True)
        with open(RERANK_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        logger.info(
            f"Rerank comparison logged | path={RERANK_LOG_PATH} | "
            f"selected={selected_provider} | candidates={len(candidates)}"
        )

    except Exception as e:
        logger.warning(f"Rerank comparison logging failed: {e}")


def rerank(question: str, chunks: list) -> list:
    """
    Uses Nova Micro to rerank chunks by relevance to the question.
    Receives pre-boosted chunks (org chunks already at front).
    Returns reranked list, falls back to original order on error.
    """
    # Legacy compatibility wrapper. The active Nova implementation now lives in
    # nova_reranker.py, so callers should use rerank_with_nova directly.
    return rerank_with_nova(question, chunks)

    # Legacy inline implementation below is intentionally inactive.
    r'''
    if not chunks:
        return chunks
    
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

    try:
        response = bedrock_runtime.converse(
            modelId=RERANKER_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}]
        )
        raw      = response["output"]["message"]["content"][0]["text"].strip()
        indices  = json.loads(raw)
        reranked = [chunks[i] for i in indices if i < len(chunks)]
        logger.info(f"Reranked {len(chunks)} chunks → top {len(reranked)}")
        return reranked

    except Exception as e:
        logger.warning(f"Reranker error: {e} — falling back to original order")
        return chunks[:top_n]
    '''


@observe(name="retrieve", capture_input=False, capture_output=False)
def retrieve(question: str, org_id: str = None, role: str = None, doc_type: str = None) -> tuple[list, str, list]:
    """
    Retrieves relevant chunks from Bedrock KB then reranks using Nova Micro.
    org_id comes from JWT login session — not from question text.

    Filter logic:
        superadmin (ndis) → no filter → sees all docs
        org with docs     → org-only filter → never mixes NDIS
        org without docs  → ndis-only filter → pure NDIS fallback

    Pipeline:
        1. build_filter()      — determine correct filter from org_id
        2. Bedrock KB retrieve — semantic search with filter
        3. boost_org_chunks()  — org chunks moved to front
        4. rerank()            — Nova Micro reranks boosted list

    Returns (chunks, context_text, sources)
    """
    if not question or not question.strip():
        logger.warning("Empty question passed to retriever")
        return [], "", []

    retrieval_config = {
        "vectorSearchConfiguration": {
            "numberOfResults": NUM_RESULTS
        }
    }

    # Determine and apply filter
    doc_filter = build_filter(org_id, doc_type)
    if doc_filter:
        retrieval_config["vectorSearchConfiguration"]["filter"] = doc_filter

    try:
        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": question},
            retrievalConfiguration=retrieval_config
        )

        all_chunks = response["retrievalResults"]
        logger.info(f"Retrieved {len(all_chunks)} chunks — boosting org chunks...")
        
        # Filter headers and footers
        content_chunks = [c for c in all_chunks if not is_noise_chunk(c)]
        filtered = len(all_chunks) - len(content_chunks)
        if filtered:
            logger.info(f"Filtered {filtered} noise chunks — {len(content_chunks)} content chunks remain")

        # Boost org chunks to front
        boosted_chunks = boost_org_chunks(content_chunks, org_id)

        selected_provider = RERANK_PROVIDER.lower()
        if selected_provider not in ("amazon", "nova"):
            logger.warning(
                f"Unknown RERANK_PROVIDER={RERANK_PROVIDER}; defaulting to amazon"
            )
            selected_provider = "amazon"

        # In compare mode, run both rerankers on the same boosted candidates.
        # In provider-only mode, call just the selected reranker to avoid extra
        # latency and cross-region Amazon rerank cost during eval.
        if RERANK_COMPARE:
            nova_chunks = rerank_with_nova(question, boosted_chunks)
            amazon_chunks = rerank_with_amazon(question, boosted_chunks)

            if selected_provider == "nova":
                reranked_chunks = nova_chunks
            else:
                reranked_chunks = amazon_chunks

            log_rerank_comparison(
                question=question,
                candidates=boosted_chunks,
                nova_chunks=nova_chunks,
                amazon_chunks=amazon_chunks,
                selected_provider=selected_provider
            )
        else:
            if selected_provider == "nova":
                reranked_chunks = rerank_with_nova(question, boosted_chunks)
            else:
                reranked_chunks = rerank_with_amazon(question, boosted_chunks)

        context = "\n\n".join([c["content"]["text"] for c in reranked_chunks])
        sources = [c["location"]["s3Location"]["uri"] for c in reranked_chunks]

        # Log reranker position with original Bedrock similarity score
        logger.info(f"Top {len(reranked_chunks)} after reranking with {selected_provider}:")
        for i, (src, chunk) in enumerate(zip(sources, reranked_chunks)):
            orig_score = round(chunk.get("score", 0), 4)
            amazon_score = chunk.get("amazon_rerank_score")
            logger.info(
                f"  [{i+1}] OrigScore: {orig_score} | "
                f"AmazonScore: {amazon_score} | {src.split('/')[-1]}"
            )

        langfuse.update_current_span(
            input=question,
            output=[s.split("/")[-1] for s in sources],
            metadata={
                "chunks_retrieved": len(all_chunks),
                "chunks_after_noise_filter": len(content_chunks),
                "chunks_returned": len(reranked_chunks),
                "rerank_provider": selected_provider,
                "org_id": org_id,
                "doc_type": doc_type,
            },
        )

        return reranked_chunks, context, sources

    except Exception as e:
        logger.error(f"Retriever error: {e}")
        return [], "", []


def is_context_empty(context: str) -> bool:
    return len(context.strip()) < 100


if __name__ == "__main__":
    while True:
        q = input("\nEnter question (or 'quit'): ").strip()
        if q.lower() == "quit":
            break
        chunks, context, sources = retrieve(q, org_id="org_horizons")
        print(f"   Chunks: {len(chunks)}")
        print(f"   Context length: {len(context)} chars")
        print(f"   Sources: {[s.split('/')[-1] for s in sources]}")
        print(f"   Empty: {is_context_empty(context)}")
