# trm — project sheet

Abbreviations: JSON = JavaScript Object Notation; YAML = a text configuration format; GPU = graphics processing unit; NUMA = non-uniform memory access; CLI = command-line interface; MCP = Model Context Protocol.

Date: 2026-11-10 · Sheet owner: not recorded · Node: `node1` · Profile name: `default` (the node serves one project)

This sheet follows `docs/projects/TEMPLATE.md`. It was moved from `docs/server-facts.md` on 2026-11-10 and filled from that file; its facts were read-only reads of the node on 2026-10-27, when the node was reached through the `trm-research` MCP server and `ssh node1`. Items the 2026-10-27 collection did not record say "not recorded". Values marked "code default" come from `rb_node/config.py` and `rb_node/jobs.py` on `main`, not from the node. Since 2026-11-10 the node runs `rb_node` 0.2.0 (protocol 2) installed from `main`; its `node.json` values are recorded in `docs/HANDOFF.md` (Node state). The bridge design is `docs/superpowers/specs/2026-10-27-research-bridge-design.md`; the hub and node manuals are in `docs/manual/`.

Server hostname reported by `hostname`: `<NODE_HOSTNAME>`.

## 1. Research root

| Item | Value |
|---|---|
| Research root | `/home/<NODE_USER>/project/trm` (the repository root reported by `repo_overview`; also the code default of `trm_root`) |
| Is it a git work tree? | not recorded |
| Who else writes in this tree | the queue runner `scripts/queue_run.sh` (see §5); other live sessions and people: not recorded. GPUs 0-3 of the server belong to other users (§5) |

## 2. Readable directories

Code default `read_roots` (relative to the research root), plus the node's own mailbox `out/` directory. Whether these names match the tree after the server's 2026-10-15 restructuring is not recorded.

| Directory (relative) | What it holds | File types in it |
|---|---|---|
| `lab/registry/` | hypothesis registry | not recorded |
| `lab/experiments/` | experiment documents | not recorded |
| `lab/reports/` | reports | not recorded |
| `reports/figures/` | figures | not recorded |

Other text types the project needs read: not recorded.

## 3. Document kinds

Code defaults of `experiments_dir` and `hypotheses_path`. The identifier forms are fixed in `rb_node/remote.py` (`^EXP-\d+$`, `^H-\d+$`).

| Kind | Identifier form (anchored regular expression) | Lookup rule | Where (relative to the research root) |
|---|---|---|---|
| experiment | `^EXP-\d+$` | one file per identifier, names tried in order: `{id}.md`, `{id}_*.md`; exactly one match | `lab/experiments/` |
| hypothesis | `^H-\d+$` | one heading section per identifier inside one file | `lab/registry/HYPOTHESES.md` |

## 4. Withheld patterns

