---
name: rubric-check
description: Explain what full marks needs for an EcoGuard rubric item, who owns it, the failure that drops it to 50%, and how to prove it in the demo, checked against the current code. Use when planning or finishing a feature, preparing for the demo, or when asked whether something meets the rubric.
argument-hint: "[rubric item, for example 2.1.1]"
allowed-tools: Read Grep Glob Bash(git status *) Bash(git branch *)
---

# Rubric check

Rubric item: $ARGUMENTS

1. Find the item in `docs/requirements.md`. If no item was given, infer it from the branch name and changed files, and say which one you chose.
2. Read the owner's brief in `docs/members/` and the contracts the item touches.
3. Look at the code for the item, using the layout in `CLAUDE.md`.

Reply with:
- **Full marks needs**: each criterion marked Met, Partly or Not yet, with the file that shows it
- **50% trap**: the failure the rubric names and whether this code is exposed to it
- **Demo proof**: the exact steps and test data that show it working in under a minute
- **Likely Q&A**: three questions an examiner might ask about it, each with a one-sentence answer the owner should be able to give

Don't edit any files.
