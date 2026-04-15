---
title: Deployment Environment
type: topic
tags: [deployment, cloud, infra, blocked]
sources: ["[[src-technical-decisions]]", "[[src-remaining-questions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Deployment Environment

Status: **blocked on [[cloud-provider-decision]]**.

## What we know

- **AU region required** ([[australian-data-residency]])
- Postgres + pgvector managed option preferred
- Containerised — FastAPI + LiveKit Agents both run as containers
- Redis (managed) preferred over self-hosted

## Open choices

- **Cloud provider** — GCP vs AWS vs Azure (blocked on client)
- **Compute** — Cloud Run / ECS / ACA (serverless containers) vs Kubernetes (EKS/GKE/AKS)
- **Managed DB** — RDS / Cloud SQL / Azure Flexible Postgres
- **LiveKit hosting** — LiveKit Cloud vs self-hosted on the chosen compute platform

## Bias

For a 2-person team ([[team-capacity]]), lean toward:
- Managed databases (no self-hosted Postgres ops)
- Serverless-flavoured compute (avoid K8s maintenance)
- LiveKit Cloud if AU region is available and pricing is sensible

## Connections

- Hub: [[Client-Requirements]], [[Architecture]]
- Related: [[cloud-provider-decision]], [[australian-data-residency]], [[team-capacity]]
