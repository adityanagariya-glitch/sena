---
name: postmortem
description: Blameless postmortem for an ML/system incident. Use when the user reports something broke in production, a model regression shipped, a training run was wasted, or a data pipeline failed. Walks through timeline, root cause, contributing factors, what worked, action items. Systemic fixes over individual blame.
argument-hint: [the incident — what broke and when]
allowed-tools: Read, Grep, Glob, Bash(git log:*), Bash(git diff:*)
---

# /postmortem — Blameless Incident Review

## Phase 1 — Gather the facts

Ask the user for (in order):

1. **What happened, in one sentence.**
2. **Timeline:** when was it deployed/started → when was it detected → when was it mitigated → when was it resolved. Approximate is fine; the structure matters.
3. **Impact:** what was affected? Users? Cost? Revenue? Data integrity? Model performance?
4. **How was it detected:** alert, user report, you noticed it accidentally?
5. **What you've done so far:** mitigation steps, rollback, etc.

## Phase 2 — Root cause (not "human error")

Walk through the Five Whys, **silently**, then present the chain. "Human error" is never an acceptable root cause — if someone made a mistake, the systemic cause is the system that allowed it.

Common ML/AI root-cause patterns:
- **Training-serving skew:** different preprocessing, different feature order, different tokenizer.
- **Silent data drift:** input distribution moved, no monitor caught it.
- **Eval-set contamination:** the model "passed" because the test was leaked into training.
- **Missing baseline:** no one noticed degradation because there's nothing to compare against.
- **No rollback path:** model promoted without keeping prior version warm.
- **Latent dependency:** a library update changed behavior; no version pin.
- **Config silently wrong:** Hydra/yaml typo loaded a default; no schema validation.
- **No canary / no A/B:** went straight to 100% traffic.

## Phase 3 — Output

```
## Postmortem: <incident name>

### Summary
<2-3 sentences: what happened, who was affected, how it was resolved.>

### Timeline (in user's timezone)
- HH:MM — <event>
- HH:MM — <event>
- ...

### Impact
- Users affected: <number or "all" or "users in segment X">
- Duration: <detection to mitigation, and detection to resolution>
- Cost: <compute wasted / revenue impact / SLA budget burned>

### Root cause
The trigger was <X>. The root cause was <Y> — <mechanism>.

### Contributing factors (the system that allowed it)
- <factor 1> — <one line on why this mattered>
- <factor 2> — ...

### What worked
- <thing that went right — recovery, alerting, runbook>

### What didn't
- <thing that went wrong — slow detection, missing rollback, etc.>

### Action items (each owned, dated, and with a verification step)
- [ ] **Prevent:** <change that makes this class of bug impossible> — owner, ETA, "done when X is true."
- [ ] **Detect:** <monitor/alert/test that would catch this earlier> — owner, ETA.
- [ ] **Recover faster:** <runbook improvement / rollback automation> — owner, ETA.

### Lessons
1. <one-line lesson, focused on systems not people>
2. <...>
```

## Hard rules

- **No blame on individuals.** Name systems, not people. "The deploy script doesn't gate on eval results" not "Alice forgot to run evals."
- **No "we'll be more careful next time."** That's not an action item; it's a wish. Real action items are testable.
- **Three-tier action items:** prevent (stops recurrence), detect (catches earlier), recover (limits damage). Every postmortem needs all three.
- **Action items have owners and ETAs.** No owner = no action item.
- **Distinguish trigger from root cause.** The trigger is what kicked it off; the root cause is why the system was vulnerable to that trigger.
