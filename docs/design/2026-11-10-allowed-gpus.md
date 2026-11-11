# Node GPU allowlist and worker-assigned GPU — design

Date: 2026-11-10 · Status: draft, not user-approved; built: merged from branch `claude/node-allowed-gpus` in PR 47 (merge commit e95be9c) · Author: Claude session on node1 · Code: `rb_node/config.py`, `rb_node/configure.py`, `rb_node/jobs.py`, `rb_node/run_job.py`, `rb_node/cli.py` · Data: `node.json` (`allowed_gpus`), job records under `mailbox/state/jobs/`

Status history:
- 2026-11-10 draft, written after the change was built. The user set the value and gave the go-ahead (§11) but has not read this document.
- 2026-11-11 status set to built (lifecycle in `docs/design/README.md`): merged to `main` on 2026-11-10 in PR 47 (merge commit e95be9c). The design is still not user-approved.

## 1. Intent

node1 is shared. Its queue runner uses GPUs 4–7 with one worker per GPU and refuses other GPUs; GPUs 0–3 belong to other users (`docs/projects/trm.md` §5; before 2026-11-10 `docs/server-facts.md` §5). A job submitted through the bridge did not follow that rule: the node accepted any GPU index that `nvidia-smi` reports, and `run-job` replaced the worker's `CUDA_VISIBLE_DEVICES` with the requested indices. An approved job could therefore run on another user's GPU, or on a GPU that a second worker was already using. Postmortem: `docs/postmortems/2026-11-10-node-local-checks.md` PM-01.

## 2. Goals

- G1. A bridge job is queued only for GPUs the node's owner listed.
- G2. A job claimed by a queue worker runs on that worker's GPU.
- G3. `run-job` starts nothing on a GPU outside the list, whoever calls it.
- G4. A node with no list refuses jobs (fail closed).

## 3. Non-goals

- Jobs that use more than one GPU. They are refused until the queue can give one job several GPUs.
- Showing the list on the hub (`gpu_status`, the pending-jobs page).
- Changing the research tree's queue runner.

## 4. Anti-goals (failure even if it works)

- A bridge job runs on a GPU that is not the node owner's.
- Two jobs share a GPU because of the bridge.
- The hub can set or widen the list (hard rule 4 in spirit: policy comes from node config only).

## 5. Constraints

- `rb_node` stays standard library only, Python 3.8.
- `allowed_gpus` is read from `node.json`; no bridge op writes it.
- The check order of `job_submit` keeps approval first (SEC-01) and the replay lookup second, so a refused call leaves nothing behind.

## 6. Architecture

No new process and no new connection. Two checks on the node:

1. `job_submit` (`rb_node/jobs.py`): after the job template check, an empty or malformed `allowed_gpus` gives `no_allowed_gpus`; a requested GPU outside the list, or more than one GPU, gives `invalid`.
2. `run-job` (`rb_node/run_job.py`, called by the queue job file): if the environment's `CUDA_VISIBLE_DEVICES` is a single index, that is the worker's GPU, and a one-GPU job uses it in place of the requested index. If the GPUs it would use are not all in `allowed_gpus`, it starts nothing and ends the job as `failed` with reason `gpu_not_allowed`, exit code 126.

### 6.1 Interfaces

| Name | Kind (read / mutation (pending) / internal) | Notes |
|---|---|---|
| `node.json` `allowed_gpus` | internal (node console) | List of distinct GPU indices. `rb-node config set allowed_gpus '[4, 5]'`; `rb-node config check` reports an empty list. |
| `job_submit` error `no_allowed_gpus` | mutation (pending) | New error code. `invalid` gains two causes. |
| `job_finished` event | read | New optional fields `gpus_used` (when it differs from the request) and `reason` (when a launch was refused). |

The MCP tool set is unchanged (ten tools).

## 7. Security

The list is node-owned policy. The approval passphrase still gates every submission; this change narrows what an approved submission can do. No key, root, withheld pattern or audit field changes.

Out of scope: a user with a shell on the node can still run anything on any GPU.

## 8. Data and ledger

Job record (`mailbox/state/jobs/<job_id>.json`): `gpus` stays the request; `gpus_used` is added when the job ran elsewhere; `reason` is added on a refused launch. No hub ledger field changes.

## 9. Scope of this phase

1. Config key, `config set` validation, `config check` line.
2. `job_submit` checks.
3. `run-job` worker GPU and launch refusal.
4. Tests, manual (English and Korean), `deploy/node.json.example`.
5. On node1 (done 2026-11-10 with the user's go-ahead): reinstall, `rb-node config set allowed_gpus '[4, 5, 6, 7]'`.

## 10. Verification

| Goal / anti-goal | Check | Kind (unit test / live check / manual) | Status |
|---|---|---|---|
| G1 | `tests/test_jobs.py::test_submit_refuses_gpu_outside_allowed`, `::test_submit_refuses_multi_gpu` | unit test | passed 2026-11-10 |
| G2 | `tests/test_jobs.py::test_run_job_uses_the_workers_gpu`, `::test_cli_run_job_reads_the_workers_gpu`; console run on node1 with a scratch config | unit test, manual | passed; `docs/provisioning.md` §Results |
| G3 | `tests/test_jobs.py::test_run_job_launches_nothing_outside_allowed`; console run on node1 with a scratch config | unit test, manual | passed |
| G4 | `tests/test_jobs.py::test_submit_refused_without_allowed_gpus`, `::test_malformed_allowed_gpus_fails_closed` | unit test | passed |
| G2 with the real queue runner | A bridge job claimed by a `queue_run.sh` worker | live check | not verified: the queue held about 50 jobs, so a new job would not start during the session |

## 11. Decided by the user

- 2026-11-10: `allowed_gpus` on node1 is `[4, 5, 6, 7]`, and the work goes ahead in the proposed order. The proposal named the key, said a one-GPU job uses the worker's GPU, and said multi-GPU jobs are refused until designed.

## 12. My calls (user to check)

- An empty list refuses every job, instead of meaning "no restriction". A node installed before this change must set the key before any job is accepted.
- A malformed list (strings, booleans, negative numbers, not a list) counts as empty.
- `run-job` enforces the list at launch too, including console use, with exit code 126.
- The worker's GPU is read from `CUDA_VISIBLE_DEVICES` only when it is a single index. Anything else (unset, several indices, a UUID) leaves the requested GPUs in place.
- The requested index is kept in `gpus`; the GPU actually used goes in `gpus_used`. The budget is unchanged (`gpu_hours / len(gpus)` of wall time).
- Multi-GPU refusal is unconditional on the node, not a config switch.
- The error message for a GPU outside the list names the list. The hub can already see every GPU through `gpu_status`.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | Empty `allowed_gpus` refuses jobs | A node owner who forgets the key gets `no_allowed_gpus` on every approval until it is set | commit 1c72963 |
| 2 | Worker's GPU wins over the requested index | The user's chosen index is a request, not a guarantee; the record shows the difference | commit 1c72963 |
| 3 | Multi-GPU jobs refused | No multi-GPU job through the bridge until a design exists | commit 1c72963 |

## 14. Left to the builder

Nothing open.

## 15. Open questions

- Should the hub show `allowed_gpus` (in `gpu_status` or on the pending page), so a wrong GPU is caught before approval? Default: not shown; the node refuses at approval.
- Should a one-GPU request carry an index at all, given that the worker decides? Default: keep the index, for nodes without a per-GPU runner.
