---
description: MANDATORY protocol when user says "I am adding X" (new directory, service, file, or external resource). Triggers a documentation sweep BEFORE any code work begins. Load when "adding" trigger fires.
trigger_phrases:
  - "I am adding"
  - "I'm adding"
  - "adding a new service"
  - "adding a new directory"
  - "new dependency"
  - "new external resource"
---

# Adding New Project Components (MANDATORY PROTOCOL)

When the user says **"I am adding X"** (a new directory, service, file, or external resource), update ALL of the following BEFORE doing anything else:

| File | What to update |
|------|---------------|
| `CLAUDE.md` (root project file) | Add to root-level file tree + add a dedicated section describing the component |
| `.claude/SESSION_START.md` | Add to the READ-IF-RELEVANT table under the appropriate task area |
| `.claude/tasks/TASKS.md` | Update any blocked tasks that are now unblocked by the new component |
| `~/.claude/projects/.../memory/MEMORY.md` | Add an index entry pointing to a new memory file |
| Create `memory/project_<name>.md` | Describe what the component is and how to use it |

## Blocking rule

Do NOT start any other work until this update sweep is complete. The sweep ensures future sessions land in the correct state.

## Why this matters

A new component that isn't surfaced in `CLAUDE.md` / `SESSION_START.md` is invisible to the next session. Skipping the sweep = re-discovering the component every session at full token cost.

## Exception

If the addition is genuinely throwaway (one-off script, scratch file in `.gitignore`d location), skip the sweep but note in the working session what was created so the user can decide later.
