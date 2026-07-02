# amazon_reranker.py
import boto3
import logging
from math import ceil
from langfuse import observe, get_client

langfuse = get_client()

from config import (
    RERANK_TOP,
    RERANK_REGION,
    AMAZON_RERANK_MODEL_ID,
    AMAZON_RERANK_MODEL_ARN,
)
from nova_reranker import rerank_with_nova

logger = logging.getLogger(__name__)

_SERVICE = "policy_proc"
_TAG = "policy_proc_reranker_amazon"

rerank_runtime = boto3.client(
    "bedrock-agent-runtime",
    region_name=RERANK_REGION
)


@observe(as_type="generation", name="policy-proc-rerank-amazon", capture_input=False, capture_output=False)
def rerank_with_amazon(question: str, chunks: list) -> list:
    """
    Uses Amazon Bedrock native Rerank API as a cross-encoder reranker.
    Intended for manual cross-region reranking from Sydney to Tokyo.
    Returns reranked list, falls back to original order on error.
    """
    if not chunks:
        return chunks

    top_n = min(RERANK_TOP, len(chunks))
    query_units = ceil(len(chunks) / 100)

    langfuse.update_current_generation(
        model=AMAZON_RERANK_MODEL_ID,
        input=question,
    )

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

        langfuse.update_current_generation(
            output={"reranked_count": len(reranked_chunks)},
            usage_details={"queries": query_units},
            metadata={"service": _TAG},
        )

        logger.info(
            f"Amazon Bedrock reranked {len(chunks)} chunks -> top {len(reranked_chunks)} | "
            f"model={AMAZON_RERANK_MODEL_ID} | region={RERANK_REGION}"
        )
        return reranked_chunks

    except Exception as e:
        langfuse.update_current_generation(
            output={"error": str(e)},
            usage_details={"queries": 0},
            metadata={"service": _TAG},
        )
        logger.warning(
            f"Amazon Bedrock reranker error: {e} -> falling back to Nova reranker | "
            f"model={AMAZON_RERANK_MODEL_ID} | region={RERANK_REGION}"
        )
        return rerank_with_nova(question, chunks)
