# Experiment requests and result records — design

Date: 2026-11-10 · Status: draft · Author: session research-bridge-f6 (2026-11-10) · Code: none in this branch (design only; later work touches `rb_node/config.py`, `rb_node/jobs.py`, `rb_node/run_job.py`, `rb_node/remote.py`, `rb_node/local.py`, `rb_node/configure.py`, `rb_host/jobs.py`, `rb_host/server.py`, `rb_host/store.py`, `rb_host/sync.py`, `rb_host/web.py`, `rb_host/cli.py`, `rb_host/doctor.py`, and with the user's go-ahead the vault-side copy `vault-export/dashboard/rb_pending.py`) · Data: node `<mailbox_root>/state/runs/<job_id>/`, `<mailbox_root>/state/requests/<job_id>.json`; hub `ledger.jsonl` (new fields and a new record kind), `<data_root>/runs/<node>/<job_id>/`

Status history:
- 2026-11-10 draft
- 2026-11-10 draft revised after an independent audit (findings B1, I1 to I8, M1 to M13 applied or answered)

Abbreviations used below: CLI = command-line interface; HTML = HyperText Markup Language; UTF-8 = the 8-bit Unicode text encoding; UTC = Coordinated Universal Time; KiB / MiB = 1024 / 1024² bytes; sha256 = the SHA-256 hash function (Secure Hash Algorithm, 256-bit output); pid = process id; pgid = process group id; GPU = graphics processing unit; MCP = Model Context Protocol (the ten tools a Claude session calls on the hub); SSH = Secure Shell; JSON = JavaScript Object Notation; JSONL = one JSON object per line; TSV = tab-separated values; YAML = a text configuration format the node cannot parse (standard library only); argv = argument vector, the list of words of a command; uuid = universally unique identifier; MAD = median absolute deviation. "Hub" is the Linux server that holds the ledger and runs the MCP server; "node" is an experiment server (first node: `node1`). "Session" is a Claude session on the hub unless stated otherwise. Line numbers refer to the worktree at `origin/main` = 0b16b47. Paths under `.superpowers/review-2026-11-10/` are working material of this review (gitignored, not in the repository).

## 1. Intent

Today a session can ask for a job (`submit_job`), the user approves it with a passphrase (`rb approve`), the node queues it under a GPU-hour wall limit, and one event comes back saying the job ended. Nothing else comes back. The job path records no metric, no reason for the run, no link to the run it follows, no link to the hypothesis or experiment document it tests, and no output. The hub ledger never learns that the job ended: the `job_finished` event is stored as a message and the job record stays `queued`. A session that wants to decide the next run has to ask a node session in prose and trust the answer.

Repositories in the "autoresearch" style solve the record-keeping half of this problem with a small set of practices: one evaluator the agent cannot change, one numeric metric with a direction, a fixed budget per run, one append-only log line per run with the commit id and a keep / discard / crash status, and a git commit id recorded in each log line, which identifies the code that run used. They solve the other half (who decides that a run happens) by letting an agent loop without asking anyone. research-bridge cannot do that: hard rule 1 puts the user's passphrase between every request and its execution.

This design adapts the record-keeping practices to research-bridge and keeps per-job approval by the user. It is written so that it does not depend on any one research project: everything specific to a project (command, metric, result file, budget cap, check command) is declared on the node by the node owner, in a block called an *experiment family*.

### 1.1 What the current job path does (verified against the code)

| Step | Where | What happens |
|---|---|---|
| Request | `rb_host/server.py:201-207`, `rb_host/jobs.py:72-88` | `submit_job(node, config_path, gpus, gpu_hours, idempotency_key, note)` appends one ledger record `kind=job, op=submit, status=pending_approval` with `config_path`, `config_name`, `config_sha256`, `gpus`, `gpu_hours`, `idempotency_key`, `note`. No SSH call. The record id is `uuid.uuid4().hex` (32 hexadecimal characters) and later becomes the node's `job_id`. |
| Approver view | `rb_host/cli.py:44-79`, `rb_host/jobs.py:124-134` | `rb approve <id>` requires a terminal, prints `describe(rec)` (id, node, config name and path, first 12 characters of the sha256, gpus, gpu_hours, note, all passed through `clean()`), asks y/N, then reads the passphrase with `getpass`. The approver sees a hash of the config, not its content. |
| Approval | `rb_host/jobs.py:169-212` | Re-hashes the config file (`_check_config`, lines 158-166), derives the approval key from `approve_params` and the passphrase, uploads the config as message `job-<id>`, calls node op `job_submit`. Node refusals of the approval reset the record to `pending_approval`; transport failures leave it `approved`; success sets `queued` with the node's result. |
| Node submit | `rb_node/jobs.py:127-167` | Reads the idempotency-key argument (line 129, no lookup), then checks the approval key before any lookup or write (line 131), then the idempotency store, the GPU list, the config extension (`.yaml .yml .json`, line 16), the budget (`0 < gpu_hours <= 168`, lines 17 and 65-76), and that `job_template` is set (line 146). Builds `rb-node run-job --gpus … --gpu-hours … --job-id … -- <job_template with {config} replaced>` (lines 150-152), writes the git state of `trm_root` to `state/git/<job_id>.json` (lines 153-155), and writes the queue file `NNNN_<job_id>.job` atomically (lines 156-164). |
| Run | `rb_node/run_job.py:43-109` | `rb-node run-job` is the *wrapper*: the queue runner starts it, and it starts the job's command. Wall limit = `gpu_hours * 3600 / len(gpus)` (line 51). Writes `state/jobs/<job_id>.json` with `status=running`, `git_start` and `git_submit` (lines 53-65). Sets `CUDA_VISIBLE_DEVICES` to the approved GPUs (line 67). Starts the command without redirecting its output (line 71: `Popen(argv, env=env, start_new_session=posix)`), so output goes wherever the queue runner sends it. Kills the process group on a cancel file or at the deadline (lines 76-95). Status is `done`, `failed`, `budget_exceeded` or `cancelled` (lines 69-97). |
| Report | `rb_node/run_job.py:102-108` | Rewrites `state/jobs/<job_id>.json` with `status`, `exit_code`, `ended`, `seconds`; posts one outbox event `{"event": "job_finished", "job_id", "status"}`, plus `git_head` when the wrapper knows the research root (lines 105-107). |
| Egress masking | `rb_node/remote.py:174-200` | Node op `poll` blanks every body line that matches a withheld pattern. The event is one JSON line, so any hit blanks the whole body, and an event whose body becomes empty is replaced by `{"event": "withheld", "withheld_lines": n}` (lines 184-185): the `job_id` is lost. |
| Hub intake | `rb_host/server.py:95-122`, `rb_host/store.py:87-164` | `store_incoming` blanks hit lines again with the hub's patterns (`store.py:101`), writes `inbox/<node>/<msg_id>/body.txt`, and the ledger gets a `message` record with `msg_kind=event`. No code in `rb_host/` reads `job_finished`; the job record is not updated. |
| Cancel | `rb_node/jobs.py:170-202` | A pending job is removed from the queue and `state/jobs/<id>.json` gets `status=cancelled`; no event is posted. A running job gets a cancel file; `run_job` then posts the event. |
| Git facts | `rb_node/gitinfo.py:1-5, 38-67` | Only branch, head sha, dirty-file count, upstream ahead/behind and a credential-free origin URL; never file names or diffs. `mask_state` replaces branch, upstream and origin with `[withheld]` on a hit. |

Two more facts matter for the design. First, a session on the node can post an event through `serve-local`'s `post_event` tool, which writes `{"event": <kind chosen by the session>, "body": <text>}` (`rb_node/local.py:141-147`); it cannot set top-level `job_id` or `status` fields, but it can choose `kind = "job_finished"`. The same session can also call `reply`, which posts an outbox item of kind `reply` with any body text it chooses (`rb_node/local.py:132-139`), including a line that parses as a well-formed `job_finished` object for a real job id; the item kind (`reply` or `event`, `rb_node/mailbox.py:148-151`) is set by the node code, not by the session, and the hub ledger records it as `msg_kind` (`rb_host/server.py:112-113`). Second, the queue runner on the current test node returns stale `processing/` entries to `jobs/` when it starts (`docs/server-facts.md:33`), so one queue file, and therefore one `job_id`, can run more than once. Because the wrapper starts the main command in its own session (`run_job.py:71`, `start_new_session`), a restarted runner can start a second wrapper while the first wrapper or its command is still alive.

## 2. Goals

- G1. A session can request a run of a node-declared experiment family with a purpose, a document reference and a parent run. The request is a ledger record only; nothing reaches the node until the user approves that one request with the passphrase.
- G2. The approver sees, before typing the passphrase: the family and its declared metric, direction and GPU-hour cap; the purpose; the document reference; the parent run's status, metric and verdict; the config text and its difference from the parent's config; GPUs and GPU hours.
- G3. Every run that starts has a run directory on the node with `run.json` written at start (family, commit, config hash, budget) and rewritten at the end (status, reason, exit code, seconds, metrics), a captured `run.log`, and an optional `result.json`.
- G4. The node, not a session, sets the run status from a fixed vocabulary: `done`, `crash`, `checks_failed`, `budget_exceeded`, `cancelled`.
- G5. The hub ledger record of a job is updated from the node's reports (`job_finished` events, cancel results, a read-only run query) without the user doing anything, and repeated or forged reports do not change it wrongly.
- G6. A verdict (`keep`, `discard`, `inconclusive`) is recorded on the hub, separately from the node status, by a named command; it never causes anything to run.
- G7. A run whose identifying strings match a withheld pattern returns only its status: the node reduces it before it leaves, and the hub reduces it again before it stores or shows it.
- G8. The hub page served by `rb web serve` shows a runs table per family.
- G9. Each family can have a program document (objective, metric, files in scope, off limits, what has been tried) from a template, so that a fresh session can continue the work from it.
- G10. A new hub works with the node installed today and an old hub works with an updated node; every wire change is additive.

## 3. Non-goals

- An unattended run loop. No component of research-bridge starts a run that the user did not approve with the passphrase (see §6.9 and §15 for the batch question).
- Editing the node's research tree: research-bridge does not commit, revert or reset code on the node. Code changes are made by people or node sessions through the existing routes.
- Choosing GPUs or budgets automatically (research-bridge design §3).
- Validating the keys inside a config file on the node. The node is standard library only and cannot parse YAML; config keys allowed to vary are described in the program document, and the approver sees the config text and its difference from the parent.
- Transferring checkpoints, plots or other large artefacts. A project that wants them on the hub writes them under a node read root, where the existing `fetch_file` (50 MB cap, sha256, withheld check) applies.
- Experiment values on the share page (`docs/design/2026-11-06-shared-status-page.md` §3 excludes metrics and verdict words; that stays) or on the laptop board (`docs/design/2026-11-02-unified-board.md` §4 and open question 1: no experiment values or verdict text; that stays). The runs table, which does show metric values and verdicts of non-withheld runs, lives only on the hub page, bound to loopback and reached through an SSH tunnel. Those two designs are not changed by this one.
- Several research trees on one node. That is the project-profile design written in parallel; this design names its one dependency on it in §5.
- A new MCP tool. The ten tools stay.

## 4. Anti-goals (failure even if it works)

- A run starts without the user typing the passphrase for that request, or a request runs a different command than the one the approver was shown. The specific case to prevent: a new hub sends `family` to the installed node, which ignores unknown arguments and runs the global `job_template` instead.
- A session chooses the command, the metric, the metric's direction, the result parser or the check command of a run.
- A metric value, metric name, artefact name, result note or log line of a withheld run (values that originate on the node) reaches the hub ledger, the hub page, an MCP result or a log; or the config text, purpose or ref of a withheld request is shown on the hub page, by `rb runs` or in an MCP result. The request text itself is written on the hub by a session and stays in the ledger record, so that `describe()` can show it to the approver in the terminal; that is the only place it is shown (§7.2).
- A family request is approved from a surface that did not show the approver the family declaration (§6.4).
- A verdict, a metric or a "best so far" marker causes a job to be submitted, approved or cancelled.
- A forged or replayed event changes the ledger record of a job, or a report for job A updates job B.
- A rerun of the same queue file by the runner consumes a second full GPU-hour budget under one approval.
- A job's output fills the node's disk because `run.log` has no cap.
- Withheld content or real experiment values in this document or in the template (`docs/design/README.md` rules).

## 5. Constraints

- `AGENTS.md` hard rules 1 to 9 unchanged. In particular: rule 1 (no approval over MCP; `submit_job` writes a pending record and makes no SSH call; the node accepts `job_submit` only with the approval key; exactly ten MCP tools), rule 2 (hub to node only; the node never pushes), rule 3 (withheld series never leave the node; the hub re-checks), rule 4 (paths from node config only), rule 6 (no message bodies or secrets in audit logs), rule 7 (events carry an `"event"` key).
- Coordinator contract `.superpowers/review-2026-11-10/design/contract.md` §0: every wire change is additive; the installed node answers `hello` with `node`, `version`, `withheld_extra` only, returns `unknown_op` for unknown ops and ignores unknown arguments; node code stays standard library only, Python 3.8 or later. §2 places this design in "design only".
- Contract §1.3 and §1.4 are built in this branch and are assumed here: `rb sync` writes `<data_root>/sync/<node>.json`; `hello` gains `protocol: 2`, `ops` and a `state` object; `rb web serve` serves `/jobs` on port 8767 bound to loopback; tool results may gain fields.
- Node-side approval (`docs/design/2026-11-03-node-side-approval.md`): the approval key is a reusable value derived from the passphrase and is not bound to any argument (`rb_node/approval.py:104-121` compares its hash with the verifier only). The node cannot tell which arguments the user saw. The binding between what the approver was shown and what is sent is therefore the hub's job: `jobs.approve` sends exactly the record fields that `describe()` showed, re-read under the ledger lock (§6.4). This design adds arguments to `job_submit` and adds no other approval path.
- Project profiles (parallel design): when a node serves more than one tree, a family belongs to one profile and its relative paths resolve against that profile's root. Until then, "the research root" below means the current `trm_root` setting.

## 6. Architecture

```
hub (Linux server)                                         node
──────────────────────────────────────────────            ─────────────────────────────────────────
session ─MCP submit_job(family, purpose, ref, parent)─▶ ledger: job record, pending_approval
user ─ rb approve <id> (terminal, y/N, passphrase)
        │ hello (protocol, families) ─────────────────ssh─▶ serve-remote
        │ approve_params, put_file, job_submit(+family…) ─▶ jobs.submit → queue file
        │                                                    queue runner → rb-node run-job
        │                                                        run dir: run.json, run.log,
        │                                                        result.json, check.log
        │                                                        outbox event job_finished
rb sync / MCP poll ── poll, ack ──────────────────────ssh─▶ poll (structured reduction of
        │                                                        job_finished, then line masking)
        │ runs (job_ids, detail) ────────────────────ssh─▶ runs op (read only, reduced)
        ▼
reconcile → ledger job record (run_status, metric, …)
rb verdict <id> keep|discard|inconclusive → ledger verdict record
rb web serve → /runs (read only, loopback, reached by ssh -L)
```

Every connection goes from the hub to the node (hard rule 2). The node never contacts the hub; reports wait in the node outbox or in the run directory until the hub asks.

### 6.1 Practices from autoresearch-style repositories

The survey (`.superpowers/review-2026-11-10/understand/ext-autoresearch.md`, 2026-11-10) read these repositories, to the extent shown. Repositories that appeared only as search results (for example aiming-lab/AutoResearchClaw, Human-Agent-Society/CORAL, evo-hq/evo) were not read and are not cited.

| Repository | Read |
|---|---|
| karpathy/autoresearch, https://github.com/karpathy/autoresearch | `README.md`, `program.md` in full; constants and evaluator signature of `prepare.py` |
| davebcn87/pi-autoresearch, https://github.com/davebcn87/pi-autoresearch | `README.md` lines 1-330 of 401; first 120 lines of `skills/autoresearch-create/SKILL.md` |
| uditgoenka/autoresearch, https://github.com/uditgoenka/autoresearch | `README.md` lines 69-135 and the heading outline only |
| WecoAI/aideml, https://github.com/WecoAI/aideml | first 50 lines of `README.md` |
| hyperspaceai/agi, https://github.com/hyperspaceai/agi | first 90 lines of `README.md` |

| Practice | Source | Decision | Reason |
|---|---|---|---|
| One evaluator the agent cannot change | karpathy `prepare.py` "do not modify"; pi `prompt.md` "Off Limits" | Adapted | The evaluator is part of the project code on the node. A session cannot name a command: the family's `job_template`, `result_command` and `check_command` come from node config only. The family may list `evaluator_paths`; the wrapper records one opaque `evaluator_id` computed from their content at start, so a run made with a changed evaluator is marked as not comparable. |
| One numeric primary metric with a stated direction | all five | Adopted | Declared per family (`metric.name`, `metric.direction` = `min` or `max`). Secondary metrics are allowed but never decide anything. |
| Fixed time budget per run, hard kill | karpathy (5 minutes, kill at 10) | Adapted | The user chooses GPU hours per request, capped by the family's `max_gpu_hours` and the node's 168-hour limit; the wall limit and the 60-second kill grace already exist (`run_job.py:15, 51`). A family may set `exact_gpu_hours` when runs must be comparable by budget. |
| Bounded iterations by default | pi `maxIterations`; uditgoenka "Bounded by default" | Adapted | The bound is stronger here: each run is one approval. Whether one approval may cover a bounded batch is a user decision (§15). |
| Append-only log of runs with commit, metric, status, description | karpathy `results.tsv`; pi `log.jsonl` | Adapted | The hub `ledger.jsonl` is already append-only; the job record gains the run fields and a separate `verdict` record kind holds judgements. The node keeps one directory per run. There is no second log file that would have to be kept consistent with the ledger. |
| Status vocabulary keep / discard / crash (and `checks_failed`) | karpathy; pi | Adapted | Split by who knows: the node sets what happened (`done`, `crash`, `checks_failed`, `budget_exceeded`, `cancelled`); the hub records what it means (`keep`, `discard`, `inconclusive`), because only the hub holds the earlier runs to compare against. |
| Independent correctness check that the metric cannot override | pi `checks.sh`; uditgoenka "Mechanical search signal, independent acceptance" | Adopted | Optional `check_command` per family; its failure gives `checks_failed` even when the metric improved. |
| A git commit id recorded with each run, identifying the code it used | karpathy; pi | Adopted, with a rule for dirty trees | Commit at submit and at start are recorded (they already are, `jobs.py:153-155`, `run_job.py:55-64`). A run with uncommitted changes or a commit that moved while queued is marked, and a family can refuse such runs (§6.5). |
| Revert discarded changes with `git reset`; dedicated `autoresearch/<tag>` branch | karpathy | Rejected | research-bridge does not edit the node's tree. The verdict is a record, not an action. |
| Agent loop that never stops, permissions disabled | karpathy `program.md` "NEVER STOP" | Rejected | Contradicts hard rule 1: every job needs the user's passphrase. |
| A file that lets a fresh agent resume (objective, metric, files in scope, off limits, what has been tried) | pi `.auto/prompt.md`; karpathy `program.md` | Adapted | One program document per family, template in Appendix A; the "what has been tried" table is generated from the hub runs table. |
| Ideas backlog | pi `ideas.md` | Adapted | A section of the program document, not a separate file. |
| Confidence score = best improvement / MAD of the family's metric values | pi | Adapted | Advisory column on the hub page only; never used as a verdict. |
| Parent link per candidate, drawn as a tree | aideml | Adopted | `parent_run` in the request; the page links to the parent. |
| Hooks that block force-push, `rm -rf`, reading `.env` and SSH keys | uditgoenka | Rejected | Not needed: the bridge key already cannot open a shell (forced command, `restrict`), and the run command is fixed by the node owner. |
| `finalize` of kept experiments into review branches | pi | Rejected | Code is not managed by the bridge (see the `git reset` row). |
| One machine-readable snapshot file for a page | hyperspaceai/agi | Rejected for this design | The share-page snapshot (2026-11-06 design) already plays that role for counts, and metrics must stay off it. |
| Peer-to-peer network | hyperspaceai/agi | Rejected | Contradicts hard rule 2. |

### 6.2 Experiment families (declared on the node)

A family is a kind of experiment with one command shape, one result source and one primary metric. Families are declared by the node owner in `node.json` and edited only on the node console (`rb-node config`), never through a bridge op. The `node.json` key `families` is unrelated to the `families[*].patterns` list inside the withheld pattern file (hard rule 3); the two never share a file. Example with neutral names:

```json
"families": {
  "toy-classifier": {
    "job_template": ["uv", "run", "train.py", "--config", "{config}",
                     "--checkpoint-dir", "outputs/{job_id}", "--result-dir", "{run_dir}"],
    "result_file": "result.json",
    "result_command": [],
    "metric": {"name": "val_error", "direction": "min"},
    "max_gpu_hours": 8,
    "exact_gpu_hours": null,
    "check_command": ["uv", "run", "check.py", "{run_dir}"],
    "post_timeout_s": 300,
    "evaluator_paths": ["eval.py"],
    "require_clean_tree": false,
    "program_doc": "docs/programs/toy-classifier.md",
    "max_log_bytes": 268435456,
    "max_out_bytes": 104857600,
    "egress": "status_only"
  }
}
```

| Field | Required | Meaning and rule |
|---|---|---|
| key (family id) | yes | `^[a-z][a-z0-9_-]{0,31}$`. Must not match a withheld pattern (see the rule for declared strings below the table). |
| `job_template` | yes | argv list. Placeholders `{config}` (stored config path), `{run_dir}` (the job's output directory `state/runs/<job_id>/out/`, §6.5), `{job_id}`; replaced whole-word inside each argv element, never through a shell. Must contain `{config}`. |
| `metric.name`, `metric.direction` | no | Name matches `^[A-Za-z0-9_.\-/]{1,64}$` and must not match a withheld pattern; direction `min` or `max`. A result is expected only when `metric` is declared. A family without `metric` (such as the implicit `default`) reads no result: the main command's exit code gives `done` or `crash`, and a declared `check_command` can still give `checks_failed`. |
| `result_file` | no | Path relative to `{run_dir}` (the `out/` directory) that the job writes. Used only when `metric` is declared and `result_command` is not set; defaults to `result.json` in that case. |
| `result_command` | no | argv run by the wrapper after a successful main command; its standard output lines of the form `METRIC <name>=<number>` (the pi-autoresearch convention) become the wrapper's `result.json`. An absent or empty list (`[]`) means not set. Set either `result_file` or `result_command`, not both; `rb-node config check` fails a family that sets both. |
| `max_gpu_hours` | yes | `0 < value <= 168`. The node refuses a request above it (`over_family_budget`). |
| `exact_gpu_hours` | no | When set, the node refuses any other value (`budget_must_equal`). |
| `check_command` | no | argv run after a successful main command and result. Exit 0 = pass. |
| `post_timeout_s` | no | Timeout for each of `result_command` and `check_command` (default 300, at most 3600). |
| `evaluator_paths` | no | Paths relative to the research root. At start the wrapper computes `evaluator_id`: the first 16 hexadecimal characters of a sha256 over the sorted per-file content hashes. Only `evaluator_id` leaves the node, never the paths or per-file hashes. |
| `require_clean_tree` | no | When true, a run whose tree has uncommitted changes at start ends as `crash` with reason `tree_dirty` before the command starts. |
| `program_doc` | no | Path of the program document relative to the research root; must lie inside the read roots so `read_doc` can return it masked. |
| `max_log_bytes` | no | Cap for `run.log` (default 256 MiB). |
| `max_out_bytes` | no | Cap for the job's `out/` directory (default 100 MiB). The wrapper measures `out/` at the end; above the cap it records `out_over_cap: true` and the size in `run.json`, deletes nothing, and reads no result from `out/` (status `crash`, reason `out_over_cap`). Large outputs such as checkpoints belong under the research tree (as in the example), not in `out/`. |
| `egress` | no | `status_only` (default) or `values`. Set by the node owner. With `status_only` the event carries only the keys sent today (`event`, `job_id`, `status`, and `git_head` when the research root is known) plus `schema`, `run_status`, `reason`, `attempt` and `egress: "status_only"`, for every run of the family, withheld or not: fixed vocabularies, numbers and a commit id, no metric, name, note or log line. The `runs` op answers the same fields except `event`, plus `state`. A withheld run is reduced further (§7.1). The implicit family `default` (the flat `job_template`, no metric) has `egress: "status_only"`, so its event keeps every key sent today and only adds keys. With `values` the event and the `runs` op return the fields shown in §6.7. The node owner sets `values` only for a family whose runs cannot carry a withheld series. My call (user to check): default `status_only`, because withheld detection works on single lines and a withheld series can be identified by parts spread over several config lines (§7.1). |

The existing flat `job_template` stays and is the implicit family `default` with no metric. A family explicitly named `default` in `families` replaces it. A request without `family` uses `default`; if neither exists the node answers `no_job_template` as today. A request whose `family` is not declared (or is not offered, see below) is refused with `unknown_family`, before the queue file is written.

**Declared strings and withheld patterns.** The family id and the metric name (every string that `hello.families` returns) must not match a loaded withheld pattern: `rb-node config check` and `rb-node doctor` report `fail` for such a family. `hello` evaluates the patterns on each call, with the patterns loaded at that moment, and omits a family whose returned strings match, so a pattern added later also hides a family declared earlier; `job_submit` then answers `unknown_family` for it. The hub re-checks the `families` list against its own patterns before it writes `sync/<node>.json` and drops any family that matches (hard rule 3: the hub re-checks everything it stores).

What the hub may know about a family (returned by `hello` on a protocol-2 node that supports families, field `families`): `id`, `metric` (name and direction), `max_gpu_hours`, `exact_gpu_hours`, `egress`, `has_result`, `has_check`, `has_program_doc`. Never argv or paths. `ops` lists `runs` when the node has the op (§6.7).

### 6.3 The request record (hub)

`submit_job` gains four optional arguments; the tool name and its existing arguments are unchanged:

| Argument | Rule | Stored as |
|---|---|---|
| `family` | family id regex; when the cached `sync/<node>.json` lists families, must be one of them, else the call returns `{"error": "unknown_family"}` and writes nothing. When the cache has no family list (old node or no sync yet), the record is written with `capability_unknown: true`. | `family` |
| `purpose` | one line, at most 200 characters after `clean()`; required when `family` is given | `purpose` |
| `ref` | a document id `^[A-Za-z]+-\d+$` or a path of at most 200 characters; optional | `ref` |
| `parent_run` | an existing job record id on the same node; optional. A different family is allowed and shown as such. | `parent_run` |

`ref` is a label. Neither the hub nor the node ever opens it as a path. The node validates `parent_run` as 32 lowercase hexadecimal characters (and with `_check_id`) before it builds any path from it, for example the parent's `state/runs/<parent_run>/run.json` in §7.1; an invalid value is refused with `bad_id` (hard rule 4).

The record keeps all existing fields (`config_path`, `config_name`, `config_sha256`, `gpus`, `gpu_hours`, `idempotency_key`, `note`, `status`, `created`). Two more are computed on the hub at creation: `withheld` (true when `family`, `config_name`, any line of the config file, the whole config text joined with spaces, `purpose` or `ref` matches the hub's patterns, or the parent run is withheld) and `schema: 2`. The idempotency rule is unchanged: the same key returns the earlier record.

The record does not prevent a request for a withheld run: the user may run such experiments. It only decides how the run is shown (§7.2). For a withheld record the `submit_job` result returns only `id`, `status`, `withheld: true` and `capability_unknown`.

My call (user to check), contract conformance: contract §0 allows result fields to be added and behaviour to be refined; it does not name new arguments. Adding these four optional arguments changes an MCP interface, so build step 6 (§9) does not add them until the coordinator or the user confirms. Until then a request cannot name a family, and only the legacy path is built.

### 6.4 What the approver sees

`rb approve` keeps its flow (terminal check, description, y/N, passphrase). `describe()` adds the lines below. Each displayed line passes through `clean()` separately with a limit of 200 characters per line (`clean()` turns newlines into spaces and cuts at 300 characters by default, `rb_host/jobs.py:106-121`, so it is applied per line, not to the whole block); the line caps below still apply:

```
SUBMIT job <id>
  node: node1
  family: toy-classifier   metric: val_error (lower is better)   cap: 8 GPU-hours   check: yes   egress: status_only
          (declaration from sync at <time>; checked again against the node before upload)
  purpose: <one line>
  ref: <document id or path>
  parent: <id>  status <run_status>  metric <value>  verdict <verdict or none>
  config: <name>  sha256 <12 chars>  path <path>
  config text (first 40 lines):
    ...
  difference from parent config (unified, at most 60 lines):
    ...
  gpus: 0,1   gpu_hours: 6   wall limit: 3.0 h (main, result and check commands together)
  note: <note>
```

Rules: the config text is shown only when the file is UTF-8 text under 64 KiB; otherwise "binary or large config, hash only". The difference is computed only when the parent's config file still has the sha256 recorded in the parent's record; otherwise "parent config changed on disk". Values of a withheld parent are not shown (status only). The family line comes from the cached sync file because `describe()` runs before any connection; the approval connection then calls `hello` first (§7.3), writes the live family list into `sync/<node>.json`, and stops if the live declaration differs from what was shown (metric, direction, cap, `exact_gpu_hours` or `egress`; see `shown` below). The next `rb approve` therefore shows the corrected text. The node enforces the cap and `exact_gpu_hours` itself, so a stale cache cannot widen the budget.

**Binding what was shown to what is sent.** `rb approve` passes the family declaration it displayed (the cached `families` entry: id, metric, direction, cap, `exact_gpu_hours`, `egress`) to `jobs.approve` as a new argument `shown`. `jobs.approve` re-reads the record under the ledger lock, compares `shown` with the live `hello.families` entry, stops on any difference, and sends exactly the record fields that `describe()` displayed. When a family record has no cached declaration (no sync yet, or `capability_unknown: true`), `describe()` prints "family declaration not yet known", and `rb approve` does not ask for the passphrase: it connects, calls `hello`, writes the live family list into `sync/<node>.json`, stops, and asks the user to run `rb approve <id>` again, which then shows the declaration. So `rb approve` never calls `jobs.approve` for a family record without a non-empty `shown`.

**The second approval surface.** Hard rule 1 also names the loopback `/rb/approve` form on port 8765 (`vault-export/dashboard/rb_pending.py`). That form renders its own table (`render_pending`, lines 51-75: config name, path, hash, GPUs, GPU hours, note) and calls `jobs.approve` directly (line 98); it never calls `describe()`. My call (user to check), option (a) of the audit: `jobs.approve` refuses a record that carries `family` unless the caller passes `shown`, with the error `family_needs_terminal_approval`. The refusal is made in `jobs.approve` in the repository, so it holds on the 8765 path from the moment step 6 is built, before any vault file changes. The gate is on `family`, not on `schema: 2`: every new record carries `schema: 2`, and plain requests must stay approvable from the 8765 form (contract §0). A later step (§9, step 6b) changes `render_pending` to show "approve in a terminal: `rb approve <id>`" for family records instead of the passphrase field; that edits a vault file and needs the user's go-ahead (`AGENTS.md`, "Ask the user before"). The other option, showing the full `describe()` text on the 8765 form and passing `shown` from it, is not chosen because it puts config text into a browser page and doubles the display code.

### 6.5 The run directory (node)

`run-job` gains `--family NAME` (and reads the stored request fields from `state/requests/<job_id>.json`, written by `jobs.submit`). The run directory is `<mailbox_root>/state/runs/<job_id>/` (the existing `state_dir` of `run_job` is `<mailbox_root>/state`). It is outside the read roots, so nothing in it is reachable by `read_doc` or `fetch_file`; it leaves the node only through `poll` (the event) and the `runs` op, both reduced and masked.

The job is told only about the subdirectory `out/` (`{run_dir}` and `RB_RUN_DIR` both name `state/runs/<job_id>/out/`). The wrapper's files (`run.json`, `run.lock`, `run.log`, the post-command logs and the wrapper's own `result.json` from `result_command`) are in the parent directory, which the job is not told about, so a job that writes a file named `run.json` into its output directory cannot replace the wrapper's record.

| File | Written by | Content |
|---|---|---|
| `run.json` | wrapper, at start, every 60 s (`last_seen`), and at the end (atomic replace) | See below. The status in it can be relied on because the experiment code is not told where it is and does not write it. |
| `run.lock` | wrapper | Lock file for the rerun rule below. |
| `out/` | the job | The job's output directory. Capped by `max_out_bytes` (§6.2). |
| `run.log` | wrapper | Standard output and standard error of the main command, interleaved, up to `max_log_bytes`; `log_truncated: true` in `run.json` after the cap. The wrapper also copies every line to its own standard output, so the queue runner's log keeps receiving the output it gets today. |
| `out/<result_file>` or `result.json` | the job (`result_file`, inside `out/`) or the wrapper (`result_command`, in the parent) | `{"metrics": {"<name>": <number>, …}, "notes": "<text, at most 500 characters>", "artifacts": ["<name>", …]}`. At most 32 metrics, finite numbers only; names as for `metric.name`. |
| `check.log`, `result_command.log` | wrapper | Output of the post commands, capped at 1 MiB each. |

`run.json` fields (schema 1):

- At start: `schema`, `job_id`, `family`, `attempt`, `started`, `last_seen`, `wrapper_pid`, `child_pgid` (once the main command has started), `gpus`, `gpu_hours`, `wall_limit_s`, `runner_gpus` (the `CUDA_VISIBLE_DEVICES` value the wrapper inherited, before it overwrites it), `config_name`, `config_sha256` (recomputed by the wrapper from the stored config), `git_submit`, `git_start` (head, branch, dirty_files), `evaluator_id` (§6.2), `purpose`, `ref`, `parent_run` (copies from the request, for people and node sessions reading the run directory), `status: "running"`.
- At the end, added: `status`, `reason`, `exit_code`, `ended`, `seconds`, `gpu_seconds` (`seconds * len(gpus)`), `metric` (`{"name", "value"}` or null), `result_ok`, `check_exit`, `log_truncated`, `withheld` (§7.1).

The job receives `RB_RUN_DIR` (the `out/` directory), `RB_JOB_ID` and `RB_FAMILY` in its environment in addition to the placeholders.

**Commit rule.** A run is *pinned* when `git_start.dirty_files == 0` and `git_start.head == git_submit.head`. The page marks unpinned runs. A family with `require_clean_tree: true` refuses to start an unpinned-by-dirt run (`crash`, reason `tree_dirty`); a moved head alone is recorded, not refused, because the queue may wait for hours while the tree advances on purpose.

**Rerun rule.** The wrapper opens `run.lock` and takes an exclusive, non-blocking lock on it with `fcntl.flock` (standard library; available on POSIX (Portable Operating System Interface) systems such as the Linux node) before it reads or writes `run.json`, and keeps it for its lifetime. Where `fcntl` is not available, the lock step is skipped and the process-id and `last_seen` tests below remain, as the existing code already guards `start_new_session` with a POSIX check. It passes the locked file descriptor to the main command and the post commands (`Popen(pass_fds=…)`), so the lock stays held while any of them is alive, even after the wrapper itself has died; the lock is released only when every process holding the descriptor has exited. Then it looks for an existing `run.json`:
- lock not obtained, or `run.json` says `running` and either its `wrapper_pid` still exists, its `child_pgid` still exists (`os.killpg(pgid, 0)` succeeds), or `last_seen` is less than two `last_seen` intervals old: an earlier attempt may still be alive. The wrapper does not start the command, appends `rerun_refused_live` to `run.json`'s `attempts` list when it holds the lock (otherwise it changes nothing), posts no event, and exits with code 0. The earlier attempt keeps running and reports as usual. A process id reused by an unrelated process after a reboot makes this test refuse a rerun that would have been allowed; in that case nothing runs, and the user can submit a new request.
- final status present: the wrapper does not start the command, appends a line `rerun_refused` to `run.json`'s `attempts` list, posts no new event, and exits with code 0 so the runner files it as done; the original record stands. One approval gives at most one completed run.
- `running` present, the lock obtained, and none of the liveness tests above holds (the earlier attempt died, for example in a reboot): the new attempt's wall limit is the approved limit minus the time already used (`last_seen - started` of each earlier attempt); if nothing is left the run ends as `budget_exceeded`, reason `budget_used_by_earlier_attempt`. `attempt` is incremented and the earlier attempt's fields move to `attempts`.

### 6.6 Statuses set by the node

| Status | When | `reason` values |
|---|---|---|
| `cancelled` | the cancel file was seen while the main command or a post command ran; or the job was cancelled before it started, in which case no run directory exists and `jobs.cancel` adds `run_status` and `reason` to the `state/jobs/<job_id>.json` record it already writes | `cancel_running`, `cancel_pending` |
| `budget_exceeded` | the deadline passed while the main command ran; or no budget was left for a rerun | `deadline`, `budget_used_by_earlier_attempt` |
| `crash` | the main command could not start, exited non-zero, or exited 0 but the declared result is missing, unparseable, lacks the primary metric or has a non-finite value; or the tree was dirty under `require_clean_tree`; or `result_command` failed or timed out; or `out/` exceeded `max_out_bytes` | `start_failed`, `exit_nonzero`, `no_result`, `bad_result`, `tree_dirty`, `result_command_failed`, `post_deadline`, `out_over_cap` |
| `checks_failed` | main command and result were fine, and `check_command` exited non-zero, timed out, or hit the deadline | `check_nonzero`, `check_timeout`, `post_deadline` |
| `done` | everything above passed | none |

Precedence when several apply: `cancelled`, then `budget_exceeded`, then `crash`, then `checks_failed`, then `done`. Post commands run with the approved GPUs and share the same deadline as the main command, so the GPU hours the user approved bound all GPU use under that approval; each post command also has its own `post_timeout_s`.

**Compatibility of the vocabulary.** The existing `status` field keeps its current values everywhere it exists today (`state/jobs/<job_id>.json` and the event): `done`, `failed`, `budget_exceeded`, `cancelled`. A new field `run_status` carries the vocabulary above, with `reason`. Mapping from `run_status` to `status`: `crash` and `checks_failed` become `failed`; the others keep their name. An old hub or the vault reader that looks at `status` sees what it sees today; `jobs.cancel` keeps reading `status == "running"`. The hub reads `run_status` when present and otherwise maps legacy `failed` to `crash` with reason `unknown`.

### 6.7 What returns to the hub

**The `job_finished` event** (posted by the wrapper, still one JSON line, `"event"` key kept):

```json
{"event": "job_finished", "job_id": "<id>", "status": "done", "git_head": "<sha>",
 "schema": 2, "run_status": "done", "reason": null, "attempt": 1, "family": "toy-classifier",
 "exit_code": 0, "started": "<time>", "ended": "<time>", "runner_gpus": "<value or null>",
 "seconds": 10512.4, "gpu_seconds": 21024.8, "pinned": true,
 "config_sha256": "<64 hex>", "metric": {"name": "val_error", "value": 0.0},
 "evaluator_id": "<16 hex or null>", "withheld": false}
```

The first four keys are the ones sent today (`git_head` only when the wrapper knows the research root). This is the `egress: "values"` form; a family with `egress: "status_only"` and a withheld run send the reduced form of §7.1. Secondary metrics, notes, artefact names and the log tail are not in the event; they come from the `runs` op. The value shown is a placeholder, not a result.

**The `runs` node op** (new, read only, listed in `hello.ops`): arguments `job_ids` (at most 50) or `since` (timestamp), and `detail` (bool), `tail` (0 to 200 lines, default 0). For each id it looks, by exact id (a regular expression on the queue file name, `^\d+_<id>\.job(\..+)?$`, which also matches the runner's `.job.gpu<N>` names in `processing/` (`docs/server-facts.md`), not a glob, as contract §1.4 does for cancel), in all four queue directories (`jobs`, `processing`, `done`, `failed`, `rb_node/remote.py:27`), in `state/runs/<id>/run.json` and in `state/jobs/<id>.json`, and answers `{"job_id", "state"}` with `state` one of: `unknown` (found nowhere); `queued` (queue file in `jobs/`); `starting` (queue file in `processing/`, no `run.json` yet); `running` (with `last_seen`); the final `run_status` from `run.json`; `finished_legacy` (a `state/jobs/<id>.json` with a final legacy `status` but no run directory, for jobs run by older node code, with that `status`); or `filed` (queue file in `done/` or `failed/` with neither record). With `detail`, it also returns the end fields of `run.json` that the event carries (including `started`, `ended`, `runner_gpus`), the secondary metrics, `notes`, `artifacts` and the last `tail` lines of `run.log`. Every text field passes line masking; the run as a whole passes the reduction in §7.1. A withheld run answers `{"job_id", "state", "status", "run_status", "withheld": true}` and nothing else. A run of a `status_only` family that is not withheld answers `{"job_id", "state", "status", "git_head", "schema", "run_status", "reason", "attempt", "egress": "status_only"}` and nothing else, with or without `detail`.

The op does not need a new MCP tool: `rb sync` calls it (§6.8) and stores what it returns on the hub, and the existing tools return the stored data (§6.10).

### 6.8 Reconciliation of the hub ledger

A function `reconcile(node, report)` runs on the hub in four places: after each `job_finished` item stored by `store_incoming` (both from MCP `poll` and from `rb sync`), after an approved cancel returns, after `rb sync` calls the `runs` op, and once over events stored before this code existed (below). It is idempotent.

1. **Accept.** An item is a candidate only when its kind is `event` (ledger `msg_kind == "event"`) with no `reply_to`, and its body parses as one JSON object with `event == "job_finished"`, a top-level `job_id` of 32 lowercase hexadecimal characters, a `status` or `run_status` from the vocabularies above, and no `body` key. The `body` key test rejects events written by a node session through `post_event`, which always have the shape `{"event", "body"}` (`rb_node/local.py:145`). The kind test rejects a `job_finished`-shaped line that a node session sends through `reply` (kind `reply`, set by the node code, `rb_node/local.py:132-139`). A node updated by this design also refuses the reserved kinds `job_finished`, `responder_failed` and `withheld` in `post_event`.
2. **Match.** The ledger must hold a `kind=job, op=submit` record with that id and the same `node`. Otherwise nothing changes, and the sync file counts it in `unmatched_events`.
3. **State check.** The record's `status` must be `queued` or `approved` (the case where the approval's response was lost after the node queued the job: the report proves it was queued, so `status` becomes `queued`). A report for a record in `pending_approval` or `rejected` changes nothing and is counted in `unmatched_events`. The ledger `status` field keeps its existing vocabulary (`pending_approval`, `approved`, `queued`, `rejected`, `cancelled_requested`); the run outcome goes into new fields. Readers that count jobs by `status` (`rb_host/board.py:285-305`, `rb_host/share.py`, `vault-export/session-calendar/bridge_edges.py:74`) therefore see no new value.
4. **Order.** A report without `attempt` (legacy event from the installed node) counts as attempt 1. A report with a lower `attempt` than the one stored changes nothing. A final report replaces a non-final state. Once a final status is recorded for an attempt, it is replaced only by a `runs`-op answer, which is read from the wrapper's own `run.json` and so takes precedence over an event; an event or cancel result with a different final status for the same attempt changes nothing and is counted in `conflicting_reports` in the sync file. The same attempt with the same final status changes nothing. Non-final answers (`queued`, `starting`, `running`, and the derived `stale`) are not written to the ledger, with one exception: a non-final `runs`-op answer for an `approved` record writes `status: "queued"` once (step 3), because that is a status change. The latest non-final answer and its `last_seen` go to `sync/<node>.json` (field `run_states`, keyed by job id) and are shown from there. `Ledger.update` appends a full copy of the record (`rb_host/ledger.py:153-161`), so this keeps a long job from adding a ledger line on every sync pass.
5. **Reduce.** The hub applies §7.2 before writing.
6. **Write.** `ledger.update(id, run_status, reason, attempt, family, git_head, exit_code, started, ended, runner_gpus, seconds, gpu_seconds, pinned, metric, evaluator_id, evaluator_changed, config_match, withheld, reported_at, report_source)` where `config_match` compares the reported `config_sha256` with the request's, `evaluator_changed` is true when `evaluator_id` differs from that of the most recent earlier run of the same family that reported one, and `report_source` is `event`, `cancel_result` or `runs_op`. A report in the `status_only` form (§6.2) or the withheld form (§7.1) writes only the fields it carries (at most `status`, `run_status`, `reason`, `attempt` and the commit id); the other fields stay unset, and the update also writes `details: "none"`, which tells the `runs` step below that no details will come for this job. Details from the `runs` op (secondary metrics, notes, artefact names, log tail) go to `<data_root>/runs/<node>/<job_id>/run.json` and `log_tail.txt`, mode 600, after masking; the ledger line holds no log text and no notes (hard rule 6 applies to audit logs; the ledger keeps the same discipline for free text).

Sources other than events:
- **Cancel of a pending job.** An approved cancel whose node result is `{"cancelled": "pending"}` reconciles the target job directly as `run_status: cancelled`, reason `cancel_pending`, because the node posts no event in that case.
- **The `runs` op.** Each `rb sync` pass asks a node whose `hello.ops` lists `runs` about every job record in `approved` or `queued` without a final `run_status` and older than 10 minutes, and about records with a final `run_status` whose details are not yet stored and that do not carry `details: "none"`. A `finished_legacy` answer is reconciled like a legacy event (`report_source: runs_op`, legacy `failed` read as `crash` with reason `unknown`, `details: "none"`). A `filed` answer (queue file finished, no record on the node) is kept in `run_states` and shown as "filed, no record"; it does not change the ledger. A `running` answer with `last_seen` older than 3 minutes is shown as `stale` (the wrapper is probably dead), derived from `run_states` in the sync file, not written to the ledger; a node answer `unknown` for an `approved` record older than the approval claim time (300 s, `rb_host/jobs.py:21`) is shown as "not on node" and the user may approve again (same idempotency key, so nothing runs twice). Failure rule (contract §1.3: a failed source fails the pass): a `runs` call that fails with a transport error or any error code other than `unknown_op` makes the `rb sync` pass fail, after the poll results of the same pass have been stored and reconciled; `unknown_op` sets `runs_op: false` in the sync file and is not a failure.
- **Events stored before this code.** `job_finished` events stored in `inbox/` by an earlier hub version were never reconciled. The first `rb sync` pass of the new code reads the stored event bodies once (oldest first, through the same steps 1 to 6, which are idempotent) and records `reconciled_stored: true` in the sync file; `rb sync --reconcile-stored` repeats it on request.
- **Old node.** No `runs` op: the hub relies on the event alone. A job record still `queued` after its wall limit plus one hour is shown as "no report" with its age; nothing is changed in the ledger.

### 6.9 Verdicts (hub)

A verdict is a judgement about a finished run: `keep` (the change is worth building on), `discard` (it is not), `inconclusive` (the result does not decide). It is stored as its own ledger record so that its history stays:

```json
{"kind": "verdict", "id": "<uuid hex>", "job_id": "<id>", "node": "node1", "verdict": "keep",
 "note": "<at most 300 characters>", "set_by": "terminal", "created": "<UTC time>"}
```

- Command: `rb verdict <job_id> keep|discard|inconclusive [--note TEXT]`. The latest verdict record for a job wins; `rb verdict <job_id> --clear` appends a record with `verdict: null`.
- Allowed only for job records with `run_status` `done` or `checks_failed`. A `crash`, `budget_exceeded` or `cancelled` run has no metric to judge; the page shows its status in the verdict column.
- `set_by` is `terminal` when `rb verdict` runs with a terminal on standard input and output (the same `_interactive()` test as `rb approve`), otherwise `no_terminal`. The marker is advisory: `_interactive()` only tests `isatty()` (`rb_host/cli.py:15-33`), which a session with shell access can satisfy with a pseudo-terminal, and no passphrase follows. It does not prove that the user set the verdict. A session with shell access can record a verdict, and the page shows the marker as recorded. There is no MCP tool for verdicts (ten tools).
- A note that matches a hub withheld pattern is refused. A verdict on a withheld run is stored but the page shows only that a verdict exists.
- A verdict runs nothing, sends nothing to the node and is never read by `rb approve` or `jobs.approve`.
- The page also shows a *suggestion*: `better`, `worse` or `equal` compared with the best `keep` run of the same family that has the same `evaluator_id` and the same budget. The suggestion is computed, never stored as a verdict.

### 6.10 Where sessions and the user see the records

| Surface | Change |
|---|---|
| MCP `submit_job` | four optional arguments (§6.3); result adds `family`, `withheld`, `capability_unknown` |
| MCP `queue_status(node)` | result adds `runs`: the 50 most recent hub rows for that node (the same fields as the page row in §8.4), read from the ledger, no extra SSH call; and `pending`: that node's `pending_approval` job records (id, family, purpose, gpus, gpu_hours). Withheld records follow §7.2: in `runs` and `pending` they carry id, times, status and `withheld: true` only (no family, purpose or ref) |
| MCP `thread(job_id)` | the job record already matches by id (`ledger.thread`, `rb_host/ledger.py:163-166`); it now carries the run fields; `ledger.thread` also matches records whose `job_id` equals the argument, so verdict records are included; `stored_dir` points to `<data_root>/runs/<node>/<job_id>/` when details exist; a withheld job record is returned reduced (§7.2) |
| MCP `nodes` | per-node `status` object (contract §1.3) adds `families` from the sync file |
| `rb runs [--node N] [--family F] [--json] [--format md]` | the runs table in the terminal; `--format md` prints the "what has been tried" table for a program document |
| `rb verdict` | §6.9 |
| `rb web serve` | new route `/runs` and `/runs/<family>`, and the job page links each finished job to its row (§8.4) |

### 6.11 Interfaces

| Name | Kind (read / mutation (pending) / internal) | Notes |
|---|---|---|
| MCP `submit_job` + `family`, `purpose`, `ref`, `parent_run` | mutation (pending) | ledger only; no SSH call; tool set unchanged; waits for confirmation (§6.3, My call) |
| `jobs.approve(…, shown=None)` | internal (approval) | refuses a record with `family` when `shown` is absent (`family_needs_terminal_approval`); compares `shown` with the live declaration (§6.4) |
| 8765 `render_pending` / `handle_post` (vault file) | approval surface | later step 6b, with the user's go-ahead: family records show the `rb approve <id>` command instead of a passphrase field |
| MCP `queue_status`, `thread`, `nodes` | read | added result fields only |
| node op `hello` + `families` | read | additive; old hubs ignore it |
| node op `job_submit` + `family`, `purpose`, `ref`, `parent_run` | mutation (approval key) | additive; the hub sends them only to a node that lists the family in `hello.families` (§7.3, §6.12); an undeclared or hidden family gives `unknown_family`, an invalid `parent_run` gives `bad_id` |
| node op `runs` | read | new op; old nodes answer `unknown_op` |
| `rb-node run-job --family` | internal (queue file) | written by `jobs.submit` |
| serve-local `post_event` | internal | refuses reserved kinds |
| `rb verdict`, `rb runs` | hub CLI | `rb verdict` is not an approval and needs no passphrase |
| `/runs` route | read | GET and HEAD only, loopback, same rules as contract §1.3 |

### 6.12 Compatibility

"Installed node" means the `rb_node` code on node1 today: `hello` returns `node`, `version` (0.1.0), `withheld_extra`; the event is `{"event", "job_id", "status"}`, plus `git_head` when the research root is known; `job_template` is empty, so `job_submit` is refused with `no_job_template` until the node owner sets it.

| Situation | Behaviour |
|---|---|
| New hub, installed node, request without `family` | As today: legacy `job_submit`, legacy event. Reconciliation maps `failed` to `crash` (reason `unknown`), stores no metric, marks the row "legacy". |
| New hub, installed node, request with `family` | Written with `capability_unknown: true`. `rb approve` calls `hello`, sees no `protocol`, refuses locally, uploads nothing; the record stays `pending_approval`. |
| New hub, installed node, `runs` op | Not called: `hello` has no `ops`. If it were called, the node answers `unknown_op`, which the hub treats as "not supported". |
| New hub, installed node, withheld run | The node only line-masks: a hit turns the event into `{"event": "withheld", …}` without `job_id`, so the job stays "no report". The hub's own reduction (§7.2) still covers config text, purpose and ref, which it holds. |
| Old hub, updated node | The old hub sends no `family`: the node uses the flat `job_template` (family `default`). The event keeps every key sent today and gains keys the old hub stores but does not read; `status` keeps its old values. `hello` gains `families` and `ops`, which the old hub ignores. |
| Updated node, `node.json` without `families` | Identical to today's behaviour plus the run directory and the added event keys of the `status_only` form (`schema`, `run_status`, `reason`, `attempt`, `egress`), because the implicit `default` family is `status_only` (§6.2). Every key sent today stays. |
| Node at protocol 2 (contract §1.4, built in this branch) without family support | `hello` has `protocol: 2` but no `families` key. The hub treats a missing `families` key as "families not supported": a request with a family is refused locally as for the installed node (§7.3), and nothing is uploaded. Requests without a family go the legacy way. |
| Node downgraded after families were declared | The old code drops the unknown `families` key on load (`rb_node/config.py:59`) and serves only the flat `job_template`; the hub sees no `families` and refuses family requests again. Queue files written by the new code carry `--family`, and the old `rb-node run-job` parses its options with `argparse` `parse_args` (`rb_node/cli.py:124-128`), so such a job would fail with exit code 2. Before a downgrade the node owner empties the queue of family jobs (§9 step 10 adds this to `docs/manual/node-setup.md`). |
| Node updated while jobs are queued | Queue files written by the old code have no `--family`; the new `run-job` treats a missing `--family` as `default`, and a missing `state/requests/<job_id>.json` as a request with no extra fields. |

## 7. Security

### 7.1 Withheld runs on the node

The *identifying strings* of a run are: the family id, the config file name, every line of the stored config file, `purpose`, `ref`, the branch and upstream names of `git_submit` and `git_start`, every metric name, every artefact name and the result `notes`. The `job_id` is not one of them: it is a hub-generated uuid. A run is *withheld* when any identifying string matches a withheld pattern loaded by the node (the five fallback patterns of hard rule 3 plus the pattern file), when the whole stored config text joined into one line (lines joined with single spaces) matches, or when its parent run is withheld. The joined test is needed because a pattern that requires two parts on one line misses a config that carries those parts on separate lines. It can still miss combinations that no pattern describes; that residual risk is why `egress` defaults to `status_only` (§6.2), so a family returns values only after the node owner has decided its runs cannot carry a withheld series. Before reading the parent's `run.json`, the node validates `parent_run` (§6.3).

- The wrapper evaluates this at the end of the run and writes `withheld` into `run.json`; when true, the event it posts already has the reduced form.
- Node op `poll` evaluates it again at egress, with the patterns loaded now, for every outbox item of kind `event` with no `reply_to` whose body parses as a `job_finished` event (other items, including a `job_finished`-shaped `reply`, get line masking only, and the hub never reconciles from them, §6.8 step 1): it reads `run.json` and the stored config for that `job_id`, and if the run is withheld it replaces the body with `{"event": "job_finished", "job_id", "status", "run_status", "withheld": true}`. Only then does the existing line masking run. This keeps today's property that a pattern added later also covers older items (`remote.py:175-176`). If the reduced body itself matches a pattern, the existing generic replacement `{"event": "withheld", …}` applies.
- The `runs` op applies the same test before answering.
- The same egress pass reduces the event of a family whose current `egress` is `status_only` to the `status_only` form (§6.2), so a setting changed later also covers older items.
- `run.log` lines, `notes` and every other text field of a non-withheld run pass line masking as `read_doc` text does.
- **Fixed words against the loaded patterns.** The pattern sets include a family aimed at verdict and status prose (`docs/design/2026-11-02-unified-board.md:83`), so a pattern could match a word of this design's fixed vocabularies: run statuses, reason codes, verdict words, event key names, `egress` values. If one did, line masking would blank or reduce every event, and rows pasted from `rb runs --format md` into a program document would be blanked by `read_doc`, without any error. `rb-node doctor` and `rb doctor` therefore test every fixed word and key name against the loaded patterns and report `fail`, naming the word (never the pattern), when one matches. The fix is on the code side: that word is replaced by a neutral code in a later release. This document does not quote patterns.

### 7.2 Withheld runs on the hub

The hub repeats the test with its own patterns (`withheld_patterns_file` plus the fallback), using what it holds: the request's family, config name, config file lines and the config text joined into one line (when the file still has the recorded sha256), purpose and ref, plus every string field of the report and the parent's `withheld` flag. If any hits, or the node said `withheld: true`, or the request was created `withheld`:

- `store_incoming` stores the reduced body (`job_id`, `status`, `run_status`, `withheld: true`) instead of line-masking the JSON line, so the hub still learns that the job ended;
- the ledger update writes only `run_status`, `withheld`, `reported_at`, `report_source`, `details: "none"` (and `status: "queued"` when the record was `approved`);
- nothing is written under `<data_root>/runs/<node>/<job_id>/`;
- the page row, `rb runs` and MCP results show the job id, the times and the status only, under a "withheld" group rather than under the family. This includes pending requests: a withheld `pending_approval` record appears in `queue_status.pending`, the `submit_job` result, `thread` and the page's pending list with id, times, status and `withheld: true`, and without family, purpose, ref or config name. Only `describe()` in `rb approve` shows the request text, to the approver in the terminal. My call (user to check): reduce withheld records on every surface rather than narrowing anti-goal 3.

The test is not only made when a report is stored. `Ledger.update` merges fields (`rb_host/ledger.py:153-161`), so a run that becomes withheld later (a pattern added on the hub) would keep its stored `metric` and its files under `runs/<node>/<job_id>/`. The hub therefore re-tests the request strings, the stored report fields and the `runs/` files against its current patterns each time it renders a page row, builds `rb runs` output or builds an MCP result, as contract §1.3 does for message bodies. On a hit the row is shown reduced and no stored value is shown; the stored data is left in place and stops being shown.

### 7.3 Other properties

- **No new approval path.** Requests, verdicts, the `runs` op and reconciliation write the hub ledger or read node state; only `rb approve` (or the loopback form that hard rule 1 already names, which cannot approve a family request, §6.4) sends `job_submit`. The node still checks the approval key before any lookup or write (`rb_node/jobs.py:131`).
- **The old-node hazard.** The installed node ignores unknown arguments, so `job_submit` with `family` would run the flat `job_template`. Rule: on the approval connection the hub calls `hello` before `approve_params`; it sends `family` (or any other new argument) only when `hello.protocol >= 2`, `hello.families` exists, and the family appears in it. Otherwise a request with a family is refused locally with "node code does not support experiment families; update the node" and stays `pending_approval`; nothing is uploaded. A request without a family goes the legacy way.
- **Commands come from node config only** (hard rule 4 and the design's anti-goal). `{config}`, `{run_dir}` and `{job_id}` are the only substitutions; the `job_id` already passes `_check_id`; `parent_run` is validated before any path is built from it, and `ref` is never opened (§6.3); the run directory path is built by the node.
- **Forged reports.** A node session can post events through `post_event`, whose body always has a `body` key, and items through `reply`, whose kind is `reply`; neither passes the accept rule (§6.8 step 1: kind `event`, no `reply_to`, no `body` key). An updated node also refuses the reserved kinds in `post_event`. A process running as the node account can write anything; that stays out of scope, as in the node-side approval design §7.
- **Disk.** `run.log` is capped per family; the job's `out/` directory is measured against `max_out_bytes` at the end (not stopped while it grows; large outputs belong under the research tree); post-command logs at 1 MiB; the hub stores at most 200 tail lines per run.
- **Audit.** The node audit records `op=runs` with the count of ids and the result code; no metric values, names or text. The hub writes no metric values to any audit log.

## 8. Data and ledger

### 8.1 Hub ledger

- `kind=job, op=submit` records gain: `schema`, `family`, `purpose`, `ref`, `parent_run`, `withheld`, `capability_unknown` (at creation); `run_status`, `reason`, `attempt`, `git_head`, `exit_code`, `started`, `ended`, `runner_gpus`, `seconds`, `gpu_seconds`, `pinned`, `metric`, `evaluator_id`, `evaluator_changed`, `config_match`, `reported_at`, `report_source`, `details` (at reconciliation, final reports only; §6.8 steps 4 and 6). The `status` field keeps its existing values; a job "has finished" when `run_status` holds a final value. Records without `schema` are legacy and are read as before.
- New record kind `verdict` (§6.9). Readers that iterate over all records and count `kind == "job"` (board, share builder) skip it because of its kind.
- `ledger.pending_jobs()`, `rb approve`, the board's job counts and the share page are unaffected.

### 8.2 Node files

- `<mailbox_root>/state/requests/<job_id>.json`: `family`, `purpose`, `ref`, `parent_run` as received in `job_submit`, written by `jobs.submit` after the approval check (a refused request still leaves nothing, node-side approval design G2).
- `<mailbox_root>/state/runs/<job_id>/`: §6.5.
- `<mailbox_root>/state/jobs/<job_id>.json`: unchanged fields plus `run_status` and `reason`.

### 8.3 Hub files

- `<data_root>/runs/<node>/<job_id>/run.json` (details from the `runs` op, masked) and `log_tail.txt`.
- `<data_root>/sync/<node>.json` (contract §1.3) adds `families` (the `hello` list after the hub's own pattern check, §6.2), `runs_op` (bool), `unmatched_events` and `conflicting_reports` (counts), `run_states` (latest non-final state and `last_seen` per job id, §6.8 step 4) and `reconciled_stored` (bool, §6.8).

### 8.4 The runs table on the hub page

Route `/runs` lists families (with the program-document marker and run counts); `/runs/<family>` shows one table, newest first. Same rules as contract §1.3: GET and HEAD only, loopback bind, `Host` check, HTML-escaped text, no scripts, no external resources, no approval form, reached from a laptop with `ssh -N -L 8767:127.0.0.1:8767 <HUB_ADDR>`.

| Column | Source |
|---|---|
| job (short id, link to `/thread/<id>`) | ledger |
| created, started, ended | ledger `created`; `started` and `ended` from the final report (event or `runs` op) |
| status | `run_status` and `reason`; `starting`, `running`, `stale`, "filed, no record", "not on node" or "no report" when derived (non-final states from `run_states` in the sync file) |
| verdict | latest verdict record, with `set_by`; or the status word for runs that cannot have one |
| metric | value with an arrow for the direction; marker on the best `keep` run so far |
| suggestion | `better` / `worse` / `equal` against the best `keep` run with the same `evaluator_id` and budget |
| confidence | (best improvement) / MAD of the family's `done` metric values with the same `evaluator_id`, where best improvement = the best `keep` value minus the family baseline value (the run named as baseline in the program document, else the oldest `done` run with that `evaluator_id`), signed so that an improvement in the declared direction is positive; shown only with 5 or more runs; advisory |
| parent | link to the parent row |
| ref, purpose | request |
| GPUs, GPU hours used / approved | report (`gpu_seconds / 3600`) and request; marker when `runner_gpus` from the report is set and differs from the approved GPUs |
| commit | first 8 characters of the reported `git_head` (the head at start, `git_start.head`); markers for unpinned and for `config_match: false` |
| evaluator | marker when `evaluator_changed` |

Withheld rows appear only in a separate "withheld" group with job id, times and status. Pending requests for the family appear above the table with the exact `rb approve <id>` command (the page itself approves nothing); withheld pending requests appear only in the "withheld" group, reduced (§7.2). Rows of a `status_only` family show job, created, status, verdict, parent, ref, purpose, approved GPUs and GPU hours, and commit when `git_head` was sent; the started, ended, metric, suggestion, confidence, GPU hours used and evaluator columns are empty. Every row is re-tested against the hub's current patterns at render (§7.2).

## 9. Scope of this phase

This branch writes this document only. Build order for a later branch (each step keeps old hubs and the installed node working):

1. **Node, run directory without families.** `run_job` creates the run directory, writes `run.json` at start and end, tees output to `run.log` with the cap, adds `run_status`, `reason`, `schema`, `attempt`, `exit_code`, `seconds`, `gpu_seconds`, `pinned`, `config_sha256` to `state/jobs/<id>.json`, adds the `status_only` keys (`schema`, `run_status`, `reason`, `attempt`, `egress`) to the event (every job is in the implicit `default` family at this step; the `values` form follows in step 3), keeps `status` and the other keys sent today, implements the rerun rule (lock file passed to the command, liveness tests), gives the job the `out/` subdirectory. Test change: `test_job_finished_event_in_undelivered` (`tests/test_jobs.py:284`) asserts `event`, `job_id` and `status` (plus `git_head` when present) instead of equality of the whole body; `test_run_job_done_and_failed` (line 252) stays as is and gains a `run_status == "crash"` assertion.
2. **Node, withheld reduction.** `run_job` receives the loaded withheld patterns (the CLI passes the node config); `poll` reduces `job_finished` items of kind `event` as in §7.1 (joined config text included); `post_event` refuses reserved kinds; `rb-node doctor` tests the fixed words and key names against the loaded patterns (§7.1).
3. **Node, families.** `families` in `NodeConfig`, `rb-node config check` and `rb-node doctor` checks (template has `{config}`, cap within 168, metric declared with exactly one result source, id and metric name not withheld, `program_doc` inside read roots, `egress` value valid); `hello.families` with the per-call pattern check and `egress`; `job_submit` accepts `family`, `purpose`, `ref`, `parent_run`, refuses an undeclared or hidden family with `unknown_family` and an invalid `parent_run` with `bad_id`, enforces the family cap and `exact_gpu_hours`, writes `state/requests/<job_id>.json`, substitutes the placeholders and passes `--family`; post commands, result parsing, the `out/` cap, the `status_only` reduction and the status precedence in `run_job`.
4. **Node, `runs` op**, listed in `hello.ops`, with exact-id lookup in the four queue directories and the `starting`, `finished_legacy` and `filed` states.
5. **User step:** update the node (`scripts/node-install.sh --update` on the node console) and declare at least one family with `rb-node config`. Until then steps 6 to 9 run against the legacy path only.
6. **Hub, requests and approval.** Starts only after the coordinator or the user confirms the new `submit_job` arguments (§6.3, My call). `submit_job` arguments and validation against the sync file; `withheld` at creation (joined config text included); `describe()` additions (config text, parent difference, per-line `clean()`); `hello` before `approve_params` and the local refusal for families on nodes without `hello.families`; `jobs.approve(…, shown)` with the refusal of family records when `shown` is absent (§6.4); the hub's pattern check of `hello.families` before writing the sync file.
6b. **8765 form (vault file, needs the user's go-ahead).** `vault-export/dashboard/rb_pending.py`: family records show "approve in a terminal: `rb approve <id>`" instead of the passphrase field. Step 6 already makes `handle_post` fail for such records (`family_needs_terminal_approval`); this step only changes what the form shows.
7. **Hub, reconciliation.** `reconcile()` in the poll path and in `rb sync` (accept rule with item kind, ordering and conflict rules of §6.8 step 4, non-final states in the sync file); cancel-result reconciliation; `runs` op calls and their failure rule; the one-time pass over stored events; hub reduction in `store_incoming`; `sync/<node>.json` fields.
8. **Hub, commands.** `rb runs`, `rb verdict`; MCP result fields for `queue_status`, `thread`, `nodes`, each with the render-time withheld re-test of §7.2; `rb doctor` tests the fixed words and key names against the hub patterns.
9. **Hub page.** `/runs` and `/runs/<family>`, with the render-time re-test.
10. **Documents.** Appendix A copied into `docs/projects/TEMPLATE.md` (or a sibling `docs/projects/PROGRAM-TEMPLATE.md`); README section "Experiments" (request, approve, read results, record a verdict); `docs/manual/node-setup.md` section on declaring a family (including `egress`), which also states that the queue must hold no family jobs before a node downgrade (§6.12).

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_host_tools.py::test_submit_job_family_writes_pending_only` (no SSH call made; record fields), `::test_submit_job_unknown_family_writes_nothing` | unit test | not run (design only) |
| G2 | `tests/test_jobs.py::test_describe_shows_family_config_text_and_parent_diff`, `::test_describe_parent_config_changed`, `::test_describe_cleans_per_line`, `::test_approve_stops_on_changed_declaration`, `::test_approve_family_without_shown_refused`; `tests/test_rb_pending.py::test_handle_post_refuses_family_record` (B1: a family record cannot be approved through the 8765 `handle_post`) | unit test | not run (design only) |
| G3 | `tests/test_jobs.py::test_run_job_writes_run_json_start_and_end`, `::test_run_job_tees_output_and_caps_log`, `::test_job_run_json_in_out_dir_does_not_replace_record`, `::test_out_over_cap_is_crash` | unit test | not run (design only) |
| G4 | `tests/test_jobs.py::test_run_status_precedence` (one case per row of §6.6), `::test_result_missing_is_crash`, `::test_check_failure_is_checks_failed`, `::test_post_commands_share_deadline` | unit test | not run (design only) |
| G5 | `tests/test_reconcile.py::test_event_updates_queued_record`, `::test_replayed_event_no_change`, `::test_post_event_shape_rejected`, `::test_event_for_other_node_or_unknown_id_ignored`, `::test_cancel_pending_result_reconciles`, `::test_lower_attempt_ignored`, `::test_reply_shaped_job_finished_ignored`, `::test_missing_attempt_counts_as_one`, `::test_final_status_not_replaced_by_event`, `::test_runs_op_final_wins_over_event`, `::test_running_answer_writes_no_ledger_line`, `::test_runs_error_fails_pass`, `::test_stored_events_reconciled_once`; `tests/test_local.py::test_post_event_refuses_reserved_kinds`; `tests/test_remote.py::test_runs_op_states_exact_id` (all four queue directories, `finished_legacy`) | unit test | not run (design only) |
| G6 | `tests/test_verdict.py::test_verdict_record_appended_not_sent`, `::test_verdict_refused_for_crash`, `::test_set_by_terminal_vs_no_terminal`, `::test_verdict_not_read_by_approve` | unit test | not run (design only) |
| G7 | `tests/test_remote.py::test_poll_reduces_withheld_run_event_to_status`, `::test_pattern_added_later_reduces_old_event`, `::test_runs_op_withheld_status_only`, `::test_split_line_config_reduced` (joined config text), `::test_status_only_family_returns_no_values`, `::test_hello_omits_family_with_withheld_metric_name`; `tests/test_configure.py::test_config_check_fails_withheld_metric_name`; `tests/test_host_store.py::test_hub_reduces_withheld_run_event`, `::test_hub_drops_withheld_family_from_sync_file`; `tests/test_reconcile.py::test_withheld_reconcile_writes_status_only`; `tests/test_host_tools.py::test_rb_runs_withheld_group`, `::test_queue_status_pending_withheld_reduced`, `::test_pattern_added_on_hub_hides_stored_metric`; `tests/test_doctor.py::test_fixed_words_checked_against_patterns` (node and hub) | unit test | not run (design only) |
| G8 | `tests/test_web.py::test_runs_page_rows_and_withheld_group` (escaping, no scripts, Host check) | unit test | not run (design only) |
| G9 | template exists in `docs/projects/`; pass condition: a new session given only a filled program document answers four questions correctly from it: (1) the objective, (2) the primary metric and its direction, (3) which config keys a request may vary, (4) the job ids and statuses of the last five runs | manual | not run (design only) |
| G10 | `tests/test_host_tools.py::test_family_refused_for_node_without_protocol2` (fake old node: nothing uploaded, record stays pending), `::test_legacy_event_reconciles_failed_as_crash`; `tests/test_jobs.py::test_old_hub_submit_uses_default_family` | unit test | not run (design only) |
| Anti-goal: rerun consumes a second budget | `tests/test_jobs.py::test_rerun_after_final_refused`, `::test_rerun_after_crash_gets_remaining_budget`, `::test_rerun_while_first_attempt_alive_refused` (lock held by the live command after the wrapper died) | unit test | not run (design only) |
| Anti-goal: session names a command | `tests/test_jobs.py::test_family_args_cannot_set_template` (unknown family refused with `unknown_family`; extra args ignored), `::test_parent_run_bad_id_refused` | unit test | not run (design only) |
| Compatibility of queue files | `tests/test_jobs.py::test_run_job_without_family_uses_default` (queue file from old code after a node update) | unit test | not run (design only) |
| Live | one approved run of a declared family on node1, one `rb sync` pass, row on `/runs` | live check | not run (needs node update and the user) |

## 11. Decided by the user

- 2026-11-05: the hub is the Linux development server (`docs/manual/hub-setup.md` §12).
- The runtime environment is managed by uv (`AGENTS.md`).
- 2026-11-10, goals of this review: material gathered on the hub; session conversations visible on a hub-served page; SSH transport with automatic update after the first link; experiment handling after autoresearch practice; the project not fixed to trm; flexible MCP synchronisation; scripts simplified so that the README suffices.

## 12. My calls (user to check)

From this design:
- Per-job passphrase approval stays; the unattended loop is rejected; batch approval is left to the user (§15) with "one approval per job" in force.
- Families live in `node.json` and are edited only on the node console; the flat `job_template` becomes the implicit family `default`.
- Family ids must not match a withheld pattern, so withheld series cannot be requested by family name over the bridge (they can still arise from config content or purpose and are then reduced).
- `submit_job` gains four optional arguments instead of encoding them in `note`. The contract allows added result fields and refined behaviour but does not name new arguments, so this is raised with the coordinator; build step 6 waits for confirmation (§6.3).
- A family request can be approved only through `rb approve`, which shows the family declaration; `jobs.approve` refuses a family record when the caller did not pass the declaration it showed, so the 8765 form cannot approve one (§6.4, option (a) of the audit). Changing the 8765 form's display is a vault-file step that needs the user's go-ahead.
- Withheld records are reduced on every surface (page, `rb runs`, every MCP result including the pending list and `thread`); only `describe()` shows their request text, to the approver (§7.2). Anti-goal 3 is worded accordingly.
- Each family has `egress`, set by the node owner, default `status_only`: until the node owner sets `values`, no metric, name, note or log line of that family leaves the node (§6.2, §7.1).
- A rerun starts only when the earlier attempt is shown to be gone: the wrapper's lock is free (the lock descriptor is also held by the command), the recorded wrapper pid and command process group no longer exist, and `last_seen` is at least two intervals old (§6.5).
- The job writes into `out/` inside the run directory; the wrapper's files are in the parent, which the job is not told about; `out/` is measured against `max_out_bytes` at the end (§6.5).
- A final status, once recorded, is replaced only by a `runs`-op answer; non-final states go to the sync file, not the ledger (§6.8 step 4).
- The legacy `status` field keeps its values; the new vocabulary goes into a new `run_status` field (additive), with `crash` and `checks_failed` mapped to legacy `failed`.
- A missing or invalid declared result is `crash`, not `done` with no metric.
- Post commands (`result_command`, `check_command`) use the approved GPUs and share the main deadline, so the approved GPU hours bound all GPU use.
- One approval gives at most one completed run; a rerun after a dead wrapper gets only the remaining budget.
- `run.log` duplicates the output to the queue runner's log instead of replacing it; cap 256 MiB by default.
- The run directory is under `<mailbox_root>/state/runs/`, outside the read roots; results leave only through the reduced event and the `runs` op.
- The "run name" for masking is the set of identifying strings in §7.1, including every config line and the parent's withheld flag.
- The hub stores run details in `<data_root>/runs/`, not in the ledger line; the ledger stays the single run log (no separate `runs.jsonl`).
- The ledger `status` field keeps its existing values; the outcome goes into `run_status` and related fields, so the board, the share builder and the vault reader see no new status value.
- The hub page shows metric values and verdict words of non-withheld runs. This departs from the "no experiment values, no verdict text" default of the laptop board (2026-11-02, §4 and open question 1) and the share page (2026-11-06, §3). Those two surfaces stay as they are; the hub page is loopback-only and reached through an SSH tunnel by the user.
- The node's `run.json` keeps per-file evaluator hashes local; only one opaque `evaluator_id` leaves the node.
- Verdicts can be set by anyone who can run `rb verdict` on the hub, recorded as `terminal` or `no_terminal`; the marker is advisory, not proof that the user set it; no MCP tool for verdicts.
- The page's suggestion and confidence columns are advisory and never stored as verdicts.
- Program documents live in the research tree on the node (declared by `program_doc`), read with `read_doc`; the hub generates the "what has been tried" table but does not write into the node's tree.
- `exact_gpu_hours` and `require_clean_tree` are optional per family, off by default.

Carried from the coordinator contract §3 (in force as defaults, not confirmed by the user):
- The hub stores outgoing message bodies under `outbox/` after the withheld check.
- The ten MCP tools stay; flexibility comes from added result fields and the refined `poll`.
- The hub page has no approval form; approval stays `rb approve` in a hub terminal.
- Unattended sync runs as systemd user units installed only when the user runs `rb service install`.
- Windows instructions shrink to an appendix; Windows code paths stay untouched.
- `trm` naming in config keys and on the wire is not renamed now; the profile design proposes aliases.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | (empty until the build) | | |

## 14. Left to the builder

- Exact error codes beyond those named (`unknown_family` on the hub and the node, `over_family_budget`, `budget_must_equal`, `family_needs_terminal_approval`, `bad_id`), CLI flag spelling, the `last_seen` interval (60 s proposed), the stale threshold (3 minutes proposed).
- The per-file hash inside `evaluator_id` (git blob hash of the working file is the obvious choice: it matches git and works for uncommitted edits).
- How `run_job` reads the pipe (a thread per stream, or one merged pipe); lines longer than 64 KiB are split.
- Page layout, sorting controls, and whether `/runs` paginates above 500 rows.

## 15. Open questions

1. **May one approval cover a bounded batch?** Options: (a) one passphrase per job (today); (b) `rb approve id1 id2 …`: each request shown with y/N, the passphrase typed once, the derived key used for each `job_submit` in that one process; (c) a budget envelope (family, number of runs, total GPU hours, expiry) approved once and enforced by the node, which would let a session start runs without a new passphrase and so needs a change to hard rule 1's text. Default if unanswered: (a). I would recommend (b) as the next step, since it keeps a per-job y/N and the typed passphrase; (c) needs its own design.
2. **May sessions record verdicts?** Default: yes, through `rb verdict`, marked `no_terminal` (an advisory marker, §6.9). Alternative: a verdict marked as the user's asks for the approval passphrase, verified locally on the hub.
3. **Should a family's post commands run on the approved GPUs inside the budget (default) or without GPUs outside it?**
4. **GPU slot conflict with a queue runner that assigns its own GPU** (the current test node's runner sets `CUDA_VISIBLE_DEVICES` per worker, and `run_job` overwrites it). This design records `runner_gpus` so a mismatch shows on the page. Should the wrapper instead refuse to start when the runner's GPU is not in the approved list? Default: record only.
5. **Where should program documents live** for a project whose tree is not readable by sessions on the hub? Default: in the research tree, declared by `program_doc`.
6. **May the hub page show metric values and verdict words** of non-withheld runs, given that the laptop board and the share page do not? Default: yes on the loopback hub page only.
7. **Should `require_clean_tree` default to true** for new families, as autoresearch's "every experiment is a commit" suggests? Default: false, because node trees are often edited between runs on purpose.
8. **Which families may use `egress: "values"`?** Default: none until the node owner sets it per family (§6.2).

## Appendix A. Program document template (one per family)

The program document is descriptive. The node never loads configuration from it; the authoritative declaration is the family block in `node.json`. It must not name withheld series or contain withheld results; withheld runs appear only as a count.

```markdown
# Program: <family id>

Updated: YYYY-MM-DD by <session or person>. Node: <node name>. Family declaration last checked: YYYY-MM-DD.

## Objective
<One paragraph: what question the runs of this family answer, and what result would end the program.>

## Metric
- Primary: <name>, <lower | higher> is better. Written by: <job (result_file) | result_command>.
- Secondary (recorded, never decisive): <names>.
- Comparable only when: <same evaluator_id, same budget, same data version, ...>.

## Evaluator (fixed)
- Files: <paths relative to the research root>. Changing them starts a new comparison series; record the date here.
- What it measures and on which data: <text>.

## Budget
- Usual request: <GPUs> GPUs, <hours> GPU hours. Family cap: <max_gpu_hours>. Exact budget required: <yes/no>.

## Files in scope
<What a request may vary: the config keys and their allowed ranges. Code changes needed for a run are made on the node by <who>, committed before the request.>

## Off limits
<Files, keys and data that no request may change: the evaluator, the data split, the result-writing code, ...>

## Checks
<What check_command verifies, and why the metric alone is not enough.>

## Baseline
<Job id of the baseline run and its commit. The value is read from the runs table, not copied here.>

## What has been tried
<Paste of `rb runs --family <id> --format md`: job, parent, purpose, status, verdict, one-line lesson. Withheld runs: count only.>

## Ideas not yet tried
- <idea> — <why it might help> — <cost estimate in GPU hours>

## Open questions
- <question> — <who can answer>
```
