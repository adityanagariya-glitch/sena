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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import bedrock_runtime, MODEL_ID
from cleaner import clean

import prompt as P

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MAX_TOKENS = 4096


def load_inputs() -> dict:
    """Build the placeholder substitutions from example.json."""
    raw = json.loads((HERE / "example.json").read_bytes().lstrip(b"\xe2\x80\x8b").decode("utf-8"))
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
    return {"text": clean(text.strip()), "usage": usage, "elapsed": elapsed,
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

    wave1 = [(i, sec) for i, sec in sections if i != 7]
    wave2 = [(i, sec) for i, sec in sections if i == 7]

    print(f"Wave 1: {len(wave1)} section(s) in parallel | Wave 2: {len(wave2)} section(s) sequential\n")

    usage_log = {"model": MODEL_ID, "sections": {}, "totals": {}}
    tot_in = tot_out = tot_total = 0
    section_outputs: dict[int, dict] = {}

    def _run(i: int, section: dict, section_subs: dict) -> tuple[int, dict]:
        return i, run_section(f"section_{i}", section, section_subs)

    base_subs = {**subs, "{{SECTION_3}}": "", "{{SECTION_4}}": "", "{{SECTION_5}}": ""}

    # Wave 1: sections 1-6 in parallel
    with ThreadPoolExecutor(max_workers=len(wave1)) as pool:
        futures = {pool.submit(_run, i, sec, base_subs): i for i, sec in wave1}
        for future in as_completed(futures):
            i = futures[future]
            try:
                _, result = future.result()
            except Exception as e:
                print(f"[section {i}] FAILED: {type(e).__name__}: {e}")
                usage_log["sections"][f"section_{i}"] = {"error": str(e)}
                continue
            section_outputs[i] = result
            u = result["usage"]
            in_t, out_t = u.get("inputTokens", 0), u.get("outputTokens", 0)
            print(f"[section {i}] OK  in={in_t} out={out_t}  {result['elapsed']:.1f}s"
                  f"  ({'truncated!' if result['stopReason'] == 'max_tokens' else result['stopReason']})")

    # Wave 2: section 7 with context from 3, 4, 5
    for i, section in wave2:
        ctx_subs = {
            **subs,
            "{{SECTION_3}}": section_outputs.get(3, {}).get("text", ""),
            "{{SECTION_4}}": section_outputs.get(4, {}).get("text", ""),
            "{{SECTION_5}}": section_outputs.get(5, {}).get("text", ""),
        }
        sys.stdout.write(f"[section {i}] calling Bedrock (uses 3/4/5)… ")
        sys.stdout.flush()
        try:
            result = run_section(f"section_{i}", section, ctx_subs)
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            usage_log["sections"][f"section_{i}"] = {"error": str(e)}
            continue
        section_outputs[i] = result
        u = result["usage"]
        in_t, out_t = u.get("inputTokens", 0), u.get("outputTokens", 0)
        print(f"OK  in={in_t} out={out_t}  {result['elapsed']:.1f}s")

    # Write outputs in section order
    report_parts = []
    for i, _ in sections:
        if i not in section_outputs:
            continue
        result = section_outputs[i]
        out_file = OUT / f"section_{i}.md"
        out_file.write_text(result["text"] + "\n")
        report_parts.append(result["text"])
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

    usage_log["totals"] = {"inputTokens": tot_in, "outputTokens": tot_out, "totalTokens": tot_total}
    (OUT / "_usage.json").write_text(json.dumps(usage_log, indent=2))
    (OUT / "_report.md").write_text("\n\n---\n\n".join(report_parts) + "\n")

    print(f"\nTOTAL tokens — in={tot_in}  out={tot_out}  total={tot_total}")
    print(f"Outputs in {OUT}/  (section_N.md, _report.md, _usage.json)")


if __name__ == "__main__":
    main()
