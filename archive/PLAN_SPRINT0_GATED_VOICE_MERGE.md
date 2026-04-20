## Plan: Sprint 0-Gated Voice Onboarding Merge

Recommended approach: keep Voice implementation moving, but enforce Sprint 0 as release-governance gates.

### Steps
1. Build traceability matrix from Voice tasks to Sprint 0 Must/Should.
2. Preserve all Voice phase tasks; label each as Ready / Blocked by Gate / Deferred.
3. Continue implementation in dev with stubs where prerequisites are missing.
4. Gate production promotion on Sprint 0 Must first, then Should.
5. Use feature flags for non-destructive switch from mock to live.

### Core Principle
Do not remove in-progress Voice work; control release through gates.
