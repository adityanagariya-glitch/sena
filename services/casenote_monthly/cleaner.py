"""Post-process Bedrock output: strip thinking/verification blocks and fix formatting."""
import re

_THINKING_KEYWORDS = (
    "Pass 1", "Pass 2", "Pass 3", "Pass 4",
    "Execution Log", "ALGORITHM", "Self-Verification",
    "Verification Log", "☑", "☐", "Metric notes",
)


def clean(text: str) -> str:
    """Strip self-verification blockquotes, execution logs, emojis from model output."""
    text = text.replace("⚠️", "").replace(" HIGH PRIORITY", "")
    lines = text.splitlines()
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip consecutive blockquote lines (> ...) — these are verification/notes
        if line.strip().startswith(">"):
            while i < len(lines) and lines[i].strip().startswith(">"):
                i += 1
            # Remove the preceding --- separator that wrapped this block
            while out and out[-1].strip() in ("", "---"):
                removed = out.pop()
                if removed.strip() == "---":
                    break
            continue

        # Detect --- that opens a thinking/execution block (between two ---)
        if line.strip() == "---":
            block: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != "---":
                block.append(lines[j])
                j += 1
            block_text = "\n".join(block)
            if j < len(lines) and any(kw in block_text for kw in _THINKING_KEYWORDS):
                i = j + 1  # skip past the closing ---
                while out and out[-1].strip() == "":
                    out.pop()
                continue

        out.append(line)
        i += 1

    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
