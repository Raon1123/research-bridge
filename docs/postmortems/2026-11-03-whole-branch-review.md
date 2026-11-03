---
title: "Final whole-branch review (issue 10) — postmortem"
type: postmortem
created: 2026-11-03
period: 2026-10-27 00:00 – 2026-11-03 23:59
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# Final whole-branch review (issue 10) — postmortem (2026-10-27 – 2026-11-03)

This document covers the final whole-branch review requested in GitHub issue 10 (`Raon1123/research-bridge`): every commit from the first-build base `d29aa11` to the tip of `claude/mvp-scope-review-01fb0e` (`7df8fd8`, 25 commits), including the unified board added on 2026-11-03. It records the defects the review found. None of them has been fixed yet. Fixes are tracked in `docs/HANDOFF.md` §Follow-ups. It does not assign blame.

## How this was made

1. Sources: the code at `7df8fd8` (`rb_node/`, `rb_host/`, `vault-export/dashboard/`, `deploy/`), `AGENTS.md` hard rules 1–9, `docs/HANDOFF.md`, the design `docs/superpowers/specs/2026-10-27-research-bridge-design.md`, the board design `docs/design/2026-11-02-unified-board.md`. The live vault dashboard `90_Claude/60_Tools/dashboard/server.py` and its launcher `start_dashboard.vbs` were read only to check how the 8765 server binds and whether it reads the `Host` header. Nothing in the vault was edited.
2. Who read what: one session on Claude Opus 5.5 read all code in the range itself. No subagents were used. A second reviewer model (advisor) read the transcript once before this document was written and proposed checks 5–13 of its list, which were then verified against the code or the local `claude --help` text.
3. Tests: 183 passed (`pytest -q`, 34 s) in a fresh virtual environment on a `git archive` extraction of `7df8fd8` (see DEV-1). Short probe scripts (Python, run on the laptop against the same extraction) confirmed PM-01, PM-05, PM-06 and PM-18. Their outputs are quoted in the items.
4. Audit: none yet.
5. Gaps in the record: nothing was run on node1. Items that depend on node1 state (Claude Code version and settings on node1, files present in the read roots) are marked **inferred**. The `rb_host/harness.py` text transform (vendored portablization) was read only for its transport and staging paths, not line by line.

Checked and found to hold (no item): the Model Context Protocol (MCP) server registers exactly the ten tools and `tests/test_host_tools.py:17` pins that set; `submit_job` and `cancel_job` only append a `pending_approval` ledger record (`rb_host/jobs.py:51-82`); no node module opens a network connection (the laptop starts every SSH (Secure Shell) session); `PathPolicy` rejects absolute paths, NUL bytes and `..`, and compares real paths, so symlinks that leave a root are refused (`rb_node/paths.py:34-42`); uploads are written as `*.part`, size-checked, sha256-checked and renamed only after the check (`rb_node/mailbox.py:128-145`, `rb_host/client.py:158-180`); the node audit log drops `body`, `content` and `data` and the board audit line stores only size and hash; the harness channel stages only and validates every tar member before writing; the board reducers (`reduce_state`, `reduce_events`, `reduce_kanban`, `reduce_queue`) keep only listed fields and drop values that hit a pattern, and `_fetch` deletes the fetched copy (`rb_host/board.py:212`).

