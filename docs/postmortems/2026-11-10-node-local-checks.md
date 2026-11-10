---
title: "Node-local review and checks on node1 — postmortem"
type: postmortem
created: 2026-11-10
period: 2026-11-10 06:05 – 2026-11-10 07:00 (UTC)
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# Node-local review and checks on node1 — postmortem (2026-11-10)

This document covers one Claude session on node1 that reviewed the installed node side and ran node-local checks, and the commits `1c72963`, `64b2d88` and the documentation commits after them on branch `claude/node-allowed-gpus`. It records what went wrong, how it surfaced, what was fixed and whether the fix was confirmed. It does not assign blame. Problems still open are in `docs/HANDOFF.md` §Node state and node-local tests.

## How this was made

1. Sources: the session's own commands and outputs, `rb_node/` at commit `c06162b`, node1's `install.json` and node audit log, the research tree's queue runner script.
2. Who read what: the main thread only; no subagents.
3. Audit: none yet.
4. Gaps in the record: the hub was not reachable from the session, so nothing here was checked over SSH. node1's `authorized_keys` and mailbox were not read.

Abbreviations used: PM = postmortem item; DEV = deviation from a user instruction.

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S2 | A bridge job could run on a GPU outside the node owner's set, or on a GPU another queue worker was using | recorded |
| PM-02 | S2 | A by-name job template accepted `.yml` and `.json` configs that the loader cannot find | recorded |
| PM-03 | S2 | With a by-name template, a config named like one of the tree's own configs is ignored without an error | not verified (not fixed) |
| PM-04 | S3 | The install record named a commit that did not contain the installed code; the handoff said nothing was installed | recorded |

No job had been submitted through the bridge before these were found (the node audit log has no `job_submit` entry), so PM-01 to PM-03 did not occur in a real run.

## 2. Items

### PM-01 — A bridge job could run on a GPU outside the node owner's set

- Severity: S2. It is not one of the design §4 anti-goals, but it would have affected other users of the node.
- When: present since the first build (Task 6, `run-job`); found and fixed 2026-11-10.
- What happened: `job_submit` checked the requested GPUs only against the indices `nvidia-smi` reports (0–7 on node1). `run-job` then set `CUDA_VISIBLE_DEVICES` to the requested indices, replacing the value the queue worker had exported. The queue runner itself refuses GPUs outside 4–7 and runs one worker per GPU.
- Cause (inferred): the wrapper was written to narrow what a job sees, without the runner's per-GPU worker model in view; inferred from `docs/manual/node-setup.md` §8 before the fix.
- How it surfaced: code reading during the review, with the queue runner's script open beside it.
- Fix: `allowed_gpus` in `node.json`, checks in `job_submit` and `run-job`, worker's GPU used for one-GPU jobs (commit `1c72963`). Design: `docs/design/2026-11-10-allowed-gpus.md`.
- Fix verified: recorded — unit tests (`tests/test_jobs.py`, eight new cases) and three console runs on node1 with a scratch config (`docs/provisioning.md` §Results). Not verified with a job claimed by the real queue runner.
- Prevention: a node-side change that sets an environment variable or a resource for a job is checked against the node's own runner before it is called complete.
- Evidence: `rb_node/run_job.py` at `c06162b` 「env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpus)」; `docs/server-facts.md` §5 「GPUs outside 4-7 are refused unless `FORCE_GPUS=1` (GPUs 0-3 belong to other users)」

### PM-02 — A by-name job template accepted `.yml` and `.json`

- Severity: S2
- When: introduced 2026-11-10 with the `{config_dir}` / `{config_stem}` placeholders (commit `ca8d376`); found and fixed the same day.
- What happened: `job_submit` accepts `.yaml`, `.yml` and `.json`. With `--config-name {config_stem}`, Hydra finds only `<name>.yaml`. A `.yml` or `.json` config would have been approved, queued, and failed when it started.
- Cause (inferred): the placeholder test checks the substituted string only; no run of the loader was recorded. Inferred from `tests/test_jobs.py::test_template_dir_and_stem_placeholders`.
- How it surfaced: a composition-only run on node1 (`--cfg job`, no training) with five config layouts.
- Fix: a template that uses `{config_stem}` takes `.yaml` only, case-sensitive (commit `64b2d88` and the commit after it).
- Fix verified: recorded — `tests/test_jobs.py::test_by_name_template_takes_yaml_only`.
- Prevention: a new template form is run once against the real loader in composition-only mode before it is set on the node.
- Evidence: session output 「Cannot find primary config 'rbtest'. Check that it's in your config search path.」

### PM-03 — A config named like one of the tree's own configs is ignored

- Severity: S2
- When: same change as PM-02; found 2026-11-10; not fixed.
- What happened: with `--config-dir <dir> --config-name <stem>`, the tree's own config directory is searched first. A submitted file whose name matches a file there is not loaded; the tree's file is, with no error. The job would run the base config under the submitted job's budget.
- Cause (recorded): the composition-only run with a submitted file named like the tree's primary config returned the tree's config without the submitted key.
- How it surfaced: the same run as PM-02.
- Fix: none yet. Proposed: store the uploaded config as `rbjob-<job_id>.yaml`. The user decides (`docs/HANDOFF.md`).
- Fix verified: not verified — no fix.
- Prevention: the manual now tells the submitter to use names the tree does not use (`docs/manual/node-setup.md` §4).
- Evidence: session output for that case: exit code 0, 70 lines, the submitted key absent.

### PM-04 — The install record did not describe the installed code

- Severity: S3
- When: 2026-11-10, install at 05:54:09, commit at 05:54:13 (UTC).
- What happened: `scripts/node-install.sh` was run from a working tree that held an uncommitted change. `install.json` recorded the previous commit with four dirty files, while the installed code already contained the change. `docs/HANDOFF.md` still said nothing had been installed on node1.
- Cause (recorded): `install.json` before the reinstall and the commit time of `ca8d376`.
- How it surfaced: comparing `install.json` with `diff -r` of the installed code against the checkout.
- Fix: reinstalled from a clean commit; `logs/` added to `.gitignore` so the command log does not count as a dirty file; handoff rewritten for the node's state.
- Fix verified: recorded — `install.json` shows `dirty_files: 0` and the installed code equals the checkout.
- Prevention: install on the node only from a clean commit; treat a non-zero `dirty_files` in the install record as a reason to reinstall.
- Evidence: `install.json` before the fix 「"head": "0b16b475…", "branch": "main", "dirty_files": 4」

## 3. Deviations from user instructions

None recorded.

## 4. Prevention rules

- Check a node-side resource setting against the node's own runner before calling it complete. (PM-01)
- Run a new job template once against the real loader in composition-only mode. (PM-02, PM-03)
- Install on the node from a clean commit only. (PM-04)

## 5. Open items

- PM-03 fix (stored config name): `docs/HANDOFF.md` §Node state and node-local tests, item 1.
- A bridge job claimed by the real queue runner, and every hub-side check: same section, item 3.
