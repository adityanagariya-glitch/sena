"""
Evaluate retrieval and reranking against gold chunk annotations.

Default input:
    C:\\Users\\BAPS\\Documents\\SENA_RAG\\gt-eval-dataset\\gold_dataset_v3_with_chunks.xlsx

Default output directory:
    C:\\Users\\BAPS\\Documents\\SENA_RAG\\ragas_output

Example:
    python local_tests/evaluate_retrieval_reranker.py
    python local_tests/evaluate_retrieval_reranker.py --ks 1,3,5,10 --rerankers amazon,nova

The script scores raw KB retrieval and reranked results using ranking metrics:
    nDCG@k, recall@k, precision@k, hit@k, MRR@k, MAP@k
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import boto3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from config import KB_ID, NUM_RESULTS, REGION, RERANK_PROVIDER, RERANK_TOP  # noqa: E402
from retriever import build_filter, boost_org_chunks, is_noise_chunk  # noqa: E402
from amazon_reranker import rerank_with_amazon  # noqa: E402
from nova_reranker import rerank_with_nova  # noqa: E402


DEFAULT_INPUT = ROOT / "gt-eval-dataset" / "gold_dataset_v3_with_chunks.xlsx"
DEFAULT_OUTPUT_DIR = ROOT / "ragas_output"
DEFAULT_KS = (1, 3, 5, 10)
DEFAULT_SHEETS = (
    "NDIS Only",
    "Sunrise Only",
    "Horizons Only",
    "Cross-Org Different Answers",
    "Incomplete Answers",
)


@dataclass
class GoldChunk:
    text: str
    source: str
    source_keys: set[str]


@dataclass
class RankedChunk:
    rank: int
    text: str
    uri: str
    source_name: str
    score: float | None
    source_keys: set[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Bedrock KB retrieval and rerankers with ranking metrics."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Gold Excel file.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory.")
    parser.add_argument("--sheets", default=",".join(DEFAULT_SHEETS), help="Comma-separated sheet names, or 'all'.")
    parser.add_argument("--ks", default=",".join(map(str, DEFAULT_KS)), help="Comma-separated k values.")
    parser.add_argument("--num-results", type=int, default=NUM_RESULTS, help="Raw KB candidates to retrieve.")
    parser.add_argument("--match-threshold", type=float, default=0.55, help="Fuzzy text match threshold.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between questions.")
    parser.add_argument(
        "--rerankers",
        default=RERANK_PROVIDER,
        help="Comma-separated rerankers to evaluate: amazon,nova,none,selected,both.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max rows per sheet for quick runs.")
    parser.add_argument("--include-noise", action="store_true", help="Do not filter low-content chunks.")
    return parser.parse_args()


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def source_keys(value: str) -> set[str]:
    value = value.upper()
    keys: set[str] = set()

    for kind, ndis_marker, number in re.findall(r"\b(POL|PROC)[-_ ]?(NDIS)?[-_ ]?(\d{1,3}(?:[-_ ]?\d{1,3})?)", value):
        prefix = f"{kind}{ndis_marker}{number}"
        keys.add(re.sub(r"[^A-Z0-9]", "", prefix))

    for match in re.findall(r"\b(?:SDS|HCC|NDIS)[-_ ]?(?:POL|PROC)[-_ ]?(?:NDIS[-_ ]?)?\d{1,3}(?:[-_ ]?\d{1,3})?", value):
        stripped = re.sub(r"^(SDS|HCC|NDIS)", "", re.sub(r"[^A-Z0-9]", "", match))
        if stripped:
            keys.add(stripped)

    for match in re.findall(r"\b[A-Z]{2,8}[-_ ]?(?:POL|PROC)[-_ ]?(?:NDIS[-_ ]?)?\d{1,3}(?:[-_ ]?\d{1,3})?", value):
        compact = re.sub(r"[^A-Z0-9]", "", match)
        compact = re.sub(r"^[A-Z]+(?=(POL|PROC))", "", compact)
        if compact:
            keys.add(compact)

    return keys


def parse_gold_chunks(value: object) -> list[GoldChunk]:
    raw = clean_text(value)
    if not raw:
        return []

    chunks: list[GoldChunk] = []
    for part in re.split(r"\n\s*---\s*\n", raw):
        part = part.strip()
        if not part:
            continue

        source = ""
        text = part
        source_match = re.search(r"\|\s*Source:\s*(.+)$", part, flags=re.IGNORECASE | re.DOTALL)
        if source_match:
            source = source_match.group(1).strip()
            text = part[: source_match.start()].strip()

        text = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
        chunks.append(
            GoldChunk(
                text=text,
                source=source,
                source_keys=source_keys(f"{source} {part}"),
            )
        )
    return chunks


def chunk_to_ranked(chunk: dict, rank: int) -> RankedChunk:
    uri = chunk.get("location", {}).get("s3Location", {}).get("uri", "")
    text = chunk.get("content", {}).get("text", "")
    source_name = uri.rsplit("/", 1)[-1]
    return RankedChunk(
        rank=rank,
        text=text,
        uri=uri,
        source_name=source_name,
        score=chunk.get("score"),
        source_keys=source_keys(f"{uri} {source_name}"),
    )


def token_f1(a: str, b: str) -> float:
    a_tokens = set(normalize_text(a).split())
    b_tokens = set(normalize_text(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    precision = overlap / len(a_tokens)
    recall = overlap / len(b_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def match_score(predicted: RankedChunk, gold: GoldChunk) -> float:
    pred_norm = normalize_text(predicted.text)
    gold_norm = normalize_text(gold.text)
    if not pred_norm or not gold_norm:
        return 0.0

    if gold_norm in pred_norm or pred_norm in gold_norm:
        text_score = 1.0
    else:
        text_score = max(
            token_f1(predicted.text, gold.text),
            SequenceMatcher(None, pred_norm[:1500], gold_norm[:1500]).ratio(),
        )

    has_source_match = bool(predicted.source_keys & gold.source_keys)
    if has_source_match:
        return max(text_score, min(1.0, text_score + 0.15), 0.65)
    return text_score


def relevance_vector(
    ranked_chunks: list[RankedChunk],
    gold_chunks: list[GoldChunk],
    k: int,
    threshold: float,
) -> tuple[list[int], set[int], list[float]]:
    rels: list[int] = []
    matched_gold: set[int] = set()
    scores: list[float] = []

    for chunk in ranked_chunks[:k]:
        best_idx = None
        best_score = 0.0
        for idx, gold in enumerate(gold_chunks):
            if idx in matched_gold:
                continue
            score = match_score(chunk, gold)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is not None and best_score >= threshold:
            matched_gold.add(best_idx)
            rels.append(1)
        else:
            rels.append(0)
        scores.append(round(best_score, 4))

    return rels, matched_gold, scores


def ranking_metrics(
    ranked_chunks: list[RankedChunk],
    gold_chunks: list[GoldChunk],
    ks: tuple[int, ...],
    threshold: float,
) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {"gold_chunk_count": len(gold_chunks)}
    if not gold_chunks:
        for k in ks:
            metrics.update({f"ndcg@{k}": 0.0, f"recall@{k}": 0.0, f"precision@{k}": 0.0, f"hit@{k}": 0.0, f"mrr@{k}": 0.0, f"map@{k}": 0.0})
        return metrics

    for k in ks:
        rels, matched, _ = relevance_vector(ranked_chunks, gold_chunks, k, threshold)
        dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(rels, start=1))
        ideal_hits = min(len(gold_chunks), k)
        idcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

        precisions_at_hits = [
            sum(rels[:idx]) / idx
            for idx, rel in enumerate(rels, start=1)
            if rel
        ]

        first_hit = next((idx for idx, rel in enumerate(rels, start=1) if rel), None)
        metrics[f"ndcg@{k}"] = round(dcg / idcg, 4) if idcg else 0.0
        metrics[f"recall@{k}"] = round(len(matched) / len(gold_chunks), 4)
        metrics[f"precision@{k}"] = round(sum(rels) / k, 4)
        metrics[f"hit@{k}"] = 1.0 if any(rels) else 0.0
        metrics[f"mrr@{k}"] = round(1 / first_hit, 4) if first_hit else 0.0
        metrics[f"map@{k}"] = round(sum(precisions_at_hits) / len(gold_chunks), 4)

    return metrics


def infer_org_id(sheet_name: str, row: pd.Series) -> str:
    org = clean_text(row.get("org")).lower()
    source_policy = clean_text(row.get("source_policy")).lower()
    combined = f"{sheet_name} {org} {source_policy}".lower()

    if "sunrise" in combined or org == "sunrise":
        return "org_sunrise"
    if "horizons" in combined or org == "horizons":
        return "org_horizons"
    return "ndis"


def retrieve_candidates(question: str, org_id: str, num_results: int, include_noise: bool) -> list[dict]:
    client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    retrieval_config: dict = {
        "vectorSearchConfiguration": {
            "numberOfResults": num_results,
        }
    }
    doc_filter = build_filter(org_id)
    if doc_filter:
        retrieval_config["vectorSearchConfiguration"]["filter"] = doc_filter

    response = client.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration=retrieval_config,
    )
    chunks = response.get("retrievalResults", [])
    if not include_noise:
        chunks = [chunk for chunk in chunks if not is_noise_chunk(chunk)]
    return boost_org_chunks(chunks, org_id)


def selected_rerankers(value: str) -> dict[str, Callable[[str, list], list]]:
    requested = [item.strip().lower() for item in value.split(",") if item.strip()]
    expanded: list[str] = []
    for item in requested:
        if item == "selected":
            expanded.append(RERANK_PROVIDER.lower())
        elif item == "both":
            expanded.extend(["amazon", "nova"])
        else:
            expanded.append(item)

    funcs: dict[str, Callable[[str, list], list]] = {}
    for item in expanded:
        if item == "amazon":
            funcs["rerank_amazon"] = rerank_with_amazon
        elif item == "nova":
            funcs["rerank_nova"] = rerank_with_nova
        elif item == "none":
            continue
        else:
            raise ValueError(f"Unknown reranker '{item}'. Use amazon,nova,selected,both,none.")
    return funcs


def preview_ranked(ranked: list[RankedChunk], limit: int) -> str:
    items = []
    for chunk in ranked[:limit]:
        items.append(
            {
                "rank": chunk.rank,
                "source": chunk.source_name,
                "score": chunk.score,
                "text_preview": re.sub(r"\s+", " ", chunk.text)[:220],
            }
        )
    return json.dumps(items, ensure_ascii=False)


def evaluate_sheet(
    sheet_name: str,
    df: pd.DataFrame,
    ks: tuple[int, ...],
    args: argparse.Namespace,
    rerankers: dict[str, Callable[[str, list], list]],
) -> list[dict]:
    records: list[dict] = []
    rows = df.head(args.limit) if args.limit else df

    for row_number, (_, row) in enumerate(rows.iterrows(), start=1):
        question = clean_text(row.get("prompt"))
        if not question:
            continue

        org_id = infer_org_id(sheet_name, row)
        role = clean_text(row.get("role"))
        gold_chunks = parse_gold_chunks(row.get("retrieved_chunks"))

        print(f"[{sheet_name}] {row_number}/{len(rows)} org={org_id} q={question[:80]}")
        try:
            raw_chunks = retrieve_candidates(
                question=question,
                org_id=org_id,
                num_results=args.num_results,
                include_noise=args.include_noise,
            )
            variants: dict[str, list[dict]] = {"retrieval": raw_chunks}
            for name, rerank_func in rerankers.items():
                variants[name] = rerank_func(question, raw_chunks)

            for variant_name, chunks in variants.items():
                ranked = [chunk_to_ranked(chunk, rank) for rank, chunk in enumerate(chunks, start=1)]
                record = {
                    "sheet": sheet_name,
                    "row_number": row_number,
                    "q_id": clean_text(row.get("q_id") or row.get("#")),
                    "org_id": org_id,
                    "role": role,
                    "variant": variant_name,
                    "question": question,
                    "ground_truth": clean_text(row.get("ground_truth")),
                    "source_policy": clean_text(row.get("source_policy")),
                    "candidate_count": len(raw_chunks),
                    "result_count": len(ranked),
                    "gold_chunks": len(gold_chunks),
                    "top_results_json": preview_ranked(ranked, max(ks)),
                }
                record.update(ranking_metrics(ranked, gold_chunks, ks, args.match_threshold))
                records.append(record)
        except Exception as exc:
            records.append(
                {
                    "sheet": sheet_name,
                    "row_number": row_number,
                    "q_id": clean_text(row.get("q_id") or row.get("#")),
                    "org_id": org_id,
                    "role": role,
                    "variant": "error",
                    "question": question,
                    "ground_truth": clean_text(row.get("ground_truth")),
                    "source_policy": clean_text(row.get("source_policy")),
                    "candidate_count": 0,
                    "result_count": 0,
                    "gold_chunks": len(gold_chunks),
                    "error": repr(exc),
                }
            )

        if args.sleep:
            time.sleep(args.sleep)

    return records


def build_summary(results_df: pd.DataFrame, ks: tuple[int, ...]) -> pd.DataFrame:
    metric_cols = [
        col
        for k in ks
        for col in (f"ndcg@{k}", f"recall@{k}", f"precision@{k}", f"hit@{k}", f"mrr@{k}", f"map@{k}")
    ]
    available_metrics = [col for col in metric_cols if col in results_df.columns]
    ok_df = results_df[results_df["variant"] != "error"].copy()
    if ok_df.empty:
        return pd.DataFrame()

    summary = (
        ok_df.groupby(["sheet", "variant"], dropna=False)[available_metrics]
        .mean(numeric_only=True)
        .reset_index()
    )
    all_rows = (
        ok_df.groupby(["variant"], dropna=False)[available_metrics]
        .mean(numeric_only=True)
        .reset_index()
    )
    all_rows.insert(0, "sheet", "ALL")
    return pd.concat([summary, all_rows], ignore_index=True)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ks = tuple(sorted({int(k.strip()) for k in args.ks.split(",") if k.strip()}))
    rerankers = selected_rerankers(args.rerankers)

    sheets = pd.read_excel(input_path, sheet_name=None)
    if args.sheets.strip().lower() == "all":
        sheet_names = [name for name in sheets if name.lower() != "how to use"]
    else:
        sheet_names = [name.strip() for name in args.sheets.split(",") if name.strip()]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_xlsx = output_dir / f"retrieval_reranker_eval_{timestamp}.xlsx"
    output_json = output_dir / f"retrieval_reranker_eval_{timestamp}.json"

    all_records: list[dict] = []
    for sheet_name in sheet_names:
        if sheet_name not in sheets:
            print(f"Skipping missing sheet: {sheet_name}")
            continue
        all_records.extend(evaluate_sheet(sheet_name, sheets[sheet_name], ks, args, rerankers))

    results_df = pd.DataFrame(all_records)
    summary_df = build_summary(results_df, ks)

    run_info = {
        "timestamp": timestamp,
        "input": str(input_path),
        "output_xlsx": str(output_xlsx),
        "region": REGION,
        "kb_id": KB_ID,
        "num_results": args.num_results,
        "config_num_results": NUM_RESULTS,
        "config_rerank_top": RERANK_TOP,
        "config_rerank_provider": RERANK_PROVIDER,
        "ks": ks,
        "match_threshold": args.match_threshold,
        "sheets": sheet_names,
        "rerankers": list(rerankers),
        "include_noise": args.include_noise,
    }

    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        results_df.to_excel(writer, sheet_name="Per Query", index=False)
        pd.DataFrame([run_info]).to_excel(writer, sheet_name="Run Info", index=False)

    with open(output_json, "w", encoding="utf-8") as file:
        json.dump(
            {
                "run_info": run_info,
                "summary": summary_df.to_dict(orient="records"),
                "results": results_df.to_dict(orient="records"),
            },
            file,
            indent=2,
            ensure_ascii=False,
        )

    # Append ranking metrics to eval_history_v2-1.json
    history_path = output_dir / "eval_history_v2-1.json"
    metric_cols = [
        col
        for k in ks
        for col in (f"ndcg@{k}", f"recall@{k}", f"precision@{k}", f"hit@{k}", f"mrr@{k}", f"map@{k}")
    ]
    available_metrics = [col for col in metric_cols if col in summary_df.columns]
    all_rows = summary_df[summary_df["sheet"] == "ALL"] if not summary_df.empty else pd.DataFrame()

    scores_by_variant: dict = {}
    for _, row in all_rows.iterrows():
        variant = row["variant"]
        scores_by_variant[variant] = {
            col: round(float(row[col]), 4)
            for col in available_metrics
            if col in row.index and pd.notna(row[col])
        }

    history_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": (
            f"retrieval reranker eval | rerankers: {', '.join(rerankers) or 'none'}"
            f" | ks: {list(ks)} | threshold: {args.match_threshold}"
        ),
        "scores": scores_by_variant,
    }

    history: list = []
    if history_path.exists():
        with open(history_path, encoding="utf-8") as hf:
            history = json.load(hf)
    history.append(history_entry)
    with open(history_path, "w", encoding="utf-8") as hf:
        json.dump(history, hf, indent=2, ensure_ascii=False)

    print("\nDone.")
    print(f"Excel: {output_xlsx}")
    print(f"JSON : {output_json}")
    if not summary_df.empty:
        print("\nSummary:")
        print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
