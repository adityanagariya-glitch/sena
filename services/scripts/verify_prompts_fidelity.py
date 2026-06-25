"""Verify prompt .py modules are byte-identical to the original .md (git HEAD)
and that every registry imports cleanly.

Ground truth = `git show HEAD:<md>` (the committed prompt), LF-normalized to match
what the runtime loader always produced via read_text(). A CRLF/LF-only delta is
NOT a word change and is normalized away (see PLAN invariant #5).

Run AFTER convert_prompts_to_py.py, BEFORE deleting the .md:
    .venv\\Scripts\\python.exe services\\scripts\\verify_prompts_fidelity.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"
SKIP = {"README.md"}

PROMPT_DIRS = [
    SERVICES / "onboarding" / "prompts",
    SERVICES / "case_review" / "voice" / "prompts",
    SERVICES / "case_review" / "prompts",
]
TEMPLATE_STEMS = {"onboarding_system", "case_note_system"}

# (registry import path, sys.path root) — proves the package wiring resolves.
REGISTRIES = [
    ("prompts.registry", SERVICES / "onboarding"),
    ("voice.prompts.registry", SERVICES / "case_review"),
]


def _git_head_text(md: Path) -> str | None:
    rel = md.relative_to(REPO).as_posix()
    try:
        raw = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO, capture_output=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None  # not committed (e.g. brand-new file) — skip baseline cmp
    return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _const_of(py: Path) -> str:
    var = "TEMPLATE" if py.stem in TEMPLATE_STEMS else "PROMPT"
    ns: dict[str, object] = {}
    exec(compile(py.read_text(encoding="utf-8"), str(py), "exec"), ns)  # noqa: S102
    return ns[var]  # type: ignore[return-value]


def main() -> int:
    failures: list[str] = []
    checked = skipped = 0
    for d in PROMPT_DIRS:
        for md in sorted(d.rglob("*.md")):
            if md.name in SKIP:
                continue
            py = md.with_suffix(".py")
            if not py.exists():
                failures.append(f"MISSING .py for {md.relative_to(SERVICES)}")
                continue
            new = _const_of(py).replace("\r\n", "\n").replace("\r", "\n")
            base = _git_head_text(md)
            if base is None:
                skipped += 1
                # still confirm .py matches the on-disk .md
                base = md.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if new != base:
                rel = md.relative_to(SERVICES)
                failures.append(f"DRIFT {rel} (len new={len(new)} base={len(base)})")
            else:
                checked += 1

    # registry import wiring
    reg_ok: list[str] = []
    for mod, root in REGISTRIES:
        sys.path.insert(0, str(root))
        try:
            import importlib
            m = importlib.import_module(mod)
            assert isinstance(m.TEMPLATE, str) and m.TEMPLATE
            assert isinstance(m.STEPS, dict) and m.STEPS
            assert isinstance(m.MODES, dict) and m.MODES
            reg_ok.append(f"{mod}: TEMPLATE ok, {len(m.STEPS)} steps, {len(m.MODES)} modes")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"REGISTRY {mod} import failed: {type(exc).__name__}: {exc}")
        finally:
            sys.path.remove(str(root))

    print(f"byte-checked: {checked}  (baseline-vs-disk fallback: {skipped})")
    for line in reg_ok:
        print("registry OK -", line)
    if failures:
        print("\n*** FAILURES ***")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL FIDELITY CHECKS PASS — .py constants byte-identical to git HEAD .md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
