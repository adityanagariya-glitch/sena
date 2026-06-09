# amazon_reranker.py
import boto3
import logging

from config import (
    RERANK_TOP,
    RERANK_REGION,
    AMAZON_RERANK_MODEL_ID,
    AMAZON_RERANK_MODEL_ARN,
)
from nova_reranker import rerank_with_nova

logger = logging.getLogger(__name__)

rerank_runtime = boto3.client(
    "bedrock-agent-runtime",
    region_name=RERANK_REGION
)


def rerank_with_amazon(question: str, chunks: list) -> list:
    """
    Uses Amazon Bedrock native Rerank API as a cross-encoder reranker.
    Intended for manual cross-region reranking from Sydney to Tokyo.
    Returns reranked list, falls back to original order on error.
    """
    if not chunks:
        return chunks

    top_n = min(RERANK_TOP, len(chunks))

    sources = []
    for chunk in chunks:
        src = chunk.get("location", {}).get("s3Location", {}).get("uri", "")
        text = chunk.get("content", {}).get("text", "")
        rerank_text = f"Source: {src}\n\n{text}"

        sources.append({
            "type": "INLINE",
            "inlineDocumentSource": {
                "type": "TEXT",
                "textDocument": {
                    "text": rerank_text
                }
            }
        })

    try:
        response = rerank_runtime.rerank(
            queries=[
                {
                    "type": "TEXT",
                    "textQuery": {
                        "text": question
                    }
                }
            ],
            sources=sources,
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "modelConfiguration": {
                        "modelArn": AMAZON_RERANK_MODEL_ARN
                    },
                    "numberOfResults": top_n
                }
            }
        )

        reranked_chunks = []
        for new_rank, item in enumerate(response.get("results", []), start=1):
            old_index = item["index"]
            chunk = dict(chunks[old_index])
            chunk["amazon_rerank_score"] = item.get("relevanceScore")
            chunk["amazon_rerank_old_index"] = old_index
            chunk["amazon_rerank_new_rank"] = new_rank
            reranked_chunks.append(chunk)

        logger.info(
            f"Amazon Bedrock reranked {len(chunks)} chunks -> top {len(reranked_chunks)} | "
            f"model={AMAZON_RERANK_MODEL_ID} | region={RERANK_REGION}"
        )
        return reranked_chunks

    except Exception as e:
        logger.warning(
            f"Amazon Bedrock reranker error: {e} -> falling back to Nova reranker | "
            f"model={AMAZON_RERANK_MODEL_ID} | region={RERANK_REGION}"
        )
        return rerank_with_nova(question, chunks)
