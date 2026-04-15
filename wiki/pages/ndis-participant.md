---
title: NDIS Participant
type: entity
tags: [ndis, participant, domain, entity]
sources: ["[[src-questions-for-client]]", "[[src-architecture-audit]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-16
updated: 2026-04-16
---

# NDIS Participant

An NDIS participant is a person with a disability who has been approved to receive funding under the National Disability Insurance Scheme. Participants have an individualised plan specifying funded supports and budgets.

## Relevance to SENA

Participants are the **subject** of case notes, not users of the platform. A [[support-worker]] delivers a service to a participant, then uses SENA to document that service via [[flow-b-voice-dictation]] or form-based dictation.

Key participant data SENA stores or processes:
- Participant name and identifiers (referenced in case notes)
- Participant context loaded at session start via [[context-preloading]] (CTX-01 requirement)
- Active shift/service details linked to participant

## Data sensitivity

Participant data is PII and subject to:
- [[australian-data-residency]] — must remain on Australian servers
- [[multi-tenancy]] — zero cross-tenant leakage (a participant at one provider must not be visible to another)
- [[human-in-the-loop]] — any AI-drafted text about a participant requires human approval before submission
- COMPLY-02: PII redaction before structured log emission

## What SENA does not own

Participant plans, budgets, and NDIS registration are managed by the NDIA and the client's participant management module. SENA AI receives participant context via the client platform API — the schema for this is currently undefined (see [[api-contracts]]).

## Connections

- Hub: [[NDIS]]
- Related: [[support-worker]], [[case-notes]], [[context-preloading]], [[multi-tenancy]]
- Entity: [[ndia]] (issues and manages participant plans)
- Open: [[open-questions]] — participant data schema from client platform TBD
