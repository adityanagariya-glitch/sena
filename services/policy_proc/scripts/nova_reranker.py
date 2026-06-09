# nova_reranker.py
import boto3
import json
import logging

from config import REGION, RERANK_TOP, RERANKER_MODEL

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)


def rerank_with_nova(question: str, chunks: list) -> list:
    """
    Uses Nova Micro to rerank chunks by relevance to the question.
    This is the current prompt-based reranker extracted from retriever.py.
    Returns reranked list, falls back to original order on error.
    """
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
        raw = response["output"]["message"]["content"][0]["text"].strip()
        indices = json.loads(raw)
        reranked = [chunks[i] for i in indices if i < len(chunks)]

        logger.info(
            f"Nova reranked {len(chunks)} chunks -> top {len(reranked)} | "
            f"model={RERANKER_MODEL}"
        )
        return reranked

    except Exception as e:
        logger.warning(
            f"Nova reranker error: {e} -> falling back to original order | "
            f"model={RERANKER_MODEL}"
        )
        return chunks[:top_n]
