# retriever.py
import boto3
import json
import logging

from config import REGION, KB_ID, NUM_RESULTS, RERANK_TOP, RERANKER_MODEL

logger = logging.getLogger(__name__)

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
bedrock_runtime       = boto3.client("bedrock-runtime",       region_name=REGION)

# ── Org doc cache ─────────────────────────────────────────────────────────────
# Persists for lifetime of FastAPI process.
# Clears automatically on server restart (--reload on code change).
# Call clear_org_cache() after manual S3 uploads/deletions in production.
_org_doc_cache: dict[str, bool] = {}


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


def org_has_docs(org_id: str) -> bool:
    """
    Checks if the org has any documents indexed in S3 Vectors.
    Result cached for lifetime of process — avoids extra Bedrock call per query.
    Returns True if at least one chunk exists for this org.
    """
    if org_id in _org_doc_cache:
        logger.info(f"org_has_docs cache hit — {org_id}: {_org_doc_cache[org_id]}")
        return _org_doc_cache[org_id]

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
        _org_doc_cache[org_id] = result
        logger.info(f"org_has_docs — {org_id}: {result} (cached)")
        return result

    except Exception as e:
        logger.warning(f"org_has_docs check failed for {org_id}: {e}")
        return False


def build_filter(org_id: str) -> dict | None:
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

    if org_has_docs(org_id):
        # Org has its own docs — restrict to org only
        logger.info(f"Filter: org-only ({org_id})")
        return {"equals": {"key": "org_id", "value": org_id}}

    else:
        # Org has no docs — fall back to NDIS only
        logger.info(f"Filter: ndis-only (org {org_id} has no docs)")
        return {"equals": {"key": "org_id", "value": "ndis"}}


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


def rerank(question: str, chunks: list) -> list:
    """
    Uses Nova Micro to rerank chunks by relevance to the question.
    Receives pre-boosted chunks (org chunks already at front).
    Returns reranked list, falls back to original order on error.
    """
    if not chunks:
        return chunks

    chunk_texts = "\n\n".join([
        f"[{i}] {c['content']['text'][:500]}"
        for i, c in enumerate(chunks)
    ])

    prompt = f"""You are a relevance ranker for an NDIS policy assistant.

Given a question and {len(chunks)} text chunks, return the indices of the {RERANK_TOP} most relevant chunks in order of relevance (most relevant first).

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
        return chunks[:RERANK_TOP]


def retrieve(question: str, org_id: str = None, role: str = None) -> tuple[list, str, list]:
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
    doc_filter = build_filter(org_id)
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

        # Boost org chunks to front before reranking
        boosted_chunks  = boost_org_chunks(all_chunks, org_id)

        # Rerank boosted list
        reranked_chunks = rerank(question, boosted_chunks)

        context = "\n\n".join([c["content"]["text"] for c in reranked_chunks])
        sources = [c["location"]["s3Location"]["uri"] for c in reranked_chunks]

        # Log reranker position with original Bedrock similarity score
        logger.info(f"Top {len(reranked_chunks)} after reranking:")
        for i, (src, chunk) in enumerate(zip(sources, reranked_chunks)):
            orig_score = round(chunk.get("score", 0), 4)
            logger.info(f"  [{i+1}] OrigScore: {orig_score} | {src.split('/')[-1]}")

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