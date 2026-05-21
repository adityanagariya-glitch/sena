---
id: "0006"
title: LangGraph node name collides with TypedDict state key — silent wrong routing
date: 2026-05-01
symptom_keywords: LangGraph node name TypedDict state key collision routing wrong graph
files_affected: pipeline/graph.py
---

## Symptom
Graph compiles without error but routes incorrectly — nodes are skipped or executed
in wrong order. No exception raised; just wrong pipeline behaviour.

## Root Cause
LangGraph uses the node name as both the graph node identifier AND as a key lookup
in the state TypedDict. If a node is named `triage` and the state has a key `triage`,
LangGraph reads the state value instead of executing the node.

## Fix
All node names must have the `_step` suffix to avoid colliding with state dict keys:

```python
# CORRECT
graph.add_node("triage_step", triage_node)
graph.add_node("rag_step", rag_node)
graph.add_node("evaluator_step", evaluator_node)
graph.add_node("cross_check_step", cross_check_node)
```

State TypedDict keys stay as short names (`triage`, `rag_result`, etc.).

## Verification
Pipeline routes correctly — triage_step → rag_step → evaluator_step → cross_check_step
in sequence; early exit on `flagged=False` works.

## Watch Out For
- This applies to ALL LangGraph graph builders, not just StateGraph
- Adding a new state key? Check it doesn't match an existing node name