Abbreviations used: MCP = Model Context Protocol; SSH = Secure Shell; CSRF = cross-site request forgery; DNS = Domain Name System; SVG = Scalable Vector Graphics; GPU = graphics processing unit; PM-NN and DEV-N as defined in `docs/postmortems/README.md`.

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S1 | Node `poll` returns reply and event bodies without withheld masking; only the laptop masks them | not verified |
| PM-02 | S1 | The responder's tool limit uses `--allowedTools`, which pre-approves tools but does not remove others; node settings still apply | not verified |
| PM-03 | S1 | 8765 approve route checks the client address only; a DNS-rebinding page in the user's browser can read the CSRF token and approve | not verified |
| PM-04 | S1 | A laptop Claude session can approve its own job through `rb approve --yes` or `curl` to 8765 without MCP | not verified |
| PM-05 | S1 | SVG files are checked by name only, on the node and on the laptop | not verified |
| PM-06 | S1 | Node-supplied attachment names like `C:x` escape the laptop data root on Windows | not verified |
| PM-07 | S1 | The shipped node config points the withheld source at a YAML file, so the node masks with the five fallback patterns only | not verified |
| PM-08 | S2 | `read_doc` returns `.tex` files with hit lines blanked; rule 3 and `fetch_file` deny them | not verified |
| PM-09 | S2 | Polled reply bodies are not stored on the laptop; the design says they are | not verified |
| PM-10 | S2 | The laptop download loop has no size cap | not verified |
| PM-11 | S2 | The ledger has no lock; `rb approve` and the 8765 button can approve the same job at once | not verified |
| PM-12 | S2 | GPU index validation is skipped when `nvidia-smi` is missing | not verified |
| PM-13 | S2 | `send_message` uploads any laptop file the caller names | not verified |
| PM-14 | S2 | The responder prompt names a work directory that nothing creates and the responder cannot write | not verified |
| PM-15 | S2 | `get_file` re-reads and re-masks the whole file for every 1 MiB chunk | not verified |
| PM-16 | S2 | Board refresh shares `fetched/<node>/<basename>` with `fetch_file` and reloads `host.json` instead of using its `cfg` | not verified |
| PM-17 | S2 | 8765 approval page omits config path and hash; approval blocks the single-threaded server | not verified |
| PM-18 | S3 | Withheld patterns are case-sensitive | n/a |
| PM-19 | S3 | `/board` needs `mcp` importable in the dashboard Python | n/a |
| PM-20 | S3 | `fetch_file` deletes a failed file instead of moving it to `quarantine/` as `AGENTS.md` states | n/a |

No S0 item: nothing has run on node1, so no anti-goal can have occurred.

## 2. Items

### PM-01 — Node `poll` returns reply and event bodies without withheld masking

- Severity: S1
- When: introduced in Task 4/5 (mailbox, serve-remote); found 2026-11-03 in this review.
- What happened: the server-side responder writes its answer with the `reply` tool; `Mailbox.post_out` stores the body as given, and the `poll` op returns `message.json` as stored. No withheld check runs on the body before it leaves the node. The laptop masks it in `store_incoming`. The `poll` MCP tool docstring says the bodies are already masked. Probe: a reply body containing a fallback pattern came back from `Node.handle({"op": "poll"})` unchanged.
- Cause (inferred, from the code): masking was placed on the document paths (`read_doc`, `get_file`) only; message bodies were assumed to be the responder's own text. The responder can read withheld files directly (PM-02), so its text can carry withheld content. Line blanking on either side also cannot catch a paraphrase or a number quoted without its identifier.
- How it surfaced: this review (code reading, then probe).
- Fix: none in this review. Direction: mask `body` in `post_out` or in `Node.poll` with the node's `Withheld`, report the hit count, and keep the laptop re-check.
- Fix verified: not verified
- Prevention: a node test that posts a reply containing each fallback pattern and asserts `poll` returns it blanked.
- Evidence: `rb_node/remote.py:167-168` 「return {"items": self.mb.undelivered()}」; `rb_host/server.py:125` 「Bodies are already masked.」; probe output 「poll body: result for H108N here」.

### PM-02 — Responder tool limit does not remove tools

