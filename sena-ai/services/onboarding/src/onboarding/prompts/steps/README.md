# Per-step prompt fragments

Each file in this folder is loaded by `prompt_builder.build_system_prompt`
when `turn.step.id` matches the filename (e.g. `personal_information.md`
loads when `step.id == "personal_information"`).

Missing file → no step-specific rules. Add a new file to add rules for
that step. Edit one file to change one step's behaviour — the base
prompt (`../onboarding_system.md`) stays generic and step-agnostic.

Keep each fragment focused on behaviour that is unique to that step:
- Per-step submission cadence (e.g. "submit_step on 'next' / 'save'")
- Per-step enum strictness (when this step has tricky enums)
- Per-step repeatable walk-through order
- Per-step conditional fields (e.g. plan_manager show/hide)

Do NOT duplicate generic rules already in the base prompt.
