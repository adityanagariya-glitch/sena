"""One-shot converter: prompt .md  ->  .py modules (byte-exact, round-trip verified).

WHY: prompt content moves from loose .md (read via read_text/rglob, silent empty
fallback on a miss) into importable .py modules so a missing/renamed prompt is a
loud ImportError/KeyError, not a half-built prompt. See
.claude/tasks/PLAN-prompts-md-to-py.md.

GUARANTEE ("not 1 word drifts"): for every file, the generated module's constant
is re-exec'd and asserted byte-equal to the original `md.read_text(encoding=utf-8)`
(the exact value the current loaders consume). Any mismatch -> abort, write nothing
further, report the offending file.

This script only CREATES new .py files (+ __init__.py + registry.py). It never edits
or deletes existing code. Re-runnable. Run:
    .venv\\Scripts\\python.exe services\\scripts\\convert_prompts_to_py.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # ...\SENA
SERVICES = REPO / "services"


# ── prompt-set declarations ──────────────────────────────────────────────────
# Each set: a base dir under services/, the template file (or None), and how step
# files are discovered. Output .py sits next to the source .md (same tree).

VOICE_SETS = [
    {
        "name": "onboarding",
        "dir": SERVICES / "onboarding" / "prompts",
        "template": "onboarding_system.md",
        "steps_glob": "steps/**/*.md",
        "modes_glob": "modes/*.md",
    },
    {
        "name": "case_review_voice",
        "dir": SERVICES / "case_review" / "voice" / "prompts",
        "template": "case_note_system.md",
        "steps_glob": "steps/**/*.md",
        "modes_glob": "modes/*.md",
    },
]

# Bedrock single-file prompts: each .md -> sibling .py with constant PROMPT.
SINGLE_PROMPTS = [
    SERVICES / "case_review" / "prompts" / "classify.md",
    SERVICES / "case_review" / "prompts" / "summarize.md",
]

# steps/README.md is documentation, never a prompt.
SKIP_NAMES = {"README.md"}


# ── codegen ──────────────────────────────────────────────────────────────────

def _encode_constant(var: str, text: str) -> str:
    """Return source `VAR = <triple-quoted raw>` that re-exec's byte-equal to text.

    Prefers readable raw triple-quote; falls back across delimiters; last resort
    is repr (always exact). Caller re-exec-verifies regardless.
    """
    # Raw strings cannot end in an odd run of backslashes, and cannot contain the
    # closing delimiter. Try each safe form in order of readability.
    for q in ('"""', "'''"):
        if q in text:
            continue
        if text.endswith("\\"):
            continue
        candidate = f"{var} = r{q}{text}{q}\n"
        if _roundtrip_ok(var, candidate, text):
            return candidate
    # Fallback: repr() — exact but not pretty. Split to keep lines sane.
    return f"{var} = {text!r}\n"


def _roundtrip_ok(var: str, source: str, expected: str) -> bool:
    ns: dict[str, object] = {}
    try:
        exec(compile(source, "<gen>", "exec"), ns)  # noqa: S102 - trusted local content
    except SyntaxError:
        return False
    return ns.get(var) == expected


def _write_module(py_path: Path, var: str, text: str, *, header: str) -> None:
    source = _encode_constant(var, text)
    if not _roundtrip_ok(var, source, text):
        raise SystemExit(f"FIDELITY ABORT: round-trip mismatch generating {py_path}")
    # File-level ruff silence: these are byte-exact prompt data, not code — they
    # legitimately have long lines + significant trailing whitespace. ruff format
    # never edits string contents, so fidelity is safe; this only suppresses lint.
    py_path.write_text(f'# ruff: noqa\n"""{header}"""\n\n{source}', encoding="utf-8")


def _ensure_pkg(d: Path) -> None:
    init = d / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")


def _module_name(stem: str) -> str:
    return stem  # step_id == filename stem (already valid identifiers)


