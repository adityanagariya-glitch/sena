# MERGED EXECUTION PLAN: Sprint 0 + Voice Onboarding

Source of truth: Sprint 0 requirements remain governing baseline. Voice flow is preserved and mapped to gates.

## 1) Sprint 0 Baseline (Must/Should)

### Must (hard blockers)
- Monorepo + local runtime working
- Tenant middleware and tenant propagation
- DB schema + RLS baseline migrations
- Tenant isolation test passing
- Code quality gates (ruff/mypy/tests)
- Client answers for cloud/integration/auth (Track B Q1-Q3)

### Should (staging readiness)
- Cloud account and managed Postgres in AU region
- CI/CD pipeline (lint -> test -> build)
- Model access verification
- First staging deployment

## 2) Voice Phase Mapping With Gates

### Phase 1 (Week 1): Contracts and Transport
- API contracts (`FormState`, `ContextPacket`, `FieldUpdate`) -> READY now
- Mock orchestration -> READY now
- LiveKit/WebRTC -> DEFERRED runtime dependency (Module 3 infra)
- Redis session store -> DEFERRED runtime dependency (additive, non-breaking)
- JWT production validation -> BLOCKED until auth decision (Q3)

### Phase 2 (Week 2): Cognitive Core
- Context manager and routing/extraction -> READY against mock provider
- Provider-specific live integration -> BLOCKED until cloud decision (Q1) + model verification
- TTS path -> BLOCKED until provider/cloud finalization

### Phase 3 (Week 3): Reliability and Audit
- Circuit breaker + graceful degradation -> READY
- Voice audit schema (`voice_sessions`, `agent_traces`) -> BLOCKED until Sprint 0 migration baseline is complete
- Voice RLS policies -> BLOCKED until tenant isolation test passes
- HITL event integration -> BLOCKED until integration pattern decision (Q2)

### Phase 4 (Week 4): Perf and UAT
- Dev perf tuning + evals -> READY in dev
- Staging load/UAT -> BLOCKED until Sprint 0 Should gates are passed (cloud, CI/CD, staging)

## 3) Traceability Matrix

| Sprint 0 Requirement | Voice Dependency | Status |
|---|---|---|
| Tenant middleware + auth | JWT validation and tenant-safe requests | Blocked by Q3 |
| DB + RLS baseline migrations | Voice audit schema and RLS parity | Partial |
| Tenant isolation test | Legal gate for voice production data | Incomplete |
| Cloud provider decision (Q1) | Live model integration and deployment path | Open |
| Integration pattern decision (Q2) | HITL queue/data integration | Open |
| Staging/CI readiness | Voice release promotion | Blocked |

## 4) Non-Destructive Integration Sequence

1. Finish Sprint 0 missing baseline (migrations + tenant isolation test + Track B answers).
2. Continue Voice Phases 1-2 in mock/dev mode (no deletion of in-progress code).
3. Add adapters/wrappers to reuse shared tenant middleware and DB patterns.
4. Add feature flags for safe promotion:
   - `VOICE_PROVIDER_MODE=mock|live`
   - `VOICE_REDIS_ENABLED=true|false`
   - `VOICE_JWT_REQUIRED=true|false`
   - `VOICE_HITL_ENABLED=true|false`
5. Promote each capability only when its gate is passed.

## 5) Gate Checklist

### Gate A: Sprint 0 Must
- [ ] Baseline migrations created and runnable
- [ ] Tenant isolation test green
- [ ] No-tenant rejection tests green
- [ ] Track B Q1/Q2/Q3 documented

### Gate B: Sprint 0 Should
- [ ] Cloud and managed Postgres provisioned
- [ ] CI pipeline enforced
- [ ] Model access verified
- [ ] Staging deployment healthy

### Gate C: Voice Production Promotion
- [ ] All Phase 1-4 tasks complete or explicitly deferred
- [ ] Feature flags switched from mock/stub to live only after Gate A/B pass
- [ ] UAT sign-off complete

## 6) Owners
- Senior Lead: auth/JWT, cloud/model decisions, RLS compliance sign-off
- Team Lead: docker/CI, migration execution flow, testing enforcement
- AI Engineers: voice DAG, routing, resilience, evaluation execution

## 7) Final Rule
No active Voice implementation is deleted. Work continues in dev/stub mode where needed, and release is controlled by Sprint 0 gates.
