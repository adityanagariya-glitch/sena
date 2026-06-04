# Per-step prompt fragments

Step files are grouped by flow into subfolders (`client/`, `staff/`, …). Each
file is loaded by `prompt_builder.build_system_prompt` when `turn.step.id`
matches the filename — the loader searches **recursively** under this folder, so
the subfolder is for human organisation only (e.g.
`client/personal_information.md` loads when `step.id == "personal_information"`;
`staff/staff_personal_information.md` loads when
`step.id == "staff_personal_information"`).

**The filename must equal the step_id and be globally unique across all
subfolders** — the loader resolves `{step_id}.md` from anywhere under `steps/`.
Adding a new onboarding flow = add a `steps/<flow>/` subfolder with its step
files; the loader needs no change.

Missing file → no step-specific rules. Edit one file to change one step's
behaviour — the base prompt (`../onboarding_system.md`) stays generic and
step-agnostic.

Keep each fragment focused on behaviour that is unique to that step:
- Per-step submission cadence (e.g. "submit_step on 'next' / 'save'")
- Per-step enum strictness (when this step has tricky enums)
- Per-step repeatable walk-through order
- Per-step conditional fields (e.g. plan_manager show/hide)

Do NOT duplicate generic rules already in the base prompt.
