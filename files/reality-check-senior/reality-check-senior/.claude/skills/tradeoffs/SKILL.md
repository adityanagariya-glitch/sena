---
name: tradeoffs
description: Honest comparison of two or more options — libraries, patterns, models, architectures, approaches. Use when the user asks "X vs Y", "which should I pick", "is A better than B for my case". Uses sequential-thinking MCP for structured deliberation. Asks for context if missing; never gives a recommendation without it.
argument-hint: [A vs B, or list of options]
allowed-tools: Read
---

# /tradeoffs — Structured Comparison

## Step 1 — Establish context (if missing)

Before comparing, you need:
- **Use case:** what is this for? (Inference at scale? Research prototype? Production training? Fine-tuning a 7B?)
- **Constraints:** budget, team skills, existing stack, hardware, deadline.
- **Decision-blocker:** what specifically is blocking the choice?

If any of these is missing → ask before answering. **Generic "X vs Y" answers are bad mentorship** because the right answer depends on context.

## Step 2 — Use Sequential Thinking for the comparison

For each non-trivial comparison, call `mcp__sequential-thinking__sequentialthinking` and walk through:

1. What does each option actually do? (Verify via **context7** if either is a library — APIs change, hot-takes lag.)
2. Where does each win? (Specific scenarios, not "it's better at performance.")
3. Where does each lose? (Hidden costs, failure modes, ops burden, team-skill assumptions.)
4. Reversibility: how hard is it to switch later? (Strong tie-breaker on uncertain decisions.)
5. What's the *real* differentiator in *this user's context*?

## Step 3 — Output

Use this shape (not the standard three-block format):

### Steelman of each option (1 paragraph each)
- The strongest case for option A, written as its advocate would write it.
- Same for B (and C if applicable).

### Honest comparison table

| Dimension | A | B |
|---|---|---|
| When it wins | … | … |
| Hidden cost | … | … |
| Team skill needed | … | … |
| Ops burden | … | … |
| Reversibility | … | … |
| Cost at scale | … | … |

### Recommendation for your context

A specific, opinionated recommendation **for the user's stated context**, with the reasoning. Format:

> *Given that you have <constraint 1>, <constraint 2>, and <constraint 3>, pick **B** because <mechanism>. You'll pay the cost of <specific downside>, which is acceptable because <reason>. If <X changes>, revisit and consider A.*

If the context truly doesn't determine the answer → say so. "This is a coin-flip given what you've told me; here's what would tip it."

## Hard rules

- **Never recommend by reputation.** "Use PyTorch because it's popular" is not analysis. Show the mechanism.
- **Steelman before critiquing.** If you can't articulate the strongest case for the option you're rejecting, you don't understand it well enough to reject it.
- **The honest answer is sometimes "it doesn't matter."** Don't manufacture a winner.
- **One quote per source maximum** if citing benchmarks/papers; paraphrase the rest.
- **Verify version-specific claims via context7** — "X is faster than Y" was true in 2023 may not be true in 2026.
