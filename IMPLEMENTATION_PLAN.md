# CA Notice AI — Immediate Implementation Plan

## Goal
Transition the current prototype into a workflow-based architecture without breaking the working Streamlit pipeline.

## Step 1 — Inspect existing repository

Required before code changes:
- AGENTS.md
- PROJECT_MEMORY.md
- current Streamlit entrypoint
- document extraction module
- Gemini/DeepSeek invocation path
- prompt loading path
- output rendering
- existing tests

## Step 2 — Add domain contracts first

Create typed models for:
- Case
- Proceeding
- Document
- Fact
- Evidence
- Issue
- Deadline
- Workflow
- LegalReference
- Draft

Do not change UI behavior yet.

## Step 3 — Introduce Fact Ledger

Convert extracted notice information into structured facts with provenance.

Minimum statuses:
CONFIRMED
ALLEGED_BY_DEPARTMENT
NOT_AVAILABLE
REQUIRES_VERIFICATION
INFERRED

## Step 4 — Introduce Deadline Engine

Input:
notice date, service date, response period, hearing date, today.

The engine must return explicit uncertainty when service date is absent.

## Step 5 — Introduce Workflow Registry

Register:
GST_SEC_73_GENERAL
GST_SEC_73_ITC
GST_SEC_73_RCM
GST_SEC_74_FRAUD
GST_SEC_129_MOV

## Step 6 — Make drafting source-bound

Draft generator receives structured facts and evidence state, never unrestricted raw extraction.

## Step 7 — Add validator

Reject/flag:
- unsupported facts
- wrong form
- inconsistent deadline
- unlabelled inference
- unsupported citations

## Step 8 — Regression suite

Run all four fixture notices after every architecture/prompt change.

## Step 9 — CA pilot readiness

Only after regression stability, introduce real CA-reviewed cases.

## Non-goals during this phase

- no complete rewrite
- no Income Tax support
- no autonomous filing
- no case-law automation without verified sources
- no universal mega-prompt
