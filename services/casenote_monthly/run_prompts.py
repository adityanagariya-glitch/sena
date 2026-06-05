"""Run every section prompt in prompt.py against example.json via Bedrock.

Each section's output is saved separately under ./out/section_N.md, plus:
  - out/_usage.json  : per-section + total token usage
  - out/_report.md   : all sections concatenated (convenience)

Run:
    cd /home/main/SENA/services/casenote_monthly
    /home/main/SENA/sena-ai/bin/python run_prompts.py
"""
import json
import sys
import time
from pathlib import Path

from config import bedrock_runtime, MODEL_ID

import prompt as P

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MAX_TOKENS = 4096


def load_inputs() -> dict:
    """Build the placeholder substitutions from example.json."""
    raw = json.loads((HERE / "example.json").read_text())
    data = raw.get("data", raw)
    client = data.get("client", {})
    goals = client.get("ndisPlanGoals") or client.get("personalGoals") or []
    return {
        "{{CLIENT_JSON}}": json.dumps(data, indent=2, ensure_ascii=False),
        "{{START_DATE}}": str(data.get("dateFrom", "")),
        "{{END_DATE}}": str(data.get("dateTo", "")),
        "{{NDIS_GOALS_LIST}}": ", ".join(goals) if isinstance(goals, list) else str(goals),
    }


def fill(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def normalize_section(section) -> dict:
    if isinstance(section, dict):
        return section
    if isinstance(section, str) and section.strip():
        return {"system": "", "user": section}
    return {}


def run_section(name: str, section: dict, subs: dict) -> dict:
    """Call Bedrock for one section. Returns {text, usage, elapsed}."""
    system = section.get("system", "")
    user = fill(section.get("user", ""), subs)

    t0 = time.time()
    resp = bedrock_runtime.converse(
        modelId=MODEL_ID,
        system=[{"text": system}] if system else [],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    elapsed = time.time() - t0

    text = ""
    msg = (resp.get("output") or {}).get("message") or {}
    for block in msg.get("content", []):
        if "text" in block:
            text += block["text"]

    usage = resp.get("usage") or {}
    return {"text": text.strip(), "usage": usage, "elapsed": elapsed,
            "stopReason": resp.get("stopReason")}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    subs = load_inputs()

    # Collect section_1 .. section_N from prompt.py, in order, skipping empties.
    sections = []
    for i in range(1, 50):
        obj = getattr(P, f"section_{i}", None)
        if obj is None:
            continue
        section = normalize_section(obj)
        if "user" in section:
            sections.append((i, section))

    print(f"Running {len(sections)} section(s) via {MODEL_ID}\n")

    usage_log = {"model": MODEL_ID, "sections": {}, "totals": {}}
    tot_in = tot_out = tot_total = 0
    report_parts = []
    section_outputs = {}

    for i, section in sections:
        sys.stdout.write(f"[section {i}] calling Bedrock… ")
        sys.stdout.flush()
        section_subs = {
            **subs,
            "{{SECTION_3}}": section_outputs.get(3, ""),
            "{{SECTION_4}}": section_outputs.get(4, ""),
            "{{SECTION_5}}": section_outputs.get(5, ""),
        }
        try:
            result = run_section(f"section_{i}", section, section_subs)
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            usage_log["sections"][f"section_{i}"] = {"error": str(e)}
            continue

        out_file = OUT / f"section_{i}.md"
        out_file.write_text(result["text"] + "\n")

        u = result["usage"]
        in_t = u.get("inputTokens", 0)
        out_t = u.get("outputTokens", 0)
        total_t = u.get("totalTokens", in_t + out_t)
        tot_in += in_t; tot_out += out_t; tot_total += total_t

        usage_log["sections"][f"section_{i}"] = {
            "inputTokens": in_t, "outputTokens": out_t, "totalTokens": total_t,
            "cacheReadInputTokens": u.get("cacheReadInputTokens", 0),
            "cacheWriteInputTokens": u.get("cacheWriteInputTokens", 0),
            "stopReason": result["stopReason"],
            "elapsed_sec": round(result["elapsed"], 2),
            "chars": len(result["text"]),
            "file": str(out_file.relative_to(HERE)),
        }
        report_parts.append(result["text"])
        section_outputs[i] = result["text"]
        print(f"OK  in={in_t} out={out_t} total={total_t}  {result['elapsed']:.1f}s "
              f"({'truncated!' if result['stopReason']=='max_tokens' else result['stopReason']}) "
              f"→ {out_file.name}")

    usage_log["totals"] = {"inputTokens": tot_in, "outputTokens": tot_out, "totalTokens": tot_total}
    (OUT / "_usage.json").write_text(json.dumps(usage_log, indent=2))
    (OUT / "_report.md").write_text("\n\n---\n\n".join(report_parts) + "\n")

    print(f"\nTOTAL tokens — in={tot_in}  out={tot_out}  total={tot_total}")
    print(f"Outputs in {OUT}/  (section_N.md, _report.md, _usage.json)")


if __name__ == "__main__":
    main()