| Item | Value |
|---|---|
| Pattern file on the node (absolute path, JSON) | `/home/<NODE_USER>/.research-bridge/withheld-patterns.json` (code default of `withheld_source`) |
| Format | the server holds the source as `lab/11_governance/11_lab-root/WITHHELD_RUNS.yaml` (read fresh on each call of the server's `get_withheld_patterns`; `fail_closed` false, `version` 1, `updated` 2026-10-20). It has per-family `patterns` (Python regular expressions, case-insensitive, matched anywhere), `exp_ids`, `exp_id_patterns`, a text `normalization` step (NFKC, dash variants to `-`, zero-width characters dropped, markdown escapes unescaped, line breaks collapsed) and `released_family_ids`. One match withholds the whole turn on the server. The node accepts the JSON export `{"families": [{"patterns": [...]}]}`; `exp_id_patterns` are ignored (AGENTS.md hard rule 3); YAML is not parsed |
| How the file is produced | a JSON export of the server source; the laptop holds a copy (795 bytes at collection, `version` 1, `updated` 2026-10-20, three active families). Export tool: not recorded here. Pattern bodies and family ids are intentionally not copied into this repository |
| Who updates it, and when | not recorded |
| Short inline patterns kept in node.json instead of a file | none (not available before profiles) |
| Copy on the hub | `<data root>/withheld_patterns.json` (code default on a Linux hub) |

Status 2026-11-10 (first live run, `docs/provisioning.md` §Results): the pattern file is loaded on the node and on the hub, 4 patterns on each side besides the five fallback patterns of AGENTS.md hard rule 3. `read_doc`, `send_message` and `poll` ran with it.

The five fallback patterns stay on for this project and cannot be switched off. This is the only project on the node, so the node's pattern file holds this project's patterns only.

## 5. Jobs

| Item | Value |
|---|---|
| Job entry command (`job_template`) | set on the node on 2026-11-10 to the Hydra by-name form (`--config-dir {config_dir} --config-name {config_stem}`, `.yaml` only; `docs/HANDOFF.md`, Node state). A submitted config is the whole primary config: it starts with `defaults: [cfg_pretrain, _self_]` and sets `project_name` and `run_name` itself. The queued jobs seen on 2026-10-27 were `uv run pretrain.py arch=... key=value ...` commands with Hydra overrides (`data_paths=`, `seed=`, `+k=`, `+project_name=`, `+run_name=`) |
| Config file format and extensions accepted | code default `.yaml`, `.yml`, `.json` |
| Queue directory | `/home/<NODE_USER>/project/trm/scripts/queue` (subdirectories `jobs/`, `processing/`, `done/`, `failed/`; a `stop` file when draining) |
| Queue kind | `file-queue`: a job is a plain bash script named `NNNN_<run_name>.job` (zero-padded sequence number; first in, first out is lexicographic file-name order); the runner claims it from `jobs/` by atomic `mv` into `processing/` as `NNNN_<name>.job.gpu<N>` (`<N>` is the GPU id); success moves it to `done/`, a nonzero exit to `failed/` |
| Who runs the queue runner, and how it is started | the script `scripts/queue_run.sh` (217 lines); who starts it and how: not recorded. One worker per GPU (3 workers reported by `queue_status` timing at collection). Subcommands `status` and `dry-run`. Poll interval `POLL_S`, default 10 s. Drain: `touch scripts/queue/stop`. At start it moves stale `processing/` entries back to `jobs/`. Jobs in `jobs/` can be added, deleted or renamed while it runs. It has no timeout; the bridge's `run-job` wrapper is kept regardless |
| Does the runner set `CUDA_VISIBLE_DEVICES` itself? | yes: the worker exports `CUDA_VISIBLE_DEVICES=<gpu>` through `env`; the job file does not choose the GPU. Default `GPUS="4 5 6 7"`; GPUs outside 4-7 are refused unless `FORCE_GPUS=1` (GPUs 0-3 belong to other users). CPU pinning: `taskset` to a 16-core slice of NUMA node1 per GPU (GPU 4 gets cores 64-79 and so on up to GPU 7 with 112-127), with `OMP_NUM_THREADS` and `MKL_NUM_THREADS` set to 16. Whether this and the `run-job` wrapper's own setting can disagree was not tested |
| Largest GPU-hour budget one job may ask for | 168 (the node limit in `rb_node/jobs.py`) |
| Result files a job writes and whether they lie in a readable directory | job output is appended to `logs/queue/<job>.log` under the research root; readable: no (not in the code-default read roots). Other result files: not recorded |

Counts seen on 2026-10-27: 7 jobs queued, 4 processing, 463 done, 10 failed; stop file absent. `queue_status` of the server's own MCP server projects job bodies through an allowlist of Hydra override keys (never raw shell text); each job carries `job_id`, `gpu`, `overrides`, `timing`, `wandb`.

## 6. Responder

| Item | Value |
|---|---|
| Should a message for this project start the server-side Claude session automatically? | yes (the node behaviour is node-wide, AGENTS.md hard rule 8) |
| Working directory of that session | `.` (the research root) |
| Is a live session in this tree linked to the bridge (`rb-node link`)? | not recorded |

## 7. Approval

| Item | Value |
|---|---|
| Who approves jobs for this project | the user (types the approval passphrase in `rb approve` on the hub) |
| Is the approval passphrase shared with other projects on the same node? | yes (one verifier per node). The verifier is set on the node; `rb approve` passed on 2026-11-10 (`docs/provisioning.md` §Results, B3 row 6) |

## 8. Hub display (optional)

| Item | Value |
|---|---|
| Label shown on hub pages | not recorded |
| Board sources (state, events, kanban) | not recorded |
| Stage codes used in event files | not recorded |

## 9. Checks after setup

Not run as a list for this project. The node runs the code of `main` since 2026-11-10; the security checks and the first live run of that day are in `docs/provisioning.md` §Results.

- [ ] `rb-node config check` on the node console prints no `unknown key` line.
- [ ] `rb-node doctor` on the node console reports no `fail` line.
- [ ] `rb doctor --node node1` on the hub reports no `fail` line.
- [ ] A read of one document of each kind in §3 returns text.
- [ ] Masking probe (as in `docs/projects/TEMPLATE.md` §9).

## Appendix: node facts recorded on 2026-10-27

These are facts about the server, not about the project. All were read-only.

| Fact | Command | Result |
|---|---|---|
| Python version | `ssh node1 'python3 --version'` | `Python 3.12.3` |
| `claude` CLI | `ssh node1 'which claude'` found nothing (a non-login, non-interactive shell has no `~/.local/bin` in its path); `ssh node1 'bash -lc "command -v claude; claude --version"'` | `/home/<NODE_USER>/.local/bin/claude`, version `2.1.311 (Claude Code)`. Later tasks must call the absolute path or a login shell |
| `pdftotext` | `ssh node1 'which pdftotext'` | `/usr/bin/pdftotext` (available) |

Queue facts of §5 were read with the server's `queue_status` and `repo_overview` tools, `ls` of the queue directory, `head -c 600` of one queued job and `cat scripts/queue_run.sh`.

Laptop network addresses, recorded in the same collection (Windows `ipconfig`), are obsolete: the hub is a Linux server since 2026-11-05, and which laptop interface reached the node was never determined. The placeholders were `<LAPTOP_WIFI_IP>`, `<LAPTOP_WIFI_SUBNET>`, `<LAPTOP_ETH_IP>`, `<LAPTOP_ETH_SUBNET>`, `<VIRTUAL_IF_1>`, `<VIRTUAL_IF_2>`.

The `trm-research` MCP server (`queue_status`, `get_withheld_patterns`, `repo_overview`) was loadable through tool search and used for the 2026-10-27 collection.
