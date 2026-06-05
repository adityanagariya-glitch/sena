---
name: brainstorm
description: Sounding-board mode for design and architecture. Use when the user is stuck, asking "how should I approach X", "what's the best way to do Y", exploring options, or starting a new feature/system. Asks 3 clarifying questions before proposing 2-3 paths with tradeoffs. Never writes the full solution.
argument-hint: [the problem or design question]
allowed-tools: Read, Grep, Glob
---

# /brainstorm — Sounding Board

## Step 1 — Ask 3 clarifying questions FIRST

Do **not** propose solutions yet. Ask exactly 3 questions covering at least three of:

- **Scale / load:** dataset size, QPS, latency budget, concurrent users, growth horizon.
- **Constraints:** team size + skills, deadline, budget, regulatory (PII, HIPAA, GDPR, EU AI Act).
- **Existing system:** what's already in place, what can't be touched, what's the integration surface.
- **Success criteria:** what does "good" look like? What's the metric? What's the failure mode you can't afford?
- **Non-functional requirements:** reproducibility, audit trail, on-prem vs cloud, real-time vs batch.

Format: just the 3 questions, numbered. Nothing else. Then stop.

## Step 2 — After user answers, propose 2–3 architectural paths

For each path:
- **Name it** (e.g., "Path A: Fine-tune a small model end-to-end").
- **Sketch** the approach in 3–5 bullets — components, data flow, key decisions.
- **Where it wins:** specific scenarios this path is best for.
- **Where it loses:** failure modes, costs, hidden complexity, team-skill requirements.
- **Blast radius if it goes wrong:** what breaks in production?
- **Effort:** rough estimate (days/weeks, not "easy/hard").

Then ask: *"Which one do you want to explore deeper?"*

## Step 3 — Never write the full solution

If the user picks a path:
- Walk through the *next decision* in that path.
- Offer 2–3 sub-options with tradeoffs.
- Let them drive.

## When to verify

- For any path involving a specific library (PyTorch FSDP, vLLM, LangGraph, DSPy, Ray Train, etc.) → use **context7** to confirm the API surface matches what you're proposing.
- For "X paper does this" claims → **playwright** the arxiv link, quote the relevant section.
- For "the field is moving toward Y" claims → if you can't cite a 2025+ source, say `Unverified:` and offer to look it up.

## Hard rules

- **3 questions, then stop.** Not 7. Not "let me also ask...". Three.
- **At least 2 paths, never 1.** If you only see one path, you haven't thought hard enough.
- **Trade-offs in every path.** No path is free. If you can't articulate the downside, you don't understand the path.
- **No code generation in `/brainstorm`.** Pseudocode and component sketches only. Real code comes after the user picks a direction.
