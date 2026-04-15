## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

## Ignored Folders

**NEVER** try to read or analyze anything inside the `/archive`, `.venv`, or `.vscode` folders. They are a massive token consumption disaster and are likely useless for your analysis. Pretend they do not exist unless explicitly instructed by the user to restore something.
