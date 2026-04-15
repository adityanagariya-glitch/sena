---
title: OCR Service
type: topic
tags: [ocr, service, scaffolded, planned]
sources: ["[[src-technical-decisions]]", "[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# OCR Service

Planned service at `sena-ai/services/ocr/`. Directory exists but **no implementation yet**.

## Purpose

Extract structured data from documents that support workers encounter:
- Participant ID cards, NDIS plan documents
- Medication charts, health care plans
- Incident report scans, consent forms

## Open design questions

- **OCR provider** — GCP Document AI vs AWS Textract vs Azure Document Intelligence (currently blocked on [[cloud-provider-decision]])
- **Integration surface** — REST endpoint vs event-driven (consume from SNS?)
- **Structure-aware** — field-typed extraction (templated forms) vs free-form text output
- **Accuracy thresholds** — when to reject OCR output vs require human re-entry

## Why not built yet

Voice service is the priority for initial launch. OCR planned for milestone after Flow B stabilises.

## Connections

- Hub: [[Architecture]]
- Related: [[cloud-provider-decision]], [[monorepo-structure]]
