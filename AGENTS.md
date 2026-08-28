# AGENTS.md — CA Notice AI Agent Rules

## 1. Purpose

This repository is developed through small, explicitly scoped tasks.

The user controls the development sequence.

Do not assume authority to continue to the next architecture step,
refactor unrelated code, clean up the repository, or expand task scope.

## 2. Context Loading — Token Efficiency

Do NOT automatically read historical project-memory files.

In particular:

- Do NOT automatically read:
  `docs/history/PROJECT_MEMORY_ARCHIVE.md`

- Do NOT load old session logs, old prompts, baselines, large outputs,
  audit documents, or unrelated architecture documents unless the current
  task explicitly requires them.

For every task, use the minimum necessary context.

Normally read only:

1. this AGENTS.md;
2. the files explicitly named in the user's task;
3. source files directly involved in the requested change;
4. directly relevant tests;
5. only the relevant section(s) of the architecture specification.

If the task says "current Phase 2 architecture" without naming a file,
the current authoritative architecture is:

    docs/architecture/ARCHITECTURE_SPEC_v1_1.md

until the user explicitly supersedes it.

Historical architecture specifications are not implementation authority.

## 3. Source-of-Truth Order

When information conflicts, use this priority:

1. current code and executable tests;
2. the architecture specification explicitly named by the user;
3. the user's current task instructions;
4. Git history/current diff when relevant;
5. historical documentation or archived memory;
6. agent assumptions.

Never override current code/specification with an old historical memory entry.

## 4. Before Editing

Before modifying files:

    git status

If the working tree is already dirty, preserve existing unrelated changes.

Do not restore, overwrite, stage, or modify pre-existing unrelated changes.

Read only the context necessary for the requested task.

## 5. Scope Discipline

Modify ONLY files explicitly allowed by the current task.

Do NOT:

- perform unrelated cleanup;
- refactor working code outside scope;
- rename unrelated files;
- rewrite prompts unless requested;
- change providers/models unless requested;
- change requirements/dependencies unless requested;
- start the next phase or step automatically.

If completing the requested task genuinely requires modifying a file outside
the permitted scope:

STOP and report why.

Do not silently expand scope.

## 6. Architecture Rules

Keep deterministic work outside the LLM whenever practical.

Examples:

- dates and deadline arithmetic → Python;
- monetary arithmetic → Python;
- workflow lookup → deterministic Python/configuration;
- validation → Python;
- structured state/status transitions → Python.

Use LLMs for tasks such as:

- focused notice classification;
- structured fact extraction;
- reasoning;
- explanation;
- drafting.

All application LLM calls must go through the project's existing:

    modules/llm_client.py

and existing routing layer.

Do not bypass the router with direct provider calls unless a task explicitly
changes the LLM architecture.

## 7. Safety / Tax Domain Discipline

Never convert a departmental allegation into a confirmed taxpayer fact.

Do not invent:

- taxpayer facts;
- legal citations;
- case law;
- statutory text;
- notice dates;
- service dates;
- reply forms;
- evidence;
- legal conclusions.

When the architecture requires verification, preserve that uncertainty.

Unsupported notice types must not be forced into a specialist workflow.

## 8. Secrets

Never print, expose, copy into documentation, or commit:

- API keys;
- .env contents;
- credentials;
- tokens;
- secrets.

`.env` remains local and ignored by Git.

## 9. Dependencies

Do not add or remove libraries without explicit user authorization.

Do not change:

    requirements.txt

unless the current task explicitly permits it.

## 10. Git

Do not commit unless the user explicitly requests a commit.

Prefer one architectural unit per commit.

Never stage unrelated changes together merely because they are present in
the working tree.

Do not use destructive Git commands unless explicitly instructed.

## 11. Testing

Run only the tests relevant to the requested task unless the user asks for
a broader regression run.

Do not make unnecessary live LLM/API calls when deterministic/offline tests
are sufficient.

Never change production behavior merely to make a test pass unless that
behavior change is part of the approved task.

## 12. End-of-Task Report

Do NOT update any automatic memory/state/session file.

At the end of project work, report concisely:

- files created;
- files modified;
- files intentionally left untouched;
- tests/verification commands run;
- pass/fail counts;
- errors encountered;
- number of attempts when relevant;
- what fixed each error;
- remaining ambiguity/blocker;
- `git status`;
- `git diff --stat`.

Do not dump large raw logs unless requested.

## 13. Manual Handoff Model

Project continuity is maintained through:

- Git commits/history;
- current source code;
- tests;
- authoritative architecture specifications;
- task-specific prompts supplied by the user.

Historical memory is optional reference material, not automatic boot context.

A new coding agent should be able to work from a precise task prompt without
reading the project's full historical diary.