- Severity: S1
- When: introduced in Task 6 (spawn); found 2026-11-03.
- What happened: the responder runs `claude -p ... --strict-mcp-config --allowedTools mcp__rb__*,Read,Grep,Glob`. `--allowedTools` is the list of tools allowed without a permission prompt; it does not restrict the available set. The local `claude --help` lists `--tools` for that ("Specify the list of available tools from the built-in set"), and `--setting-sources` for which settings files load. Without them, the node user's `~/.claude/settings.json` and the project `.claude/settings.json` under `trm_root` (the working directory) load, so any `permissions.allow` rule or hook there applies to the responder. `Read`, `Grep` and `Glob` are also not confined to the node read roots, so the responder can read any file the node user can read, including withheld runs.
- Cause (inferred, from the flag text and `spawn.py`): rule 8 was implemented with the pre-approval flag. The node's Claude Code version and settings are not known to this project.
- How it surfaced: this review.
- Fix: none. Direction: add `--tools Read,Grep,Glob` and `--setting-sources ""` (or a controlled `--settings` file with deny rules for withheld paths), keep `--disallowedTools Bash,Write,Edit,WebFetch,WebSearch` as a backstop, and check the result in the B2 security checks on node1.
- Fix verified: not verified
- Prevention: a spawn test that asserts the argv contains `--tools` and `--setting-sources`; a B2 check that asks the responder to run a shell command and expects refusal.
- Evidence: `rb_node/spawn.py:21` 「ALLOWED_TOOLS = "mcp__rb__*,Read,Grep,Glob"」; `rb_node/spawn.py:125` 「"--allowedTools", ALLOWED_TOOLS, "--max-turns", MAX_TURNS,」; `rb_node/spawn.py:128` 「r = subprocess.run(argv, cwd=cfg.trm_root, timeout=RESPONDER_TIMEOUT,」.

### PM-03 — 8765 approve route is open to DNS rebinding

- Severity: S1
- When: introduced in Task 11 (`rb_pending.py`, `server.py.patch`); found 2026-11-03.
- What happened: `/rb/pending` (GET) and `/rb/approve` (POST) accept a request when the client address is `127.0.0.1` and, for POST, when the form carries the per-process CSRF token. The token is printed into the GET page. The vault server listens on `0.0.0.0` and never reads the `Host` header. A web page whose DNS name is re-pointed to `127.0.0.1` (DNS rebinding) is same-origin with the rebound name, so the user's browser can load `/rb/pending`, read the token and POST `/rb/approve`; the server sees a loopback client. This approves any pending job without the user's decision. The new `/board` route has the same check but is read-only.
- Cause (inferred): the loopback check was designed against LAN clients only.
- How it surfaced: this review; the vault `server.py` was grepped for `Host` handling (only `Content-Length` is read from headers).
- Fix: none. Direction: in `handle_get` and `handle_post`, refuse unless `Host` is exactly `127.0.0.1:8765` or `localhost:8765`; for POST also require `Origin` to match when present.
- Fix verified: not verified
- Prevention: a `test_rb_pending.py` case with a foreign `Host` header that expects 403.
- Evidence: `vault-export/dashboard/rb_pending.py:62` 「if client_ip != "127.0.0.1":」; vault `dashboard/server.py:1340` 「ap.add_argument("--host", default="0.0.0.0")」; `start_dashboard.vbs:13` 「server.py --port 8765 --host 0.0.0.0」.

### PM-04 — A laptop Claude session can approve its own job

- Severity: S1
- When: introduced in Tasks 8 and 11; found 2026-11-03.
- What happened: hard rule 1 holds as written: no MCP tool approves. But both approval paths are reachable by the same laptop session that called `submit_job`, if it has a shell: `rb approve <id> --yes` (or `echo y | rb approve <id>`), or two `curl` calls to `127.0.0.1:8765` (GET the page for the token, POST `/rb/approve`). Whether this happens depends only on that session's Claude Code permission settings; this machine runs sessions in auto mode.
- Cause (inferred): the threat model treats "not MCP" as "the user". Nothing ties approval to an action only the user can take.
- How it surfaced: this review.
- Fix: none. Direction: add deny rules for `rb approve`, `rb reject` and `127.0.0.1:8765/rb/` requests to the laptop Claude Code settings; make `rb approve` refuse when standard input is not an interactive terminal and drop `--yes`, or require a code the page shows only to the user.
- Fix verified: not verified
- Prevention: write the rule into `AGENTS.md` hard rule 1 ("approval must need an action the agent cannot take"), and add a test that `rb approve` refuses non-interactive input.
- Evidence: `rb_host/cli.py:114` 「a.add_argument("--yes", action="store_true", help="skip the y/N prompt")」; `vault-export/dashboard/rb_pending.py:36` 「'<input type="hidden" name="csrf" value="%s">'」.

### PM-05 — SVG files are checked by name only

- Severity: S1
- When: introduced in Task 3 (withheld filter); found 2026-11-03.
- What happened: `.svg` is in the name-only set with `.png` and `.jpg`, so `check_file` returns `ok` without reading the content. SVG is XML text and plot labels, legends and titles are stored as text. The node uses `check_file` for `get_file` (documents and reply attachments) and the laptop uses it for the re-check, so an SVG figure whose labels name a withheld run passes both. Probe: an SVG containing a fallback pattern in a `<text>` element returned `ok`.
- Cause (inferred): SVG was grouped with raster images.
- How it surfaced: this review (probe).
- Fix: none. Direction: move `.svg` to the scanned text set (deny on hit).
- Fix verified: not verified
- Prevention: a `test_withheld.py` case with a withheld string inside an SVG `<text>` element.
- Evidence: `rb_node/withheld.py:20` 「_NAME_ONLY_EXT = {".png", ".jpg", ".jpeg", ".svg"}」; probe output 「svg check_file: ok」.

### PM-06 — Node-supplied attachment names escape the laptop data root on Windows

- Severity: S1
- When: introduced in Task 8 (`store.py`); found 2026-11-03.
- What happened: `_safe_name` strips directories but keeps a drive prefix. On Windows, `Path(root) / "C:x"` is the drive-relative path `C:x`, not a child of `root`. `store_incoming` writes the download to `quarantine/<node>/<msg>/.stage/<name>` and then moves it to `inbox/` or `quarantine/`; `fetch_file` writes to `fetched/<node>/<name>`. A reply attachment whose node file name starts with a drive letter and a colon (legal on Linux; `Mailbox.sanitize` keeps it) is written outside the data root, into the current directory of drive C. The message id is checked for slashes only, with the same gap. Probe: `Path("D:/data/inbox") / _safe_name("C:evil.txt")` printed `C:evil.txt`.
- Cause (inferred): the name check was written for POSIX separators.
- How it surfaced: this review (probe).
- Fix: none. Direction: on the laptop, accept only names matching `^[A-Za-z0-9][A-Za-z0-9._ -]*$` (no colon), check `dest.resolve()` is under the intended directory, and apply the same rule to the message id.
- Fix verified: not verified
- Prevention: a `test_host_client.py` case with attachment names `C:x`, `CON`, `a:b` that expects quarantine or rejection, not a write.
- Evidence: `rb_host/store.py:18-19` 「base = str(name).replace("\\", "/").rsplit("/", 1)[-1]」; probe output 「join C: C:evil.txt」.

### PM-07 — The shipped node config gives the node the fallback patterns only

- Severity: S1
- When: introduced in Task 1/3 (config defaults) and Task 13 Step 1 (`deploy/node.json.example`); found 2026-11-03.
- What happened: `withheld_source` points at `WITHHELD_RUNS.yaml`. `Withheld.load` parses JSON only and treats any parse error as "no extra patterns", so the node runs on the five fallback patterns. The family patterns from the session-calendar JSON are applied only on the laptop, after the data has left the node. `AGENTS.md` records that YAML sources are "treated as unparseable (fallback patterns only)", but no step puts the JSON pattern file on node1.
- Cause (recorded): `AGENTS.md` Conventions 「YAML withheld sources are treated as unparseable (fallback patterns only)」.
- How it surfaced: this review.
- Fix: none. Direction: ship the session-calendar pattern JSON to node1 during B1 and point `withheld_source` at it; log a warning in the audit when the source does not parse.
- Fix verified: not verified
- Prevention: a B2 check that reads a document containing a family pattern (not a fallback one) and expects it blanked on the node.
- Evidence: `deploy/node.json.example` 「"withheld_source": "/home/<NODE_USER>/project/trm/lab/11_governance/11_lab-root/WITHHELD_RUNS.yaml"」; `rb_node/withheld.py:60-61` 「except (OSError, ValueError):」 / 「extra = []」.

### PM-08 — `read_doc` masks `.tex` instead of denying it

- Severity: S2
- When: Task 4; found 2026-11-03.
- What happened: hard rule 3 says tex files are denied when they match. `get_file` (and so `fetch_file`) follows that through `check_file`. `read_doc` with a path accepts `.tex`, blanks hit lines and returns the rest. The same file is therefore denied through one tool and returned through the other.
- Cause (inferred): `read_doc` reuses the text mask for every text type it accepts.
- Fix: none. Direction: decide which rule is wanted, then make both paths and `AGENTS.md` agree.
- Fix verified: not verified
- Prevention: a test that reads the same withheld `.tex` through both ops and expects the same outcome.
- Evidence: `rb_node/remote.py:257` 「if p.suffix.lower() not in MASK_EXT | {".tex"}:」.

### PM-09 — Polled reply bodies are not stored on the laptop

- Severity: S2
- When: Task 8; found 2026-11-03.
- What happened: `store_incoming` returns the masked body to the MCP caller and writes only `provenance.json` and attachments. The ledger line has no body and `thread` returns ledger lines only. The item is acked on the node in the same call, so the body exists on the laptop only in the reply to whichever session polled; if that reply is lost (client timeout, crash) it cannot be read again. The design says bodies are stored in `inbox/` files.
- Cause (recorded): design spec line 122 「Bodies stored in `inbox/`/`outbox/` files, not in the ledger line.」; not implemented.
- Fix: none. Direction: write the masked body to `inbox/<node>/<msg_id>/body.txt` before the ack.
- Fix verified: not verified
- Evidence: `rb_host/store.py:80` 「(inbox / "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=2),」.

### PM-10 — The laptop download loop has no size cap

- Severity: S2
- When: Task 8; found 2026-11-03.
- What happened: `NodeClient.get_file` writes chunks until the node says `eof`. The 50 MB limit of hard rule 5 is enforced only by the node. A faulty node can fill the laptop disk.
- Fix: none. Direction: stop and delete the `.part` file once it passes `MAX_FILE`.
- Fix verified: not verified
- Evidence: `rb_host/client.py:166-174` 「res = self.call("get_file", kind=kind, ref=ref, seq=seq)」.

### PM-11 — Ledger has no lock; two approval paths can race

- Severity: S2
- When: Tasks 8 and 11; found 2026-11-03.
- What happened: `Ledger.append` reads every line and then appends, with no file lock. `rb approve` and the 8765 POST both check `status` and then call the node. Two approvals of one job at the same moment both pass the check. A double queue is prevented only by the node: the idempotency key returns the first result, and the config file has already been moved, so a second `job_submit` without a stored key fails with `no_part`. The MCP server, the CLI and the dashboard write the same file.
- Cause (inferred).
- Fix: none. Direction: an exclusive lock file around append/update and around the status check plus `approved` write in `approve`.
- Fix verified: not verified
- Evidence: `rb_host/jobs.py:104-112` 「if rec["status"] not in ("pending_approval", "approved"):」.

### PM-12 — GPU index validation is skipped when `nvidia-smi` is missing

- Severity: S2
- When: Task 5; found 2026-11-03.
- What happened: `job_submit` passes `known or None`; when `nvidia-smi` is absent or fails, `known` is empty and `validate_budget` skips the unknown-index check, so any non-negative index is queued.
- Fix: none. Direction: refuse submission (`gpu_status_unavailable`) when the GPU list cannot be read.
- Fix verified: not verified
- Evidence: `rb_node/remote.py:310-311` 「known = {g["index"] for g in self.gpu_status({}).get("gpus", [])}」 / 「return jobs.submit(self.cfg, self.mb, args, known or None)」.

### PM-13 — `send_message` uploads any laptop file

- Severity: S2
- When: Task 8; found 2026-11-03.
- What happened: attachments are any path the MCP caller names. A laptop session that follows instructions from a message body (or any prompt injection) can send private laptop files, such as SSH keys or `host.json`, to the node without a prompt. The direction is laptop to node, so rules 2 and 3 are not broken, but there is no laptop-side read root.
- Fix: none. Direction: a design proposal for a laptop attachment allowlist (`docs/design/TEMPLATE.md`).
- Fix verified: n/a
- Evidence: `rb_host/server.py:76-79` 「files = [Path(a) for a in attachments]」.

### PM-14 — Responder work directory does not exist and cannot be written

- Severity: S2
- When: Task 6; found 2026-11-03.
- What happened: the prompt tells the responder to "Put any files you want to send under the message work directory". `reply` accepts absolute paths only under `mailbox/out/_work/<msg_id>`, which no code creates, and the responder has no write tool. Reply attachments are therefore limited to files already under a read root.
- Fix: none. Direction: either create the work directory and allow a write tool confined to it, or remove the sentence from the prompt.
- Fix verified: not verified
- Evidence: `rb_node/spawn.py:28-29` 「Put any files you want to send "」 / 「"under the message work directory and list them in reply attachments."」; `rb_node/local.py:89` 「work = self.mb.root / "out" / "_work" / (_check_id(msg_id) if isinstance(msg_id, str) else "_")」.

### PM-15 — `get_file` re-reads the whole file for each chunk

- Severity: S2
- When: Task 4; found 2026-11-03.
- What happened: each `get_file` call reads, masks and hashes the full file, then returns one 1 MiB slice. A 50 MB file takes 50 calls, each reading 50 MB. If the file changes between calls the final hash does not match and the transfer fails on the laptop.
- Fix: none. Direction: build the outgoing bytes once into a node-side spool file per (ref, mtime) and serve slices from it.
- Fix verified: not verified
- Evidence: `rb_node/remote.py:215` 「data = self._bytes_for(p)」.

### PM-16 — Board refresh shares the fetched-file path and reloads `host.json`

- Severity: S2
- When: 2026-11-03 (`0451f4c`, `7df8fd8`); found 2026-11-03.
- What happened: `_fetch` calls `server.fetch_file`, which stores the copy at `fetched/<node>/<basename>`, and then deletes it. A file with the same base name that a session fetched earlier through MCP is overwritten and then deleted. The `server.*` functions also call `load_cfg()` again, so `refresh(cfg, ...)` uses the passed `cfg` for patterns and cache paths but `host.json` (or `RB_HOST_CONFIG`) for nodes and data root. Each source opens its own SSH connection.
- Fix: none. Direction: a board-private fetch helper that takes `cfg` and writes under `board/tmp/`.
- Fix verified: not verified
- Evidence: `rb_host/board.py:207` 「res = server.fetch_file(node, path)」; `rb_host/server.py:158` 「dest = Path(cfg.data_root) / "fetched" / node / _safe_name(path)」.

### PM-17 — 8765 approval page omits path and hash; approval blocks the server

- Severity: S2
- When: Task 11; found 2026-11-03.
- What happened: the page shows `config_name` only; `rb approve` shows `config_path` too. A config named `config.yaml` anywhere on the laptop looks the same on the page. `handle_post` runs the full upload and `job_submit` SSH round trip inside the request handler of the vault's `HTTPServer`, which serves one request at a time, so the whole dashboard waits for it.
- Fix: none. Direction: show `config_path` and the first 12 characters of `config_sha256`; run approval in a worker thread or return 202 and poll.
- Fix verified: not verified
- Evidence: `vault-export/dashboard/rb_pending.py:51` 「% (_e(jid), _e(r.get("node", "")), _e(r.get("config_name", "")), _e(gpus),」; vault `dashboard/server.py:1344` 「server = HTTPServer((args.host, args.port), Handler)」.

### PM-18 — Withheld patterns are case-sensitive

- Severity: S3
- When: Task 3; found 2026-11-03.
- What happened: patterns compile without `re.IGNORECASE`. Probe: lower-case and upper-case variants of two fallback patterns were not masked. Whether such variants occur in node documents is not known.
- Fix: n/a until the user confirms whether identifiers appear in other cases.
- Fix verified: n/a
- Evidence: `rb_node/withheld.py:27` 「out.append(re.compile(p))」; probe output 「case: 0 0」.

### PM-19 — `/board` depends on `mcp` in the dashboard Python

- Severity: S3
- When: `0451f4c`; found 2026-11-03.
- What happened: `rb_board.py` imports `rb_host.board`, which imports `rb_host.server`, which imports `mcp` at module level. The dashboard runs under `C:\Python314\python.exe`; `mcp` is importable there today from the user site-packages, so the page works, but nothing records the dependency. `rb_pending.py` does not need `mcp`.
- Fix: n/a. Direction: import `server` inside `_fetch`, or note the dependency in `vault-export/README.md`.
- Fix verified: n/a
- Evidence: `rb_host/board.py:20` 「from . import server」.

### PM-20 — `fetch_file` deletes failed files instead of quarantining them

- Severity: S3
- When: Task 8; found 2026-11-03.
- What happened: `AGENTS.md` hard rule 3 says the laptop "moves failures to `quarantine/`". `store_incoming` does; `fetch_file` deletes the file. Deleting is the safer outcome; the rule text is what is wrong.
- Fix: n/a. Direction: change the sentence to name both behaviours.
- Fix verified: n/a
- Evidence: `rb_host/server.py:174-176` 「if verdict != "ok":」 / 「dest.unlink()」.

## 3. Deviations from user instructions

### DEV-1 — Tests run outside the worktree

- Instruction: 2026-11-03, the task brief from the session that started this one: 「Create a venv in the worktree」.
- What was done instead: the virtual environment was created in this session's scratch directory, on a `git archive` extraction of `claude/mvp-scope-review-01fb0e` at `7df8fd8`.
- Reason (recorded, from `git log`): this session's branch `claude/exciting-wu-2ca2d8` is at `ce27ef7` (`main`), which does not contain the board commits `0451f4c` and `7df8fd8`; merging that branch here needs the user's approval (`AGENTS.md` §Ask the user before).
- When the user was told: in this session's final report.
- Evidence: `git diff --stat main claude/mvp-scope-review-01fb0e` lists `rb_host/board.py` and `tests/test_board.py` among 14 changed files.

## 4. Prevention rules

- Every byte stream that leaves the node, message bodies included, passes the node's `Withheld` before it is written to stdout. (PM-01, PM-07)
- Tool limits for a spawned Claude session use `--tools` plus `--setting-sources`, never `--allowedTools` alone. (PM-02)
- Loopback HTTP routes that change state check the `Host` header as well as the client address. (PM-03)
- Approval needs an action the laptop agent cannot take by itself. (PM-04)
- Any file type that is text underneath (SVG, JSON lines) is scanned, not name-checked. (PM-05)
- Laptop paths built from node-supplied names are checked with `resolve()` against the intended directory. (PM-06, PM-16)

Copying these into `AGENTS.md` is left to the fix change, so the hard rules and the code change together.

## 5. Open items

- PM-01 to PM-07 (S1): fix before the B3 live run. Tracked in `docs/HANDOFF.md` §Follow-ups (line added with this document).
- PM-08 to PM-17 (S2): tracked in `docs/HANDOFF.md` §Follow-ups as one line pointing here.
- PM-13: a laptop attachment allowlist needs a design (`docs/design/TEMPLATE.md`).
- PM-18: the user confirms whether withheld identifiers can appear in another case.
- Board question 6 (`events.jsonl` refused by the node as unscannable) and the `reduce_state` key allowlist are already in `docs/HANDOFF.md` (MVP scope table) and are not repeated here.