def convert_voice_set(spec: dict) -> dict:
    base: Path = spec["dir"]
    if not base.is_dir():
        raise SystemExit(f"missing prompt dir: {base}")
    report: dict = {"name": spec["name"], "files": [], "steps": [], "modes": []}

    # packages need __init__.py for the registry's relative imports
    _ensure_pkg(base)

    # template
    tmpl_md = base / spec["template"]
    text = tmpl_md.read_text(encoding="utf-8")
    _write_module(tmpl_md.with_suffix(".py"), "TEMPLATE", text,
                  header=f"Auto-generated from {tmpl_md.name}. Edit here; .md is gone.")
    report["files"].append(tmpl_md.name)

    # modes
    modes: list[tuple[str, str]] = []
    for md in sorted(base.glob(spec["modes_glob"])):
        if md.name in SKIP_NAMES:
            continue
        _ensure_pkg(md.parent)
        text = md.read_text(encoding="utf-8")
        _write_module(md.with_suffix(".py"), "PROMPT", text,
                      header=f"Auto-generated from {md.name}.")
        modes.append((md.stem, md.relative_to(base).with_suffix("").as_posix()))
        report["modes"].append(md.stem)

    # steps (step_id is globally unique across subfolders — assert it)
    steps: list[tuple[str, str]] = []
    seen: dict[str, Path] = {}
    for md in sorted(base.glob(spec["steps_glob"])):
        if md.name in SKIP_NAMES:
            continue
        if md.stem in seen:
            raise SystemExit(
                f"DUPLICATE step_id '{md.stem}': {seen[md.stem]} vs {md} "
                "(registry lookup would be ambiguous)"
            )
        seen[md.stem] = md
        _ensure_pkg(md.parent)
        text = md.read_text(encoding="utf-8")
        _write_module(md.with_suffix(".py"), "PROMPT", text,
                      header=f"Auto-generated from {md.name}.")
        steps.append((md.stem, md.relative_to(base).with_suffix("").as_posix()))
        report["steps"].append(md.stem)

    _write_registry(base, modes, steps)
    return report


def _rel_import(dotted_from_base: str) -> str:
    # "steps/client/personal_information" -> ".steps.client.personal_information"
    return "." + dotted_from_base.replace("/", ".")


def _write_registry(base: Path, modes: list[tuple[str, str]], steps: list[tuple[str, str]]) -> None:
    lines = [
        "# ruff: noqa",
        '"""Auto-generated prompt registry. Loud lookups replace silent file misses.',
        "",
        "TEMPLATE: the base system prompt.  STEPS: step_id -> rules text.",
        "MODES: mode -> rules text.  Missing key -> KeyError at call site (by design).",
        '"""',
        "from __future__ import annotations",
        "",
        f"from .{base_template_module(base)} import TEMPLATE as TEMPLATE",
    ]
    for step_id, rel in steps:
        lines.append(f"from {_rel_import(rel)} import PROMPT as _step_{step_id}")
    for mode_id, rel in modes:
        lines.append(f"from {_rel_import(rel)} import PROMPT as _mode_{mode_id}")
    lines.append("")
    lines.append("STEPS: dict[str, str] = {")
    for step_id, _ in steps:
        lines.append(f"    {step_id!r}: _step_{step_id},")
    lines.append("}")
    lines.append("")
    lines.append("MODES: dict[str, str] = {")
    for mode_id, _ in modes:
        lines.append(f"    {mode_id!r}: _mode_{mode_id},")
    lines.append("}")
    lines.append("")
    (base / "registry.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


_BASE_TEMPLATE_MODULE: dict[str, str] = {}


def base_template_module(base: Path) -> str:
    return _BASE_TEMPLATE_MODULE[str(base)]


def convert_single(md: Path) -> None:
    _ensure_pkg(md.parent)
    text = md.read_text(encoding="utf-8")
    _write_module(md.with_suffix(".py"), "PROMPT", text,
                  header=f"Auto-generated from {md.name}.")


def main() -> int:
    print("=== prompt md -> py converter ===")
    for spec in VOICE_SETS:
        _BASE_TEMPLATE_MODULE[str(spec["dir"])] = Path(spec["template"]).stem
    for spec in VOICE_SETS:
        rep = convert_voice_set(spec)
        print(f"[{rep['name']}] template+{len(rep['modes'])} modes+{len(rep['steps'])} steps")
        print(f"    steps: {sorted(rep['steps'])}")
        print(f"    modes: {sorted(rep['modes'])}")
    for md in SINGLE_PROMPTS:
        if not md.is_file():
            raise SystemExit(f"missing single prompt: {md}")
        convert_single(md)
        print(f"[single] {md.relative_to(SERVICES)} -> {md.with_suffix('.py').name}")
    print("OK — all modules generated and round-trip byte-verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
