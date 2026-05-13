---
title: XML Structure Audit
date: 2026-04-22
trigger: Instructions.xml — surgical XML wrapping of rule-dense markdown
constraint: Zero character changes; only wrapper-tag insertion
---

# XML Restructure Audit — 2026-04-22

## Files Modified (XML wraps applied)

| File | Sections wrapped | Why XML helps |
|------|-----------------|---------------|
| `CLAUDE.md` | `<hard_constraints>`, `<non_negotiables service="case_review">`, `<issues_solved_protocol>`, `<setup_rules>`, `<gemini_rules priority="MANDATORY">` (6 numbered `<rule>` children with type+severity attrs), `<cleanup_rule>`, `<ignored_folders>` (with `<never_read>` + `<exception>`), `<add_component_protocol>` | 8 wraps. Project's master rule file. Anthropic models heavily attend to XML-tagged constraints — converting MANDATORY blocks gives Claude unambiguous parse anchors. The numbered `<rule id="N">` pattern in Gemini Rules is the highest-leverage change: each rule becomes individually addressable ("rule id=6 forbidden-pattern critical"). |
| `.claude/commands/solve.md` | `<workflow>` containing 4 `<step n="N" type="...">` elements; `<rules>` for the post-workflow rules | Slash command instructions read by Claude on every `/solve` invocation. Step-numbered XML lets Claude branch correctly when the user provides ambiguous symptoms. |
| `.claude/issues-solved/README.md` | `<lookup_workflow trigger="before-debugging">`, `<add_workflow trigger="non-trivial-fix">`, `<exclusions>`, `<format_rules>` | Protocol contract. Trigger attributes make the "when to use" decision parseable without re-reading prose. |
| `AGENTS.md` | `<critical_constraints priority="MANDATORY" type="legal-compliance">`, `<agent_guidance>`, `<ignored_folders>`, `<error_handling_rules>` | Agentic-coding guidance file. Critical-constraints + ignored-folders are the highest-violation-cost rules in the file. |

## Convention Used

All wrapper tags carry semantic intent. Common attributes:
- `priority="MANDATORY"` — non-negotiable rule blocks
- `type="forbidden-pattern" | "legal-compliance" | "model-selection" | "api-pattern" | "capability-limit" | "prerequisite"` — categorizes what the rule governs
- `severity="critical"` — flags rules where violation broke production before
- `trigger="..."` — names the user phrase or event that activates the rule
- `id="N"` — addressable rule identity inside numbered lists
- `scope="..."` — the code surface the rule applies to

## Files Not Modified — Candidates Worth Future Wrapping

| File | Reason deferred | Wrapping target if revisited |
|------|----------------|------------------------------|
| `.claude/SESSION_START.md` | Already heavily structured with markdown tables; lower marginal value | `<read_order>`, `<must_read>`, `<do_not_read>` tags around the existing tables |
| `.claude/issues-solved/TEMPLATE.md` | Frontmatter already serves as structural anchor | `<symptom>`, `<root_cause>`, `<fix>`, `<failed_attempts>` body sections |
| `.claude/issues-solved/0001-3*.md` | Issue entries (data, not rules); markdown headings already segment them | Skip — issue content is descriptive, not directive |
| `.claude/issues-solved/INDEX.md` | Pure table; XML adds no parsing value over markdown | Skip |
| `.claude/tasks/TASKS.md` | Task list with status legends; would benefit from `<active_tasks>`, `<backlog>`, `<paused>` wrappers but content churns frequently — XML adds maintenance cost | Defer until task schema stabilizes |
| `.claude/gsd-instructions.md` | Not read; should be audited next pass | TBD |
| `GEMINI.md` | Not read; high-likelihood candidate (Gemini-specific rules duplicated from CLAUDE.md) | `<gemini_rules>` consistent with CLAUDE.md's wrapping |
| `GEMINI_LIVE_SETUP_GUIDE.md` | Setup guide; rule density unclear without read | `<setup_steps>`, `<env_vars>`, `<verification>` |
| `CLIENT_GEMINI_ACCESS_GUIDE.md` | Client-facing; likely procedural | `<access_workflow>` |
| `case_note_review_master_prompt.md` | Master prompt — high value, but prompts have their own template language; risk of confusing the model with double-wrapping | Audit carefully before changing |
| `FLUTTER_DEV_HANDOFF.md`, `FLUTTER_ECHO_FIX.md`, `FLUTTER_SCHEMA_ORDER_FIX.md`, `FLUTTER_VOICE_INTEGRATION.md`, `FLUTTER_VOICE_INTEGRATION_FIXES.md` | Handoff docs for human Flutter dev — Claude rarely reads them mid-task | Lower priority |
| `HANDOFF_VOICE_ONBOARDING.md`, `NGROK_TUNNEL_GUIDE.md` | Procedural guides; low rule-density per token | Skip unless touched |
| `Folder_structure.md` | Layout reference; static | Skip |
| `answers.md` | Q&A doc; conversational not directive | Skip |
| `Building Real-Time Conversational AI wit.md` | Research notes; not rule content | Skip |
| `.planning/PROJECT.md`, `ROADMAP.md`, `STATE.md`, `REQUIREMENTS.md`, `FEATURES_LEFT.md`, `GEMINI_LIVE_NATIVE_SCOPE.md`, `ONBOARDING_VOICE_API_PLAN.md`, `paused_state_phase_d_camera_screen_ingress.md` | Plan docs; structural value is medium but content evolves rapidly — XML maintenance burden outweighs benefit | Skip |
| `sena-ai/services/case_review/src/case_review/prompts/summarize.md`, `classify.md` | Active LLM prompts — risk of confusing the runtime model with literal XML tags it then echoes | DO NOT WRAP |
| `Exported Documents/Claude Code Study Notes.md` | Personal notes; not project rules | Skip |

## Files Explicitly Skipped (Forbidden / Low Value)

- `archive/**` — DO-NOT-READ per project rules
- `.venv/**`, `.vscode/**` — DO-NOT-READ
- `ndis_markdown_docs/**` — token monster; raw NDIS PDFs converted to markdown
- `.pytest_cache/**` — generated
- `.claude/skills/gemini-skills-main/**` — third-party vendored skill files
- `*/site-packages/**` — installed package docs
- `*/LICENSE.md` — legal text, not project rules
- `Exported Documents/Claude Code ΓÇö Study Notes.md` — personal notes

## Critical Compliance Note

Per Instructions.xml's "DATA RETENTION RULES":
- **No character was changed inside any wrapped content.**
- Only XML open/close tags were inserted (additive only).
- All YAML frontmatter preserved exactly.
- Typos and grammar (`thsi`, `watn`, `Fro`, etc.) intentionally preserved across the codebase per the no-fix rule — multiple instances seen in TASKS.md and notes; not touched.

## Validation Suggestion

Run a `git diff` and confirm only ` <tag>` / `</tag>` lines were added. If any text inside a wrapped block was modified, the audit failed and the affected file should be reverted.

## Next Pass Targets (Priority Order)

1. `GEMINI.md` — likely high rule-density Gemini guidance, candidate for `<gemini_rules>` consistent with CLAUDE.md
2. `.claude/SESSION_START.md` — high read-frequency, would benefit from `<must_read>` / `<do_not_read>` wrappers
3. `.claude/gsd-instructions.md` — unread; audit and decide
4. `case_note_review_master_prompt.md` — careful audit; do NOT wrap if it's a runtime prompt
