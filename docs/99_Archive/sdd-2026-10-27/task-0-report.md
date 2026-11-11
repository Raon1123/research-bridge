# node1 server facts (read-only, collected 2026-10-27)

Server hostname reported by `hostname`: `<NODE_HOSTNAME>`. All values below were read-only.

## 1. Node Python version
Command: `ssh node1 'python3 --version'`
Result: `Python 3.12.3`

## 2. claude CLI
Command: `ssh node1 'which claude'` -> not found (non-login, non-interactive shell PATH lacks it).
Command: `ssh node1 'bash -lc "command -v claude; claude --version"'`
Result: `/home/<NODE_USER>/.local/bin/claude`, version `2.1.311 (Claude Code)`.
Consequence: later tasks must call the absolute path `/home/<NODE_USER>/.local/bin/claude` (or a login shell) over ssh.

## 3. pdftotext
Command: `ssh node1 'which pdftotext'`
Result: `/usr/bin/pdftotext` (available).

## 4. Queue directory and job format
Commands: `mcp__trm-research__queue_status`, `mcp__trm-research__repo_overview`, `ssh node1 'ls /home/<NODE_USER>/project/trm/scripts/queue ...'`, `head -c 600` of one queued `.job`.
- Queue root: `/home/<NODE_USER>/project/trm/scripts/queue/` with subdirs `jobs/`, `processing/`, `done/`, `failed/` (plus `stop` file when draining). Repo root `/home/<NODE_USER>/project/trm`.
- Job file = plain bash script named `NNNN_<run_name>.job` (zero-padded sequence number; FIFO is lexicographic filename order). Content is a `uv run pretrain.py arch=... key=value ...` command with Hydra overrides (`data_paths=`, `seed=`, `+k=`, `+project_name=`, `+run_name=`).
- Claimed jobs in `processing/` are renamed `NNNN_<name>.job.gpu<N>` (suffix = GPU id).
- Observed counts at collection time: jobs 7, processing 4, done 463, failed 10. Stop file absent. Workers: 3 reported by queue_status timing.
- queue_status projects job bodies through an allowlist of Hydra override keys (never raw shell text); each job carries `job_id`, `gpu`, `overrides`, `timing`, `wandb`.

## 5. Runner behaviour
Command: `ssh node1 'cat /home/<NODE_USER>/project/trm/scripts/queue_run.sh'` (217 lines).
- GPU assignment: one worker per GPU; the worker exports `CUDA_VISIBLE_DEVICES=<gpu>` via `env`. Default `GPUS="4 5 6 7"`; GPUs outside 4-7 are refused unless `FORCE_GPUS=1` (GPUs 0-3 belong to other users). The job file itself does not choose the GPU.
- CPU pinning: `taskset` to a 16-core slice of NUMA node1 per GPU (gpu4 -> 64-79 ... gpu7 -> 112-127), with `OMP_NUM_THREADS`/`MKL_NUM_THREADS`=16.
- Claim: atomic `mv` jobs/ -> processing/ as `.job.gpu<N>`; success -> done/, nonzero exit -> failed/. Output appended to `logs/queue/<job>.log`.
- Timeout: none. The runner has no timeout handling. Task 6 keeps the `run-job` wrapper regardless.
- Poll interval `POLL_S` default 10 s. Drain: `touch scripts/queue/stop`. Startup recovers stale processing/ entries back to jobs/.
- Editable while running (add/delete/rename `.job` files in jobs/).
- Subcommands: `status`, `dry-run`.

## 6. Withheld-pattern source
Command: `mcp__trm-research__get_withheld_patterns`
- Server source file: `lab/11_governance/11_lab-root/WITHHELD_RUNS.yaml` (read fresh on each call). Response: `fail_closed=false`, `version` 1, `updated` 2026-10-20.
- Contains per-family `patterns` (Python regexes, IGNORECASE, matched anywhere), `exp_ids`, `exp_id_patterns`, a text `normalization` step (NFKC, dash variants to `-`, zero-width chars dropped, markdown escapes unescaped, line breaks collapsed), and `released_family_ids`. Active family ids: `exp013-seed-ge2`, `exp012-cleanr1`, `verdict-prose`. One match withholds the whole turn.
- Pattern bodies are intentionally not copied here; read the laptop copy below.
- Laptop copy: command `ls -la D:/raw/session-calendar/server/withheld_patterns.json` -> exists, 795 bytes. Its head shows `version` 1, `updated` 2026-10-20, same family ids. Task 8 dependency satisfied.

## 7. Laptop LAN address and subnet
Command: `ipconfig` (Windows, cp949 output decoded).
- Wi-Fi: IPv4 `<LAPTOP_WIFI_IP>`, mask `255.255.255.0` (<LAPTOP_WIFI_SUBNET>).
- Ethernet: IPv4 `<LAPTOP_ETH_IP>`, mask `255.255.254.0` (<LAPTOP_ETH_SUBNET>).
- Virtual (not LAN): vEthernet Default Switch `<VIRTUAL_IF_1>`, vEthernet WSL `<VIRTUAL_IF_2>`.
- Which one reaches node1 was not determined in this task.

## MCP availability
`queue_status`, `get_withheld_patterns`, `repo_overview` were loadable via ToolSearch and used.
