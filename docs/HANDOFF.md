# research-bridge handoff — 2026-11-10

Read `AGENTS.md` first (rules, layout, test commands).

## Node state and node-local tests (2026-11-10, session on node1)

This section is newer than everything below it. Where they disagree (for example "nothing has been installed on node1"), this section wins.

Observed on node1:

- `rb_node` is installed by `scripts/node-install.sh`; `install.json` records commit `64b2d88` on branch `claude/node-allowed-gpus`, clean. The branch is not pushed. After it is merged, reinstall from `main` so the record names a `main` commit.
- `node.json`: `job_template` is the Hydra by-name form (`--config-dir {config_dir} --config-name {config_stem}`), `allowed_gpus` is `[4, 5, 6, 7]`, the read roots exist, `withheld_source` is the JSON pattern file (mode 600), the approval verifier is set. `rb-node config check` reports one item: `harness_root` is empty (decision 4).
- The node audit log has hub ops from 2026-11-06 on (`hello`, `git_status`, `queue_status`, `gpu_status`, `read_doc`). It has no `msg_*`, `respond` or `job_submit` entry: the message and job paths have not run from the hub.
- The research queue is busy: four workers on GPUs 4–7 and about 50 queued jobs. A bridge job gets the highest number plus one, so it starts only after those.

Changed on the branch (344 tests pass):

- `allowed_gpus` (new `node.json` key). Before, `job_submit` accepted every index `nvidia-smi` reports and `run-job` replaced the worker's `CUDA_VISIBLE_DEVICES` with the requested ids, so an approved job could run on another user's GPU (0–3) or on a GPU a second worker was using. Now: empty or malformed `allowed_gpus` refuses `job_submit` (`no_allowed_gpus`); a GPU outside the list or more than one GPU is `invalid`; `run-job` runs a one-GPU job on the worker's GPU (record and event carry `gpus_used`) and starts nothing outside the list (`failed`, reason `gpu_not_allowed`, exit 126).
- A by-name template (`{config_stem}`) takes `.yaml` only.

Design: `docs/design/2026-11-10-allowed-gpus.md`. Postmortem: `docs/postmortems/2026-11-10-node-local-checks.md`.

Node-local test results: `docs/provisioning.md` §Results.

Open after these tests:

1. **Config name collision (user decision).** With the by-name template, a submitted config whose name equals a file in the research tree's own config directory (for example `cfg_pretrain.yaml`) is ignored without an error: Hydra loads the tree's file and the job runs the base config. Proposed fix: store the uploaded config as `rbjob-<job_id>.yaml`, so the name can never collide. Not implemented.
2. **Config content.** A submitted config is the whole primary config. It must start with `defaults: [cfg_pretrain, _self_]` to inherit the base; without it the job gets only the keys in the file. Queue jobs written by hand pass `+project_name` and `+run_name` as overrides; a submitted config has to set them itself.
3. **Hub side, not yet run:** `hello` (expect `withheld_extra > 0`), `send_message` with a small pdf then `poll`, `poll` for the `job_finished` event of job `rbtest-20261110` (posted by the console test, status `budget_exceeded`), `cancel_job` + `rb approve` against a console `rb-node run-job ... -- sleep 600`, and a real `submit_job` once the queue has room.
4. **Multi-GPU jobs** are refused until the queue has a way to give one job several GPUs.
5. The hub does not know `allowed_gpus`: a wrong GPU in `submit_job` is refused only at approval. Showing the list in `gpu_status` is a possible follow-up.
6. Not checked in this session (the user's to check): the options on the two bridge lines in node1's `authorized_keys`, and what `~/.ssh/research-bridge/` on node1 holds (hub private keys do not belong on the node).

## Resume snippet

> research-bridge (`main` at the merge of PR 35) is built and reviewed, and the pre-live-run security fixes from the whole-branch review are merged (PRs 32–35, 2026-11-05). Nothing has been installed on node1 and no SSH key or config has been created. Development continues on another machine (a development server) from 2026-11-05; superseded the same day: that server is now also the **hub** (§Hub moved to the Linux development server). The original plan below kept the laptop as the hub (it runs the 8765 dashboard, holds the SSH keys and `host.json`, and is where `rb approve` is typed). Next: the user decides items 2–4 below and does A1–A3, then the session runs B1 (with the pattern file), B2 (with the two new checks) and B3, and records results.

## Hub moved to the Linux development server (2026-11-05, user decision)

The user decided that the Linux development server is both the hub and the development machine; the laptop no longer takes the hub role. Nothing had been set up on the laptop, so nothing moves. Where this section and older text below disagree (for example "laptop only" rows, `C:/keys/...`, the laptop subnet), this section wins.

- Done on the server (branch `claude/linux-hub`): platform defaults in `rb_host/config.py` (`RB_HOST_ROOT`; Linux default `~/.local/share/research-bridge` instead of a Windows path that Linux reads as relative), `rb config check` reports a missing withheld-pattern file, `rb config mcp` carries `RB_HOST_ROOT` in an `env` block, manual `docs/manual/hub-setup.md` §12. Data root `~/project/research-bridge-hub` (mode 700) with `host.json` for `node1`. 300 tests pass on Python 3.12.
- Reopened: decision 1 (`from=` subnet) is now the server's subnet, recorded in `private/placeholders.md` as `<HUB_SUBNET>`. A1 keys go under `~/.ssh/research-bridge/` on the server; A2 `~/.ssh/config` on the server (none exists yet); `rb approve` is typed in a terminal on the server.
- Not on the server: the vault, so no 8765 dashboard, no `/rb/approve` route, no session-calendar withheld JSON, no `rb board` portfolio/priorities sources. §Before B3 item 3 (PM-03, dashboard deploy) does not block B3 for a Linux hub; it applies only if the laptop dashboard is used later.
- Before any live run: copy the withheld-pattern JSON to `~/project/research-bridge-hub/withheld_patterns.json` (§Before B3 item 1, hub half).

## Shared status page (2026-11-06, development server)

Built on branch `claude/dashboard-planning-proposal-39dfca` (commits e68109a, 218d60a), design `docs/design/2026-11-06-shared-status-page.md` steps 3–4: `rb_host/share.py` builds `share/snapshot.json` and `index.html` from allowlisted fields of the session-calendar files, the run view files, the board cache and the ledger (withheld re-check, atomic writes, one audit line); `rb_host/share_serve.py` serves exactly `/`, `/index.html` and `/snapshot.json` (GET/HEAD, loopback by default, refuses a non-shared tier); 21 tests in `tests/test_share.py`. It was built without the vault, so the input formats are assumed (plan `docs/superpowers/plans/2026-11-06-shared-status-page.md` Global Constraints §A).

Run on the laptop:

    rb config set share.calendar_sessions <path>
    rb config set share.calendar_status <path>
    rb config set share.runs <path>
    # add "labels": [...] to the share block of host.json by hand (no label allowlist: every label shows as "other")
    rb share build
    rb share serve --port <SHARE_PORT>        # default 8766, bind 127.0.0.1; --bind 0.0.0.0 for the LAN

What the user does next:

- (a) Provide masked samples of the session-calendar sessions and status files and of the runs view data, so step 2 can replace the assumed formats.
- (b) Decide issue #39 open questions 2–6 (design §15).
- (c) Step 5: apply the `vault-export/dashboard/` `/share` loopback patch and the link from `/board` (not started).
- (d) Step 6: live check on the laptop and from another device (not started).
- (e) The two parked items (no `Host` header check on `rb share serve`; owner files under `share/owner/`) are the user's call; the defaults stand.

## Working from the development server

Clone or pull `main`; run `uv sync --extra host` as in `AGENTS.md`. What does not carry over from the laptop:

| Item | Where it lives | Note |
|---|---|---|
| Tests | anywhere | The dashboard and bridge-edge tests import the repository's own `vault-export/` copies, and `rb_host` comes from the editable install, so the whole suite runs without the vault. |
| 8765 dashboard, `vault-export/` deployment | laptop only | Apply PR 35's `vault-export/` files there (see §Before B3). |
| `rb approve`, `rb reject` | laptop only | Need a real console and the approval passphrase (`AGENTS.md` rule 1). |
| SSH keys, `~/.ssh/config`, `host.json`, `~/.claude.json` MCP entry | laptop only | Connection direction is laptop to node (rule 2). Do not create keys on the development server. |
| `private/` (real names and addresses) | laptop only, gitignored | The repository is public: placeholders only (`docs/CONTRIBUTING.md`). |

Line endings: copy `rb_node/` to node1 as LF files (`core.autocrlf=input`, or a Linux checkout).

## Before B3 (must do)

Code for PM-01 to PM-12, PM-14 and part of PM-17 is merged; what each fix covers is in `docs/postmortems/2026-11-03-whole-branch-review.md` (Fix verified fields). Four things are not code and are still open:

1. **PM-07, B1:** copy the session-calendar withheld-pattern JSON to `~/.research-bridge/withheld-patterns.json` on node1 and point `withheld_source` at it. Check that `hello` reports `withheld_extra > 0` and that the node audit log has no `withheld_source` warning. Also check the laptop's `withheld_patterns_file` exists; a missing file silently falls back to the five fallback patterns.
2. **PM-02, add to B2:** on node1, run the responder argv (`claude -p ... --tools Read,Grep,Glob --setting-sources ""`) and confirm it exits 0. If node1's Claude CLI rejects `--setting-sources ""`, every responder run ends in `responder_failed` and B3 gets no reply. Then ask the responder to run a shell command and expect a refusal.
3. **PM-03, laptop (user approves):** copy `vault-export/dashboard/rb_pending.py`, `rb_board.py`, the updated `server.py.patch` and `vault-export/session-calendar/bridge_edges.py` to the vault, then restart 8765. Until then the running dashboard has no `Host` check. The new check fails closed: the rb pages return 403 if `server.py` does not pass the `Host` header.
4. **PM-04 residual (accept or design):** a laptop session that can open a pseudo-console and knows the passphrase can still approve.

## Issue tiers (2026-11-05)

Tracking issue: Raon1123/research-bridge#21. MVP = a laptop session sends a message with an attachment to node1 and gets the reply, reads one H/EXP document, and a tiny job runs after `rb approve`; the user sees it on one page.

| Tier | Issues | State |
|---|---|---|
| Done | bridge (Tasks 1–12); 10 whole-branch review; 12 board module + CLI; 13 `/board` page patch; PM-01..12, 14, 17 (page) and SEC-01..04, 07 | Merged. Issues 10, 12 and 13 are still open on GitHub and can be closed. |
| User only, blocks B3 | 2 shared key, 3 `job_template`, 4 harness allowlist, 5 keys + aliases + `authorized_keys`, 6 laptop `uv sync` + `host.json` + `~/.claude.json`, 7 install on node1, 8 security checks + live run, 9 node read roots; 25 decide whether transport authentication comes before or after B3 | Not started. Order: 2–4, 5, 6, 7 (with 9's paths and §Before B3 item 1), 8 (with item 2). |
| User decision | 14 board open questions; PM-18 masking gaps (case variants, text split across lines, zero-width characters) | Defaults are in code. |
| After B3, need a design first | 15 ledger fields, 16 `reply_to` to node, 17 queue numbering lock, PM-13 laptop attachment root, PM-15 per-chunk re-read, PM-16 board fetch path, PM-17 server half (single-threaded approval), PM-19 `mcp` import in the dashboard, responder Read/Grep/Glob not confined to read roots, SEC-05 config loader, SEC-06 `pdftotext` exposure | Start from `docs/design/TEMPLATE.md`. |
| After B3, vault side | 18 bridge edges on the session-browser main screen, 19 `verify.py` baseline | Laptop only. |
| Repository | 11 first-build postmortem, 20 merge settings and old branches | Deferred. |

## Pending decisions (user)

1. ~~Laptop subnet for `from=`~~ — decided: `<LAPTOP_ETH_SUBNET>`.
2. Does the shared key `<SHARED_KEY>` stay in node1's `authorized_keys`? Only the new keys are restricted by `restrict,from=...,command=...`; `<SHARED_KEY>` keeps an unrestricted shell. Plan default: it stays; clean up after the bridge is stable.
3. `job_template` in the node's `node.json`: an argv list with a `{config}` placeholder. It ships empty and `job_submit` refuses (`no_job_template`) until it is set.
4. Harness allowlist: from `60_Tools/sync/prepare_staging.py` (`HARNESS_FILES` = `CLAUDE.md`, `settings.json`, `rtk-reference.md`; `HARNESS_DIRS` = `commands`, `agents`, `hooks`, `workflows`). Confirm or change. `harness_root` is empty by default, so push and pull are refused until set.

## Steps still to do

**User (do not delegate):** A1 keys with passphrase under `C:/keys/research-bridge/` and `ssh-add`; A2 `rb-node1` and `rb-node1-harness` in `~/.ssh/config` (`IdentitiesOnly yes`, `StrictHostKeyChecking yes`); A3 the two `deploy/authorized_keys.example` lines on node1; laptop `uv sync --extra host` and `~/.claude.json` MCP entry; `host.json` (`{"nodes": {"node1": {"alias": "rb-node1", "harness_alias": "rb-node1-harness"}}}`); set the approval verifier on node1 with `rb-node approve-key set` (`docs/design/2026-11-03-node-side-approval.md`).

**Session, after the user confirms each command:** B1 install with §Before B3 item 1; B2 the security checks in `docs/provisioning.md` plus item 2; B3 send a test message with a small pdf, `poll`, `read_doc("node1","H-001")`, submit a job with `gpu_hours=0.01`, `rb approve` on the laptop console, expect `job_finished` with `budget_exceeded` or `done`; then fill the Results section of `docs/provisioning.md` and write a postmortem of the run.

## Notes

- 2026-11-05 fixes were made by four implementer subagents, one per area (node masking, responder, laptop storage, approval), each followed by a task review, fix rounds and a scoped re-review, then one cross-branch review. Rulings made then: `.tex` with a hit is denied by `read_doc` (not masked); the responder prompt drops the work-directory sentence instead of gaining a write tool; an unreadable GPU list gives `gpu_status_unavailable` and an empty one `no_gpus`; an event body masked to nothing becomes `{"event":"withheld","withheld_lines":N}`; `--setting-sources ""` is kept until B2 shows otherwise.
- Known minor gaps left open: an attachment name long enough to exceed the Windows path limit is retried on every poll; the node's `withheld_lines` / `withheld_attachments` counts are not kept in laptop provenance; the audit warning for an unparseable withheld source repeats on every connection.
- Hashes in `docs/history/` predate the 2026-11-02 rewrite of `main` (mapping in `docs/postmortems/2026-10-27-sdd-build.md`).
- The branch `research-bridge/impl` and worktree `D:/raw/Codes/research-bridge-wt` on the laptop are obsolete; remove them when convenient.

## Verification commands

    uv run --extra host pytest -q   # 344 passed on 2026-11-10 (node1, branch claude/node-allowed-gpus)
    curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending      # 200 on the laptop, after PR 35 is deployed
    curl -s -o NUL -w "%{http_code}" -H "Host: evil.example:8765" http://127.0.0.1:8765/rb/pending  # 403 after deployment

Vault-side state checks: `vault-export/CHECKSUMS.txt`.
