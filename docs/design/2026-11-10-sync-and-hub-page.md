# Unattended sync and the hub page — design

Date: 2026-11-10 · Status: draft · Author: session research-bridge-f6 (2026-11-10) · Code: `rb_host/sync.py` (new), `rb_host/threads.py` (new), `rb_host/web.py` (new), `rb_host/server.py`, `rb_host/ledger.py`, `rb_host/store.py`, `rb_host/board.py`, `rb_host/cli.py`, `scripts/demo_dashboard.py`; unit text for `rb service install` (`rb_host/service.py`, built separately) · Data: `<data_root>/sync/<node>.json`, `<data_root>/outbox/<node>/<msg_id>/`, ledger field `delivered`

Status history:
- 2026-11-10 draft
- 2026-11-10 independent audit (accept with fixes) applied: partial fetch keeps items, board and node error codes, unit environment lines, no-path sources, loopback-only bind, at-most-once wording, attachment-name masking, provisional status, stage sweep, upgrade order
- 2026-11-10 coordinator rulings R1 to R9 and R13 (kept in the gitignored review working directory `.superpowers/review-2026-11-10/design/`, which this repository does not contain) applied: git state key `tree` with fallback `trm` (R5), loopback-only bind with the forward command in the refusal (R7), GPU-source exemption (R8), unit text (R6), one-line `host.json` error (R9), one staleness rule shared with `rb doctor` (§6.8). They are listed in §12 as "My calls (user to check)" approved by the coordinator on 2026-11-10; the user has not approved them. Implementation on branch `claude/review-optimize-2026-11-10`.
- 2026-11-10 implemented on branch claude/review-optimize-2026-11-10 (not merged); verification table updated. Text that the build made false is corrected in place, and each correction has a row in §13 (rows 3 onward).
- 2026-11-10 decided by the user: one-time access key exchanged for a session cookie (§6.6a, §7, §15 question 1). Code: `rb_host/webaccess.py`, `rb web key`; `/healthz` reduced to liveness.

Terms used below. "Hub" is the Linux server that holds the data root and runs the Model Context Protocol (MCP) server `rb-host-mcp`; "node" is the experiment server (first node: `node1`). "Ledger" is `<data_root>/ledger.jsonl`, the append-only file of JSON (JavaScript Object Notation) records written by `rb_host/ledger.py`. "SSH" is Secure Shell. "Pass" is one run of `rb sync` over one node. Times are UTC (Coordinated Universal Time) strings `YYYY-MM-DDTHH:MM:SSZ` from `jobs.now()`. Other abbreviations: HTTP (Hypertext Transfer Protocol), URL (Uniform Resource Locator), TCP (Transmission Control Protocol), DNS (Domain Name System), CSP (the `Content-Security-Policy` HTTP response header), GPU (graphics processing unit), CLI (command-line interface), PR (GitHub pull request). SEC-nn items are findings of the security review in GitHub issue 26 (SEC-03: free text shown to the approver is stripped of control and bidirectional-override characters).

## 1. Intent

The user wants material gathered on the hub without manual steps once the SSH link works, and wants to read the conversations between hub sessions and node sessions on one page served by the hub. The code today has the pieces but they do not fit together:

1. `rb sync` exists (`rb_host/cli.py:170-211`) but nothing runs it, and it hides failures. `server._poll_node` returns `{"error": ...}` instead of raising (`server.py:26-35`, `95-122`), and `once()` only counts `len(got.get("items", []))` (`cli.py:186-187`), so a pass whose poll failed prints `new_items: 0` and exits 0. Board source failures are printed but not counted (`cli.py:188-190`). `--watch` discards the return code of each pass (`cli.py:206-209`), and `jobs.load_cfg()` sits outside the `try` (`cli.py:180`), so a broken `host.json` ends the loop with a traceback. A pass writes nothing about itself, so nobody can tell when the hub last heard from the node.
2. `poll` acknowledges what it fetches (`server.py:118-119`). If `rb sync` runs first, a session's later `poll` returns an empty list, and `thread` returns ledger rows with no body and no path (`server.py:147-149`; inbound fields at `server.py:112-115`). The stored body sits in `inbox/<node>/<msg_id>/body.txt` (`store.py:98-104`), but no tool says so. Unattended sync would therefore hide every reply from the sessions.
3. `send_message` keeps only `body_chars` and attachment names in the ledger (`server.py:84-87`). The text the hub sent is stored nowhere, so half of every conversation cannot be shown.
4. No page on the hub shows conversations. The 8765 pages are vault code on the laptop; `rb share serve` (port 8766) serves counts and allowlisted labels only (`share.py:3-4`, `share_serve.py:1-5`); `scripts/demo_dashboard.py` returns 403 on both pages because it calls the page modules without a `Host` header (`demo_dashboard.py:147-149`) and those modules accept only port 8765 (`jobs.py:24-31`).
5. One pass opens 4 to 7 SSH connections per node: poll 1 (`server._run`), board `queue` 1 and `gpu` 1, `state`/`events`/`kanban` 1 each when a path is configured (`board.py:183-218`, each through `server._run`), and `git_status` 1 (`cli.py:191-192`). There is no connection reuse (`client.py:30-31`).

This design makes one `rb sync` pass reliable and observable, lets it run from a systemd user timer, returns every reply to at most one session `poll` (and to one unless the result of the claiming call is lost), stores outgoing bodies, and adds a read-only page served on the hub's loopback address.

## 2. Goals

- G1. One `rb sync` pass per node runs `hello`, poll (store and acknowledge), `git_status` and the due board sources; it fails (exit 1) when the poll fails or a fetched board source fails for a reason other than `no_path`, `gpu_status_unavailable` or `no_gpus` (ruling R8); it writes `<data_root>/sync/<node>.json` atomically on every pass.
- G2. `rb sync` runs unattended from systemd user units that the user installs once with `rb service install`; the units contain no agent socket path and no secret.
- G3. Every inbound item is returned by at most one MCP `poll` call, and by at least one unless the result of the call that claimed it is lost (§6.4 "Cost"), whether that call fetched it from the node or `rb sync` stored it earlier.
- G4. `send_message` stores the outgoing body (after the hub's withheld check) and attachment metadata under `outbox/`; the ledger line still has no body.
- G5. A session can see sync freshness and node state through `nodes`, and find stored bodies through `thread` (`has_body`, `stored_dir`).
- G6. `rb web serve` shows nodes, pending approvals with the exact `rb approve` command, threads, one thread, jobs and node caches, reading files only.
- G7. The page answers only `GET` and `HEAD`, only with an accepted `Host` header, and is reached from the laptop through an SSH local forward.
- G8. The MCP server still exposes exactly the ten tools of hard rule 1.
- G9. `scripts/demo_dashboard.py` serves its two pages with status 200 and also starts the new page with a seeded conversation.

## 3. Non-goals

- An approval form on the hub page (§6.9).
- Resending failed outgoing messages from the outbox (§6.9).
- Recording messages between Claude sessions on the same machine (§6.9).
- Live update through server-sent events (§6.9).
- Listing node documents, reconciling ledger job status from `job_finished`, and result records for experiments. The experiment-records design (contract §2) covers the last two.
- Reusing one SSH connection for board sources, and `ControlMaster`. `board.refresh` keeps its own connections in this branch (§6.2).
- Routing a reply to a named hub session (`to_session`, issue 15) or carrying `reply_to` to the node (issue 16).

## 4. Anti-goals (failure even if it works)

- A message body appears in a ledger line, in the sync status file, in `board/audit.jsonl`, or in the page's access log (hard rule 6).
- Text that matches a withheld pattern appears on the page, in an `outbox/` file, or in a `poll` result (hard rule 3). This covers bodies and attachment names (`name_hit`, replaced by `(withheld)`).
- A page request opens a connection to a node, writes a file, or changes the ledger.
- An item is returned by two `poll` calls, or an item that was stored is never claimed by any `poll` (an item claimed by a call whose result is lost is the accepted cost of §6.4).
- A pass reports success while its poll failed.
- A unit file carries a passphrase, a key path or an agent socket path, or the page or an MCP tool can approve or cancel a job (hard rule 1).
- The node opens a connection to the hub (hard rule 2).

## 5. Constraints

- Coordinator contract §0 and §1.3. `AGENTS.md` hard rules 1 to 9 are unchanged. Rules touched in behaviour: 1 (ten tools; no approval), 2 (direction), 3 (withheld re-check on store and on render), 6 (no bodies in audit logs).
- The installed node runs older `rb_node` code and cannot be updated from the hub. Its `hello` answers only `node`, `version`, `withheld_extra` (`rb_node/remote.py:62-64`); it may not have `git_status` (added in commit 1fa1f12). Every change here is hub-side, and the hub must work against that node.
- The classification of SSH failures (contract §1.1: `TransportError.code`) lands in a parallel branch. Code here reads `getattr(exc, "code", None) or "transport"` and must work when the attribute is absent; the test for that case uses a local stub exception class without `code`, not `TransportError`, so it still passes after the branches merge (ruling R4).
- `rb_host/board.py` may change in two ways only: a failed source keeps its previous items, and the vault sources are omitted when unset on a non-Windows hub. `rb_host/client.py`, `rb_host/configure.py` and `rb_host/jobs.py` are not changed here.
- `rb_host/cli.py`: the body of `_sync` is replaced, and the `web` subcommand is added in one block directly before the line that registers `config`. The block after `pending` belongs to another implementer.
- Windows code paths stay as they are (contract §0); the new code is used on the Linux hub.
- Reuse: `share_serve.py` server hardening (plain 404/405, headers, 10 s handler timeout, request log without paths), `jobs.clean` (control and bidirectional-override characters removed, SEC-03), `store.valid_msg_id`, `store._within`, `Withheld.load`, `board.load`.

## 6. Architecture

```
laptop (browser)          hub (Linux server)                                         node1
────────────────          ───────────────────────────────────────────────────       ─────────────────────
                          systemd --user: rb-sync.timer ─▶ rb sync (oneshot) ─ssh rb-node1─▶ rb-node serve-remote
                          Claude session ─stdio─ rb-host-mcp (poll, send_message, …) ─ssh─▶ rb-node serve-remote
                                     │ writes                     ▲ reads
                                     ▼                            │
                          <data_root>/ ledger.jsonl  inbox/  outbox/  sync/  board/
                                     ▲ reads only
ssh -N -L 8767:… ──────▶  rb web serve (127.0.0.1:8767, systemd --user: rb-web.service)
```

- `rb sync` and `rb-host-mcp` are the only hub processes that connect to a node, always hub to node (hard rule 2).
- `rb web serve` reads the data root and opens no connection. The laptop reaches it through the user's own SSH login to the hub (`ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`); this is not a bridge key and the node is not involved.

### 6.1 Interfaces

| Name | Kind (read / mutation (pending) / internal) | Notes |
|---|---|---|
| `rb sync [--node N] [--watch SECONDS]` | internal (CLI, command-line interface) | Arguments unchanged. One pass per node (§6.2). Exit 1 when any node's pass failed or `host.json` is missing or invalid; in the latter case exactly one line and no traceback (ruling R9): `error: no usable host.json at <path>; run: rb setup --node NAME --host HOST --user USER` for a missing file, the same with the reason in parentheses for an unreadable or invalid one (`configure.host_json_error`, shared by every `rb` command; §13 row 3). Also exit 1, with one `error:` line, when `host.json` lists no node or `--node` names an unknown one. `--watch` keeps the minimum of 30 s and survives failed passes. |
| `rb web serve [--port 8767] [--bind 127.0.0.1]` | internal (CLI) | Read-only page (§6.6). `--bind` accepts only `127.0.0.1` in this build (the loopback rule of §7, ruling R7); `--port` 0 to 65535. A missing or invalid `host.json` gives the same one-line error as `rb sync` (R9). |
| `<data_root>/sync/<node>.json` | file | Status of the last pass (§6.3). Written only by `rb sync`. |
| `<data_root>/outbox/<node>/<msg_id>/` | file | Outgoing body and metadata (§6.5). Written only by `send_message`. |
| Ledger field `delivered`, `delivered_at` on inbound `message` records | file | §6.4, §8. |
| MCP `nodes` | read | Result gains `status` (§6.8). |
| MCP `poll` | read | Same name and arguments; returns newly fetched items and items stored by `rb sync` that no `poll` has returned yet (§6.4). |
| MCP `thread` | read | Rows gain `has_body`, `stored_dir` (§6.8). Still one level (§6.7). |
| MCP `send_message` | write to node mailbox | Writes `outbox/` first; refuses an unsafe or inbound `msg_id` (§6.5). |
| Other six tools | unchanged | Docstrings rewritten (§6.8). |
| `rb-sync.service`, `rb-sync.timer`, `rb-web.service` | systemd user units | Text in §6.10; written by `rb service install` (contract §1.2). |

The MCP tool set does not change: exactly the ten tools of hard rule 1, pinned by `tests/test_host_tools.py::test_exact_tool_set`.

### 6.2 One sync pass

For each node in `host.json` (or `--node`), in this order:

| Step | Connection | What happens | Failure handling |
|---|---|---|---|
| 1. connect | A (opened with `jobs.connect(cfg, node)`) | SSH child started. | Any exception: pass fails with stage `connect`; steps 2 to 5 skipped. |
| 2. `hello` | A | Reads `version`, `withheld_extra`, `protocol` (absent on the installed node: recorded as 1) through `client.normalize_hello` (ruling R10, closed at integration, commit ceb27f9). | `TransportError` or `RemoteError`: pass fails, stage `hello`, rest skipped. |
| 3. poll | A | `server.fetch_node(cfg, node, client, delivered=False)`: node op `poll`, `store_incoming` for each item not yet in the ledger, ledger append with `delivered: false`, one `ack` for stored and already-known items. | `RemoteError`, `TransportError`, or the ledger lock `TimeoutError`: pass fails, stage `poll`, rest skipped. A single item that `store_incoming` refuses (`ValueError`, `OSError`) is counted in `rejected`, not acknowledged, and retried next pass, as today (`server.py:107-111`); it does not fail the pass. An item whose id belongs to an outgoing or job record is treated the same way (never acknowledged, counted in `rejected` on every pass), and up to 10 such ids are named in `rejected_ids` (§6.3; integration item 14). When the step fails after items were stored, `new_items`, `rejected` and `rejected_ids` still count what was stored and refused before the failure (integration item 11). |
| 4. `git_status` | A | `tree_head` and `tree_dirty` from the node's `tree` block, or from its `trm` block when `tree` is absent (`rb_node/remote.py:362-368` sends `trm` today). A key named `research` is not accepted (ruling R5). As built, no node version sends `tree`: node 0.2.0 still sends its git state under `trm` (setup design §3 keeps that key), and the hub reads `tree` first, then `trm` (§13 row 4). | `RemoteError` (including `unknown_op` on a node that predates the op): `tree_head`/`tree_dirty` null, code in `git_error`, pass not failed. `TransportError`: pass fails, stage `git`, board skipped. |
| 5. board | B1…Bd (one per due source, opened inside `board.refresh` through `server._run`) | `board.refresh(cfg, node, due)`, called only when `due` is not empty. | A due source that ends with an error fails the pass, stage `board`, except `gpu_status_unavailable` and `no_gpus`, which are recorded in the `board` map and do not fail the pass (ruling R8). A failed source keeps its previous items (§8). |

Connection A is closed before step 5. Before step 1 a pass removes stale stage directories (`store.sweep_stage_dirs`, §8) and writes a provisional status file (§6.3), so a pass that is killed (for example by `TimeoutStartSec`) still shows its `last_attempt_at`. Sources are due (`sync.due_sources`) when their cache file is missing or unreadable, its last result was not `ok`, or its age is at least half its cadence (`board.CADENCE_S`: queue and gpu 600 s, events 1800 s, state and kanban 3600 s). `due_sources` never lists a node source that has no configured path (`state`, `events`, `kanban` without an entry in `host.json`): `run_pass` reports such a source as `no_path` in its `board` map without calling `board.refresh` for it, so it writes no cache file and no `board/audit.jsonl` line and opens no connection. The `/nodes` page takes `no_path` from the status file's `board` map.

**Connections per pass per node: 1 + d**, where d is the number of due node sources that need a connection (0 to 5: `queue`, `gpu`, and `state`/`events`/`kanban` only when a path is set). With the default 300 s timer, most passes refresh queue and gpu only: 3 connections; the maximum is 6. Today every pass opens 4 to 7. When connection A fails, the pass stops after that one attempt instead of failing 4 to 7 times. Reusing connection A for the board sources would need a client parameter on `board.refresh`, which is outside the two permitted `board.py` changes; it is deferred (new issue).

Output: one JSON line per node and pass on standard output: `node`, `ok`, `error`, `stage`, `new_items`, `rejected`, `rejected_ids`, `board` (source name to `ok`, an error code, `no_path`, or `skipped` when not due), `tree_head`, `tree_dirty`. The keys `trm_head`/`trm_dirty` of the current line are renamed to `tree_head`/`tree_dirty` to match the status file; no tracked file reads the old keys (`git grep -n trm_head` finds only the line in `cli.py:193` that writes them).

Error codes. The `error`, `git_error` and `board` fields hold codes, never exception text (exception text can contain the SSH alias and, from the node, free text). One rule, with `CODE = ^[a-z][a-z0-9_]{0,39}$`:

- `sync.error_code(exc)`: `RemoteError` gives `exc.code`; `TransportError` gives `getattr(exc, "code", None) or "transport"` (R4); `TimeoutError` from the ledger gives `ledger_locked`; another `OSError` gives `os_error`; any other exception gives `internal`. A result that does not match `CODE` (a faulty node can send any text as `RemoteError.code`) becomes `invalid_code`. This applies to `error` and `git_error`.
- A board error string is kept when it matches `CODE`. The free-text strings the node's `gpu_status` reports (`nvidia-smi not found`, `nvidia-smi failed`, `rb_node/remote.py:328-339`) become `gpu_status_unavailable`, the code the node already uses when it cannot read the GPU list (`rb_node/jobs.py:137`). Any other string becomes `source_error`; such strings come from `server._run`, which turns a `TransportError` into its message text (`server.py:34-35`), and from the class name that `board.refresh` records for an exception (`board.py:235-236`). The mapping is done in `sync.run_pass`; `board.py` is not changed for it.
- A gpu source that reports `gpu_status_unavailable` or `no_gpus` (the node's code for an empty GPU list) does not fail the pass: the code is recorded in the status file's `board` map and on `/nodes`, and the pass result depends on the other steps. Transport errors, a poll error and other source errors (except `no_path`) still fail the pass. My call (user to check), approved by the coordinator on 2026-11-10 as ruling R8; it departs from contract §1.3, under which every failed source fails the pass. Reason: on a node without a working `nvidia-smi` every pass would otherwise fail at stage `board` and `stale` would stay true although the link and the poll work.

`run_pass` catches `Exception` around each step (connect, `hello`, poll, `git_status`, board), records `error_code(exc)` for it (`internal` for an unexpected exception; a `hello` result that is not a JSON object raises `TransportError` in `normalize_hello` and so gives `closed`), writes the status file, and goes on to the next node. It logs only the exception's class name to standard error, never its text, because the text can hold node data.

`--watch S`: the value is checked first (0 or at least 30), before `host.json` is loaded or any connection is opened; each pass reloads `host.json` inside its own `try`; a configuration error prints one line (for a missing or invalid `host.json`, the line of ruling R9) and the loop continues; `KeyboardInterrupt` ends it with exit 0. The timer does not use `--watch`.

Concurrency. The timer's oneshot service cannot overlap itself. A manual `rb sync`, a session's `poll` and the timer can run at once against the same node: the ledger refuses a second `(kind, id)` (`ledger.py:141-148`), so an item is recorded once; `store_incoming` gets a stage directory unique to the process (§8), so one process no longer deletes another's partial download (the survey reproduced that `FileNotFoundError` with two pollers); both processes acknowledge. Only one hub data root may poll a given node: a second data root (for example the laptop's MCP server with its own `host.json`) would take items from this hub's ledger, and the reverse, because each acknowledges on the node what it stored. Two costs remain: a second download of the same attachment, and the fixed temporary name in `board._write_json` (`board.py:54-58`), which can make one of two concurrent refreshes of the same source raise; `run_pass` catches any exception from the board step and records it as a board failure (stage `board`). Fixing that name is outside the two permitted `board.py` changes and is deferred (new issue).

### 6.3 Sync status file

`<data_root>/sync/<node>.json`, written twice per pass, each time to a temporary file in the same directory (unique name, mode 600) and moved into place with `os.replace`, so readers see the old or the new file, never a partial one. The first write, before step 1, is provisional: `last_attempt_at` of this pass, `ok: false`, `error: "incomplete"`, `stage: "running"`, `new_items` and `rejected` 0, `rejected_ids` empty, every other field copied from the previous file. The second write, at the end of the pass, replaces it. A pass that is killed (`TimeoutStartSec`, a crash) leaves the provisional file, so `last_attempt_at` is always current and `stage: "running"` with an old `last_attempt_at` shows a pass that never finished. A reader that sees `stage: "running"` while a pass runs gets `ok: false`; `stale` is computed from `last_ok_at` and does not change.

| Field | Type | Meaning |
|---|---|---|
| `schema` | int | 1 |
| `node` | str | Node name from `host.json`. |
| `last_attempt_at` | str | Start of this pass (UTC). |
| `last_ok_at` | str or null | End of the latest pass that succeeded; copied from the previous file when this pass failed. |
| `ok` | bool | This pass succeeded. |
| `error` | str or null | Code (§6.2), `incomplete` in the provisional file, null when `ok`. |
| `stage` | str or null | `connect`, `hello`, `poll`, `git` or `board`; `running` in the provisional file; null when `ok`. |
| `new_items` | int | Items stored by this pass. |
| `rejected` | int | Items refused this pass: `store_incoming` refused them, or their id belongs to an outgoing or job record. |
| `rejected_ids` | list of str | Ids of refused items, at most 10, only ids that pass `store.valid_msg_id`; ids only, never text (integration item 14, commit 4df6e3e; §13 row 5). |
| `board` | object | Source name to `ok`, code, `no_path` (no configured path; not fetched) or `skipped` (not due). |
| `node_version` | str or null | `hello.version`. |
| `protocol` | int or null | `hello.protocol`, 1 when the node does not report it. |
| `withheld_extra` | int or null | `hello.withheld_extra` (count of the node's file patterns; 0 means only the five fallback patterns are active on the node). |
| `node_seen_at` | str or null | Time of the latest successful `hello`. |
| `tree_head` | str or null | Commit of the node's research tree, as masked by the node. |
| `tree_dirty` | int or null | Count of changed files. |
| `git_error` | str or null | Code when `git_status` was refused. |
| `duration_s` | float | Wall time of the pass. |

Fields filled by a step the pass did not reach (`node_version`, `protocol`, `withheld_extra`, `node_seen_at` when `hello` was not reached; `tree_head`, `tree_dirty`, `git_error` when `git_status` was not reached) keep the previous file's values, so `node_seen_at` gives their age. A step that was reached and refused writes its own result (for example `tree_head: null` with `git_error`). No body, no path, no host name, no exception text. The file is read by `nodes` (§6.8), by the page and by `rb doctor` (contract §1.2; setup design §6.3 check `sync_status`), and all three judge staleness by the one rule of §6.8.

### 6.4 The `delivered` flag and the semantics of `poll`

Every inbound `message` record written from now on carries `delivered` (bool). A record without the key was written before this change and counts as delivered, so the first `poll` after the upgrade does not return the whole history.

- `rb sync` appends inbound records with `delivered: false` and never sets it to true.
- MCP `poll(node=None)` does, for each requested node (all configured nodes when `node` is omitted):
  1. **Fetch.** On one connection, `fetch_node(cfg, n, client, delivered=True)`: items not yet in the ledger are stored and appended with `delivered: true` and `delivered_at`; the call returns only the items whose append succeeded (`Ledger.append` returned true). An item another process recorded first is acknowledged but not returned by this step. If an exception occurs after the first append and before the `ack` returns (a `TransportError` from `get_file` for a later item when the link drops, a ledger `TimeoutError`, a failed `ack`), `fetch_node` does not raise: it returns the items already appended together with `"error"` (the code for a `RemoteError`, `ledger_locked` for a `TimeoutError`, the message text for a `TransportError` as `_run` gives today, `internal` otherwise). `poll` returns those items and records the error in `errors[node]`. Those records are marked delivered and are not acknowledged; the next fetch finds them in the ledger and acknowledges them without returning them again. No ledger write is needed on this path, so it also works when the ledger lock is the cause. With `delivered=False` (`rb sync`) `fetch_node` raises as before: the records it appended are undelivered, and a later claim returns them.
  2. **Claim.** Under `Ledger.locked()`, one read of the latest records; every inbound record of the requested nodes with `delivered` false is rewritten with `delivered: true`, `delivered_at`. The lock covers only this read and these writes (`Ledger.claim`), never a network call or a body read.
  3. **Read.** After the lock is released, for each claimed record the body is read from `inbox/<node>/<msg_id>/body.txt` and masked again with the hub's current patterns (`Withheld.load(cfg.withheld_patterns_file).mask_text`); attachment names come from the record's `files`, and a name for which `name_hit` is true is replaced by `(withheld)`; the same applies to `reply_to` (a caller-chosen message id can be any text). The item has the same shape as a fetched item (`msg_id`, `node`, `kind`, `reply_to`, `body`, `files`, `quarantined`) plus `stored: true`.
  4. Result: `{"items": fetched + claimed}`, plus `errors` (node name to message) when a node could not be polled, as today.
- Two concurrent pollers (two sessions, two MCP server processes): an item fetched by both is appended once; only the process whose append succeeded returns it. Claims run under the ledger lock, so the second claimer reads the records the first one already rewrote and claims nothing twice. No item is returned by two `poll` calls.
- A session that polls while the timer runs: if the session reaches the node first, it stores and returns the item, and the timer's pass finds it in the ledger and only acknowledges it. If the timer stored it first, the session's claim step returns it. If both store it at the same moment, whichever append wins decides; when the timer wins, the session returns the item through its claim step in the same call.
- Node unreachable: the fetch step records the error in `errors[node]`, and the claim step still returns the stored items of that node. A session gets what the timer stored even while the link is down.
- `node` argument: only that node's records are claimed.
- Missing `body.txt` (deleted by hand): the item is returned with `body: ""` and `body_missing: true`, and is marked delivered.
- Ledger lock not obtained within 10 s (`ledger.py:13-14`, `108-109`): today this `TimeoutError` escapes `_run` and fails the tool call. Now `poll` catches it per step and reports `errors["ledger"] = "ledger_locked"`; unclaimed records stay undelivered for the next call.
- Cost: a crash or a dropped MCP connection between the claim and the session receiving the result means no `poll` returns that item again. It stays on disk and is shown by `thread` (`has_body`) and on the page. The design prefers at most once to the session over a second copy, because a session acting twice on one reply is the worse failure.
- Hub processes started before this change: an MCP server process that was started earlier runs the old `poll`, which has no claim step. Once the timer stores items with `delivered: false` and acknowledges them on the node, such a process never sees them. All Claude sessions on the hub (and so their MCP servers) must be restarted before the timer is enabled (§9 step 8).
- The page never claims; it shows "not yet returned by poll" for undelivered records.

### 6.5 Outgoing bodies: `send_message` and `outbox/`

Order in `send_message(node, body, attachments, reply_to, from_session, msg_id)`:

1. `cfg.alias(node)`; each attachment must be a file (unchanged).
2. `mid = msg_id or uuid4().hex`; `mid` must pass `store.valid_msg_id`, otherwise `ValueError("unsafe msg_id")` before anything is written. Today a caller-supplied `msg_id` is not checked on the hub; it now becomes a directory name.
3. If the ledger already holds `mid` with `direction` other than `out`, `ValueError("msg_id belongs to an inbound message")`. Today `send_message` would overwrite such a record's status with `sent` (`server.py:91`).
4. `store.store_outgoing(cfg, node, mid, body, files)` writes `outbox/<node>/<mid>/body.txt` (the body after `Withheld.mask_text`: lines that match a pattern are blanked) and `provenance.json` (`node`, `msg_id`, `created`, `body_chars`, `body_sha256` (SHA-256 of the body as sent, before masking), `body_withheld_lines`, `attachments`: list of `{index, name, bytes, sha256}`, where a name for which `name_hit` is true is stored as `(withheld)`). Both files are written to a temporary name (mode 600) and renamed. Attachment files are not copied. On a retry with the same `mid`, a stored `body_sha256` that differs from the new body's raises `ValueError("msg_id already used with a different body")`; a record from before the hash existed is compared by its masked text (§13 row 6). Comparing the hash of the unmasked body keeps a retry valid after the hub pattern file changed; the node checks only attachments on a retry (`rb_node/remote.py:87-94`), so without this check the outbox could show text the node never received.
5. Ledger append (when the record does not exist yet), unchanged fields: `kind`, `id`, `direction: out`, `node`, `reply_to`, `from_session`, `attachments` (names), `body_chars`, `status: pending_send`, `created`. No body and no path.
6. Upload and `msg_commit` (unchanged); on success `status: sent`. The uploaded body is the caller's body, unchanged, as today. Only the stored copy is masked.

Why bodies are stored outside the ledger: hard rule 6 forbids message bodies in audit logs, and the ledger is the hub's audit record. It is also ingested by the vault session browser (`vault-export/session-calendar/bridge_edges.py`), whose rule is metadata only (design spec §8). Separate files keep the ledger shareable and small, let the page re-mask a body when it is shown, and match the layout the first design already named (`inbox/`/`outbox/`, spec §8).

Why after the withheld check: the hub keeps no second copy of text that matches a withheld pattern, as `store_incoming` already does for inbound bodies (`store.py:101-104`). The consequence is that the stored copy is not always the text that was sent: when `body_withheld_lines` is above 0, the outbox cannot be used to resend the message (§6.9).

### 6.6 Page routes

`rb web serve` reads, per request: the ledger (through `threads.load`, cached by file size and modification time), `inbox/` and `outbox/` body and provenance files, `sync/<node>.json`, the board cache files (through `board.load`), and the hub withheld pattern file. Every page shows a banner when the hub pattern file is unreadable or unparseable (`Withheld.source_error`; only the five fallback patterns are then applied) and when a node's status reports `withheld_extra == 0`.

| Route | Reads | Shows |
|---|---|---|
| `/` | sync files, ledger, bodies of thread roots | Nodes: name, sync `ok` or error code and stage, last success (age) with a stale marker by the rule of §6.8, last attempt, node version, protocol, `withheld_extra`, `tree_head` (12 characters) and `tree_dirty`, undelivered count. Pending approvals: job id, operation, node, config name or target job id, GPU ids, GPU-hours, note, created, and the exact commands `rb approve <job_id>` and `rb reject <job_id>` as text. The 10 threads with the latest activity: thread id (link), node, first line of the root body (re-masked, 100 characters), message count, last activity, state, undelivered count. Refreshes every 30 s (`<meta http-equiv="refresh">`). |
| `/threads` | ledger, root bodies | All threads, latest activity first, at most 500 rows with a "N more not shown" line; same columns as on `/`. Refreshes every 30 s. |
| `/thread/<id>` | ledger, inbox/outbox files of the thread | Thread id, node, state; then each record in time order: time, direction (`hub to node` / `node to hub`), kind (`message`, `reply`, `event`), `from_session`, status, "not yet returned by poll" for undelivered inbound records, `reply_to` (link when it is in the thread), attachments (name, bytes, first 12 characters of sha256, status; quarantined files as a count and reason code, never a name), body in `<pre>` (re-masked, cleaned, cut at 20 000 characters with `[truncated]`), or "body not stored" for an outgoing record sent before this change. `<id>` is any message id in the thread. Refreshes every 60 s. |
| `/jobs` | ledger, event bodies | Job records grouped by status (`pending_approval`, `approved`, `queued`, `cancelled_requested`, `rejected`, other): id, operation, node, config name or target job id, GPUs, GPU-hours, note, created, approved or rejected time; pending ones show the two commands. Under each job, its `job_finished` events: time, status, `git_head` (12 characters). Events whose `job_id` matches no job are listed at the end. The ledger status of a queued job stays `queued`; the event is shown beside it, not merged (§3). |
| `/nodes` | sync files, board cache | Per node: every field of the status file; then the board sources with `fetched_at`, stale flag and error (a source whose entry in the status file's `board` map is `no_path` is shown as "no path configured", not with the `never_fetched` that `board.load` reports when no cache file exists): queue counts by state, GPU rows (index, name, memory used and total, utilization), state keys, events (at most 50), kanban counts. |
| `/healthz` | nothing | `application/json`: `{"ok": true}`. Liveness only, no session needed; before the access decision it also returned `ledger_mtime_ns`, which was removed because it shows when the ledger last changed. |
| `/enter` | access file | `GET /enter?key=KEY` exchanges a one-time key for a session cookie (§6.6a). No page. |

Anything else is 404. The route is matched on the raw request target before any percent-decoding: `/`, `/threads`, `/jobs`, `/nodes`, `/healthz`, `/enter`, or `/thread/` followed by `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; a query string is ignored, except that `/enter` reads its `key` parameter. Every HTML page carries one navigation line with links to the four fixed routes `/`, `/threads`, `/jobs` and `/nodes` (integration item 13, commit 791cc60). The id is then looked up among ledger message ids; it is never joined into a path. Ids that do not fit that pattern (`store.valid_msg_id` also allows spaces) are listed without a link. Body and provenance paths are built from the ledger record's `node` and `id`, checked again with `valid_msg_id`, against the configured node names, and with `store._within` against `inbox/` or `outbox/`.

Thread states: `delivery pending` when any outgoing record of the thread has `status: pending_send`; otherwise `open` when the latest non-event record is inbound; otherwise `answered`.

### 6.6a Access key

Decided by the user on 2026-11-10. The order of checks in a request is: `Host` header (403), route (404 for a route that does not exist), access (401), render. `/healthz` and `/enter` need no session.

- `rb web key [--port P] [--minutes 1..60] [--session-hours 1..168]` (defaults 8767, 10, 12) runs in a hub terminal and prints `http://127.0.0.1:P/enter?key=KEY`, the expiry time (the key works once) and the session length. `--revoke` removes every key and session; `--status` prints the counts. It makes no terminal check: a process of the same user can read the data directory anyway, and the key protects against other accounts.
- `GET /enter?key=KEY` with an unused, unexpired key answers 303 to `/` with `Set-Cookie: rb_web_<port>=<token>; HttpOnly; SameSite=Strict; Path=/; Max-Age=<session seconds>`. The cookie name carries the port because cookies are not separated by port; there is no `Secure` attribute because the page is plain HTTP on loopback. A missing, malformed, unknown, expired, used or repeated `key` parameter answers 401. `HEAD /enter` never uses a key (a link preview must not consume it) and answers 401.
- Every other route except `/healthz` without a valid cookie answers 401, `text/plain`, body `access key required: run "rb web key" in a hub terminal and open the address it prints`. The answer is the same for an unknown `/thread/<id>`, so a client without a session learns nothing about which ids exist.
- State is `<data_root>/web/access.json` (directory 0700, file 0600, written atomically): SHA-256 hashes of pending keys (with expiry and session length) and of sessions (with expiry). A key and a token are 32 random bytes from `secrets.token_urlsafe`, shown once and never stored. The command and the server are separate processes and the server is threaded, so every change holds an exclusive `flock` on `access.lock`; using a key removes it and creates the session under one lock, so two requests with one key give one session. At most 20 pending keys and 50 sessions; when a list is full the entry that expires first is dropped. A missing or malformed file means no keys and no sessions (deny).
- The access log, as before, holds method, route name and status; the key, the query string and the cookie are never written. The MCP server is not touched; the ten tools stay.
- Why not a password with a login form: a password is a long-lived secret that would have to be stored on the hub, and a form needs `POST`, which the read-only page forbids (§7: `GET` and `HEAD` only, `form-action 'none'`). A one-time key expires in minutes, is stored only as a hash, and is exchanged with a `GET`.
- Residual risk: a key or cookie sent to `127.0.0.1:P` can be captured by another local account that listens on that port while the page service is not running. A Unix-socket forward would remove this; it is not built and stays a possible later change.

### 6.7 Thread-building rule

`threads.load(cfg)` takes the latest record per id from the ledger (last line wins, `ledger.py:134-139`) and:

1. Takes every `message` record as a vertex. For each record whose `reply_to` names another message record, it joins the two (union-find). Threads are the connected components, so a hub follow-up to a node reply, which `Ledger.thread` does not return (one level, `ledger.py:163-166`), is in the same thread.
2. A `reply_to` that names no known record leaves the record as the root of its own thread, marked `reply_to unknown`.
3. Event records (`msg_kind: event`): a body that parses as JSON with `"event": "job_finished"` and a `job_id` equal to a ledger job id is attached to that job, not to a thread. The link exists only through the stored body: a body blanked by the withheld check, or a missing body, gives no link. `responder_failed` events carry `reply_to` (`rb_node/spawn.py:145`) and join their message's thread by rule 1. Other events without `reply_to` are listed per node as events without a thread.
4. Time of a record: for an inbound record whose id starts with 20 digits and a hyphen (the node's out-item id is `time_ns` zero-padded, `rb_node/mailbox.py:152`), that number converted to UTC; otherwise `created`. Records sort by time, then by ledger order. A record whose `reply_to` names a record of the same thread never sorts before that record: its sort time is raised to the time of the record it answers (node clock behind the hub clock), so the state is `open` when the node reply is the last record. The thread id is the id of its root, the first record whose `reply_to` is outside the thread.
5. Quarantined attachment names never enter the model (`provenance.json` omits them, `store.py:150-155`).

The MCP `thread` tool keeps its one-level result (`Ledger.thread`, pinned by `tests/test_ledger.py`); returning the whole component through the tool is deferred (§6.8).

### 6.8 Flexible synchronisation over MCP within the ten tools

Changes to existing tools:

- `nodes()` returns `{"nodes": [...], "status": {<node>: {...}}}`. Per node: `synced` (false when no status file exists; then the other fields are null), `ok`, `error`, `stage`, `last_attempt_at`, `last_ok_at`, `age_s` (seconds since `last_ok_at`), `stale` (computed from `last_ok_at` only: true when there was no successful pass in the last 900 s, three default timer intervals, or when `last_ok_at` is null), `node_seen_at` (latest successful `hello`; a node can be stale because one board source keeps failing while `node_seen_at` shows that the link and the poll work), `node_version`, `protocol`, `withheld_extra`, `hub_withheld_extra` and `hub_withheld_rejected` (usable and non-compiling patterns in the hub's own pattern file at the time of the last pass; null in a status file written before these fields existed), `undelivered` (count of inbound records with `delivered` false). The `stale` rule is the single rule for sync-status staleness (the board cache keeps its own per-source stale flag, §8): `nodes`, the page (`/` and `/nodes`) and the `sync_status` check of `rb doctor` (setup design §6.3) all use it, through the readers in `threads.py` (`read_status`, `summary`; joined at integration, commit ceb27f9, ruling R10). The doctor also reports a pass left at `stage: "running"` with a `last_attempt_at` older than 900 s as one that never finished. `tests/test_host_tools.py::test_nodes` changes from an equality on the whole result to checks on `nodes` and `status`.
- `poll` as in §6.4.
- `thread(msg_id)` rows: `has_body` (the body file exists) and `stored_dir` (absolute path of `inbox/<node>/<id>/` or `outbox/<node>/<id>/`, or null). A session on the hub can read the file with its own Read tool; that copy was masked when stored, not with patterns added later (only `poll` and the page re-mask).
- `send_message` as in §6.5.
- Docstrings of all ten tools state the arguments, the result shape and the error shape; `submit_job` and `cancel_job` say that they only create a `pending_approval` record and that approval is the user's step (`rb approve` in a hub terminal); `poll` keeps the phrases "masked on the node" and "checked again on the laptop" that `test_poll_docstring_states_masking_and_recheck` pins, and says that each item is returned once.

Gap table. "Resolved here" means built in this branch under contract §1.3.

| # | What a session cannot do today | Side | Outcome |
|---|---|---|---|
| 1 | See replies after `rb sync` ran first: `poll` is empty | hub session | Resolved here: `delivered` flag and claim step in `poll` (§6.4). |
| 2 | Know whether the link works, when the hub last heard from the node, the node version, whether the node loaded its pattern file | hub session | Resolved here: `nodes.status` from the sync file (§6.8). |
| 3 | Find the body of a reply another session received, or of a message it sent | hub session | Resolved here: `thread` rows `has_body`, `stored_dir`; outgoing bodies in `outbox/` (§6.5). |
| 4 | Know that items are waiting before polling | hub session | Resolved here: `nodes.status.<node>.undelivered`. |
| 5 | Pass a `msg_id` safely: unsafe ids reach the file system, an inbound id gets overwritten | hub session | Resolved here: `send_message` checks (§6.5). |
| 6 | Read tool behaviour from the tool list | both | Resolved here: rewritten docstrings. |
| 7 | Get the whole conversation through `thread` (it returns one level) | hub session | Deferred (new issue); the page shows components now. |
| 8 | Learn whether the node started a responder (`send_message` says `sent` even when `msg_commit` returned `triggered: false`, `server.py:68`, `rb_node/remote.py:161-172`) | hub session | Deferred (new issue): add `triggered` to the `send_message` result. |
| 9 | See how many items the hub refused (`poll` drops `rejected`, `server.py:125-144`) | hub session | Deferred (new issue); the count is in the sync status file. |
| 10 | Have a failed send delivered when the link returns | hub session | Deferred (new issue): outbound retry from `outbox/` (§6.9). |
| 11 | List node documents before `read_doc` | hub session | Deferred (new issue): needs a node op, so a node update. |
| 12 | See a job's end state in the ledger | hub session | Deferred to the experiment-records design (contract §2); the page shows `job_finished` next to the job. |
| 13 | Address a reply to one hub session; see `reply_to` and `from_session` on the node | both | Deferred: issues 15 and 16. |
| 14 | Know on the node whether the hub received an item (`outbox_list` is not a `serve-local` tool, `rb_node/local.py:24-37`) | node session | Deferred (new issue); `serve-local` is not one of the ten hub tools. |
| 15 | Run a live node session without racing the spawned responder | node session | Deferred: issue 41. |
| 16 | Tell an agent problem from a refused key from a network failure | both | Partly resolved: the parallel branch (contract §1.1) adds `TransportError.code`, and the sync status file then carries that code. `poll` errors still carry the message text, because `server._run` returns `str(exc)` for a `TransportError` (`server.py:34-35`) and this branch does not change `_run`; the message text of the parallel branch names the cause. Returning the code from `_run` is deferred (new issue). |
| 17 | Start a sync from a session | hub session | Not built: `poll` already fetches; an eleventh tool would change hard rule 1. |

### 6.9 Deliberately not built

- **Approval form on the page.** Hard rule 1 names two approval surfaces, `rb approve` and the loopback `/rb/approve` route on port 8765. A form on 8767 would be a third and changes the rule text, which is the user's decision. It would also turn a read-only page that holds message bodies into a page that accepts requests with side effects (cross-site request forgery token, passphrase field, `Origin` check). The page shows the command to type instead.
- **Outbound retry from the outbox.** The stored copy is masked, so it is not the sent text when `body_withheld_lines > 0`; attachment files are not copied; the node compares only attachments on a retry (`rb_node/remote.py:87-94`); and an unattended resend needs a rule for messages a session already resent by hand. Those are decisions for a retry design (new issue), related to issues 15 and 16.
- **Local session-to-session messages.** The bridge carries node traffic only; no file in `rb_host/` or `rb_node/` sees messages between two Claude sessions on one machine. Recording them needs a Claude Code hook on the message tool (a change to the user's settings) or reading transcripts, which are private and outside the masking rules. Deferred (new issue).
- **Server-sent events.** They need a script in the page, so the Content-Security-Policy (CSP) header would have to allow scripts; each open stream holds a handler thread of a small threaded server. Data changes at most once per timer interval (300 s), so a `<meta>` refresh of 30 to 60 s is enough.

### 6.10 Units written by `rb service install`

`rb service install [--interval SECONDS=300] [--port 8767] [--print]` (contract §1.2, `rb_host/service.py`) fills three templates, shows them, asks y/N, keeps a backup of an existing file, and writes them to `~/.config/systemd/user/`. Fields in braces are filled at install time: `{rb}` is the absolute path of the `rb` entry point of the environment running the command (`Path(sys.executable).with_name("rb")`; the command warns when the path contains `/.claude/worktrees/`, because a worktree is deleted later); `{host_json}` is the absolute path of the `host.json` the command itself loaded (found through `RB_HOST_CONFIG`, `jobs.py:39-41`, or else `<default_root()>/host.json`, where `default_root()` reads `RB_HOST_ROOT`, `config.py:18-26` and `52-53`). The line `Environment=RB_HOST_CONFIG={host_json}` is always written in both services. `{rb_host_root_line}` is the line `Environment=RB_HOST_ROOT=<value>` when the installing shell has `RB_HOST_ROOT` set, with that value made absolute (`~` expanded, then `os.path.abspath`, so a relative value means the same directory as in the installing shell), and is left out (no line, no comment) otherwise. As built, `rb service install` also refuses (one `error:` line, exit 1, nothing written) when `host.json` does not exist, when `--interval` is below 30 or `--port` is outside 1 to 65535, and when the `rb` path, the `host.json` path or the `RB_HOST_ROOT` value contains whitespace or `%`, which a unit line cannot hold unescaped; the unit directory is `$XDG_CONFIG_HOME/systemd/user` when that variable is an absolute path, else `~/.config/systemd/user` (§13 row 7). This section is the single source of the unit text (ruling R6). Reason: `RB_HOST_ROOT` also sets the default `data_root` and the default withheld pattern file (`config.py:29-40`). If the units set it to the directory of `host.json` while the terminal and the MCP server leave it unset (and `host.json` omits `data_root` or `withheld_patterns_file`), the timer would store items in a ledger the MCP server never reads, acknowledge them on the node, and re-check with the five fallback patterns only. Copying the shell's own environment gives the units the same derived defaults as the terminal. `{interval}` and `{port}` come from the options. `%h` is expanded by systemd to the home directory.

`rb-sync.service`

    [Unit]
    Description=research-bridge hub sync, one pass per start (pull only; never approves a job)
    ConditionPathExists={host_json}

    [Service]
    Type=oneshot
    Environment=RB_HOST_CONFIG={host_json}
    {rb_host_root_line}
    ExecStart={rb} sync
    TimeoutStartSec=240
    NoNewPrivileges=yes

`rb-sync.timer`

    [Unit]
    Description=Start rb-sync.service every {interval} seconds

    [Timer]
    OnActiveSec=60
    OnUnitInactiveSec={interval}
    RandomizedDelaySec=20
    AccuracySec=10s

    [Install]
    WantedBy=timers.target

`rb-web.service`

    [Unit]
    Description=research-bridge hub page (read-only, loopback)
    ConditionPathExists={host_json}

    [Service]
    Type=simple
    Environment=RB_HOST_CONFIG={host_json}
    {rb_host_root_line}
    ExecStart={rb} web serve --port {port} --bind 127.0.0.1
    Restart=on-failure
    RestartSec=5
    NoNewPrivileges=yes

    [Install]
    WantedBy=default.target

An earlier version of these three files (with `Environment=RB_HOST_ROOT` always written), filled with temporary paths, passed `systemd-analyze --user verify` (systemd 255, run 2026-11-10 in a scratch directory; not installed). The current text, generated by `rb_host/service.py` `units()` into a temporary directory both without and with the `RB_HOST_ROOT` line, passed `systemd-analyze --user verify` again on 2026-11-10 (systemd 255, exit 0, no output; not installed, no `systemctl` command run).

Notes on the text:

- `Type=oneshot` plus a timer: each pass is a new process, its result shows in `systemctl --user status rb-sync.service` and the journal, and passes cannot overlap. `OnActiveSec=60` starts the first pass a minute after the timer starts (at boot through `timers.target`, or after `enable --now`); `OnUnitInactiveSec` then counts from the end of each pass.
- `TimeoutStartSec=240` bounds a pass whose connection hangs (a oneshot service has no start timeout by default). The parallel branch adds `ServerAliveInterval=15`, `ServerAliveCountMax=3` to the SSH argument list (contract §1.1), so a dead link ends after about 45 s of silence.
- No `SSH_AUTH_SOCK` line, no `EnvironmentFile`, no `ExecStartPre=ssh-add -l`. The units find the agent the same way the MCP server does: `NodeClient` asks `sshenv.agent_socket(alias)` (contract §1.1), which tries `$SSH_AUTH_SOCK`, `$XDG_RUNTIME_DIR/gcr/ssh`, `$XDG_RUNTIME_DIR/openssh_agent` and `$XDG_RUNTIME_DIR/rb-ssh-agent` and prefers a socket that holds the alias's key. The systemd user manager sets `XDG_RUNTIME_DIR` for its units. When no key is loaded, the pass fails with the code from that classification (for example `agent_empty`) in the journal and in the status file.
- `rb-web.service` needs no agent: the page opens no connection.
- `Environment=RB_HOST_CONFIG` is always written and `RB_HOST_ROOT` only when the installing shell has it (as an absolute path), so the units load the same `host.json` and derive the same `data_root` and withheld pattern file as the terminal that ran the install. The MCP server must see the same two variables (or none); the MCP registration that `rb setup` prints carries them by the same rule (setup design §6.2 step 8, R6).
- `PrivateTmp` and `ProtectSystem` are left out: in a user unit they need unprivileged user namespaces, which Ubuntu may restrict, and a unit that fails to start is worse than the small gain. `ProtectHome` cannot be used because the data root, `~/.ssh/config` and the checkout are under the home directory.

What the user does once (the command prints steps 2 and 3; it does not run them):

1. Restart every Claude session on the hub, so that its MCP server runs the new `poll` with the claim step (§6.4), and make sure no other hub data root (for example the laptop's MCP server) polls the same node. Then, in a hub terminal: `rb service install`, read the three files, answer `y`.
2. `systemctl --user daemon-reload && systemctl --user enable --now rb-sync.timer rb-web.service`.
3. Check lingering: `loginctl show-user "$USER" -p Linger`. If it says `no`, `sudo loginctl enable-linger "$USER"` (an administrator may be needed); without it the user manager and its units stop at logout.
4. After each reboot: `rb agent` in a terminal (types the key passphrases; contract §1.2). Until then every pass fails with an agent code.
5. Check: `rb service status`, or `systemctl --user start rb-sync.service; journalctl --user -u rb-sync.service -n 20`; on the laptop `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>` and open `http://localhost:8767/`.

Consequence the user accepts with step 4: the unlocked bridge key stays in the agent all day, usable by any process of the same account. The MCP server already depends on this. Whether a dedicated key without passphrase, restricted on the node, is preferable is issue 25 point 4.

## 7. Security

- **Bind.** Default `127.0.0.1`, port 8767. Loopback TCP is reachable by every account on the hub, not only the user's. The `Host` check below does not stop a local account, because it can send any header. If the hub has other accounts, a Unix-socket forward with mode 600 would close that gap; it is not built (§15).
- **Host check.** The `Host` header, lowercased, must equal one of `127.0.0.1:P`, `localhost:P`, `[::1]:P`, where P is the port the server actually listens on (`server_address[1]`); a missing header is refused. Refusal: 403, body `forbidden`. This stops a web page in the laptop browser that rebinds its own DNS (Domain Name System) name to 127.0.0.1 from reading the page, because its requests carry its own host name. `jobs.host_allowed` is fixed to port 8765 (`jobs.py:24-31`), so `web.py` has its own check.
- **Laptop access.** `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`, then `http://localhost:8767/`. Use the same port on both sides: the browser's `Host` header carries the laptop-side port, so a forward to another local port (for example one chosen by an editor's automatic port forwarding) gets 403 by design.
- **Non-loopback bind** (My call (user to check), approved by the coordinator on 2026-11-10 as ruling R7; open question 6). `--bind` accepts only loopback addresses; in this build the only accepted value is `127.0.0.1`, because `ThreadingHTTPServer` is IPv4 by default and `::1` would need an IPv6 server class, which is not built. Any other value, a specific address such as `<HUB_ADDR>`, `::1`, or a wildcard (`0.0.0.0`, `::`, empty), makes `make_server` raise `ValueError` and `rb web serve` exit 1 with one `error:` line that names the access path, `ssh -N -L PORT:127.0.0.1:PORT <hub>` (with the port filled in; as built: `error: --bind accepts only 127.0.0.1; from another machine use: ssh -N -L PORT:127.0.0.1:PORT <hub>`), until the user decides otherwise. A non-loopback bind would make message bodies readable without a login by anyone who can reach `<address>:<port>` (on this hub, `<HUB_SUBNET>`); the SSH forward gives the same access to the user only. Refusing is cheap and can be relaxed later; accepting first would add code and an exposure before the user answers. The accepted `Host` values are always the three loopback names of the Host check above.
- **Methods.** `GET` and `HEAD`; every other method gets 405 with `Allow: GET, HEAD`, the same plain body as `share_serve._no_method`. No route changes page state; the only write is `/enter` removing a used key from the access file and storing a session hash (§6.6a). The one cookie is the session cookie; there is no login form.
- **Re-masking at render.** Each request loads the hub patterns once and applies them to every string taken from a ledger record or a stored file: bodies (`mask_text`, hit lines blanked), body previews, attachment names, `from_session`, `note`, `config_name` (`name_hit`: replaced by `(withheld)`). Files were masked at store time with that day's patterns; a pattern added later applies to old messages on the page, as the node does on poll (`rb_node/remote.py:174-188`).
- **Cleaning and escaping.** Free text passes `jobs.clean` (control and bidirectional-override characters removed); bodies use a variant that keeps newlines and tabs. Every interpolated value passes `html.escape(..., quote=True)`; bodies go into `<pre>`; no Markdown, no automatic links. The only attribute values built from data are `href="/thread/<id>"` with ids that match the route pattern; the navigation line's four `href` values (`/`, `/threads`, `/jobs`, `/nodes`) are fixed text, not data.
- **No scripts or external resources.** Inline style only. Response headers: `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`. The output contains no `<script`, no `<form`, no `src` attribute, no external resource, and no attribute that holds a URL other than the page's own `/thread/<id>` links and the navigation links to `/`, `/threads`, `/jobs` and `/nodes` (§13 row 8); a URL inside a message body is shown as escaped text, not as a link.
- **Attachments.** Names, sizes, hashes and status only; no download route, no inline display. Quarantined files appear as a count and reason code.
- **Access log.** One line per request on standard error (the journal under systemd): method, route name (`index`, `threads`, `thread`, `jobs`, `nodes`, `healthz`, `enter`, `other`) and status. No path, so no message id; no query; no client address; no `Host` value; no user agent; no body. A handler exception logs its class name only.
- **No writes, no connections.** A page request reads files; it never calls `jobs.connect`, never starts a subprocess, never appends to the ledger and writes no file except the access file on `/enter` (the ledger cache is in memory). `web.py` and `threads.py` import no HTTP client module. Neither imports `rb_host.server`, `rb_host.board`, `rb_host.sync` or `mcp` at module level; the sync status readers (`status_path`, `read_status`, `summary`) live in `threads.py` so that `web.py` and `nodes()` need neither `sync` nor `server` to read them. `board` (for `board.load`) is imported lazily inside the `/nodes` renderer, and `board` imports `server` and therefore `mcp` at module level (`board.py:20`, `server.py:12`). So the import claim holds when `web.py` is imported; after the first `/nodes` request the page process has `mcp` and `rb_host.server` loaded, but it still calls no function that opens a connection.
- **Threat model in scope:** other pages in the laptop browser (DNS rebinding: Host check; cross-site requests: no state-changing route), message bodies written to mislead (prompt injection: escaped and shown as data, never as instructions; rule 6 and spec §7), patterns added after storage (re-mask). **Out of scope:** other accounts on the hub (open question 1), root on the hub, the user's own account.
- **MCP side.** No tool approves, cancels or starts a sync; `submit_job` and `cancel_job` still only write `pending_approval` records (hard rule 1). `poll` re-masks claimed bodies, so a pattern added after `rb sync` stored a reply still applies when a session receives it.

## 8. Data and ledger

- **Inbound `message` records** gain `delivered` (bool) when written, and `delivered_at` (UTC) when claimed. Records without `delivered` count as delivered. Each claim appends one updated line (last line wins). No other field changes; in particular no body and no path.
- **Outbound `message` records** are unchanged; the body is in `outbox/<node>/<msg_id>/body.txt`, metadata in `provenance.json` (§6.5). Records written before this change have no outbox files; the page says "body not stored".
- **`Ledger.claim(match, **fields)`** (new): under the lock, one read of the latest records, one appended line per matching record, returns the new records.
- **`sync/<node>.json`** (§6.3), written only by `rb sync`.
- **Board cache** (`board.py`): when a source fails, the record keeps the previous `items` and their `fetched_at`, sets `ok: false` and the error, and adds `attempted_at`; the stale flag is computed from `fetched_at`, so old items are shown as stale, not as fresh. On success `fetched_at` and `attempted_at` are both the fetch time. On a non-Windows hub, `vault:portfolio` and `vault:priorities` are omitted from `board.load` when `host.json` has no path for them, instead of reporting `missing` for `D:/raw/...` defaults (`board.py:28-30`, `360-361`).
- **`store_incoming`** uses a stage directory unique to the process (`quarantine/<node>/<msg_id>/.stage-<pid>-<random>/`) and removes an empty `quarantine/<node>/<msg_id>/` afterwards. A process that is killed (for example by `TimeoutStartSec`) or crashes leaves its stage directory behind, and no later call uses that name again; so each pass first calls `store.sweep_stage_dirs(cfg, node, older_than_s=3600)`, which removes `quarantine/<node>/*/.stage-*` directories whose modification time is more than one hour old (well above the 240 s pass timeout, so a download in progress in another process is not removed) and then the empty parents. The same sweep removes temporary files `.body.txt.<hex>.tmp` and `.provenance.json.<hex>.tmp` left by a killed writer in `inbox/<node>/*/` and `outbox/<node>/*/` when they are older than one hour (integration item 12, commit 4df6e3e).
- **Session browser** (vault `bridge_edges.py`): reads the same ledger fields as before; `delivered` is ignored there. Issue 15 (`to_session`, attachment byte totals) is unchanged.

## 9. Scope of this phase

1. `Ledger.claim`; `store_outgoing`; unique stage directory in `store_incoming`; `sweep_stage_dirs`.
2. `server.fetch_node`, `_poll_node` kept as a wrapper, `poll` with the claim step, `send_message` with the outbox, `nodes.status`, `thread` row fields, docstrings.
3. `rb_host/sync.py` and the new body of `rb sync`.
4. `board.py`: failed source keeps previous items; vault defaults omitted on a non-Windows hub.
5. `rb_host/threads.py`, `rb_host/web.py`, `rb web serve`.
6. `scripts/demo_dashboard.py`: Host header fix, seeded conversation, new page.
7. Tests (brief: in the gitignored review working directory, not in this repository), full suite.
8. **User:** restart every Claude session on the hub (so its MCP server runs the new `poll` with the claim step, §6.4) before enabling the timer; make sure no other hub data root (for example the laptop's MCP server) polls the same node; then `rb service install`, the two `systemctl` commands, lingering check, `rb agent` after reboot (§6.10).
9. **User, live check:** one `rb sync` against node1 (the unchecked box of PR 45), then the page through the SSH forward.

## 10. Verification

Updated 2026-11-10 after the build: every named test was found in `tests/` and its file run with `rtk proxy uv run --extra host pytest -q tests/<file>` on the hub (Python 3.12.11); every file passed (test_sync 34, test_host_tools 64, test_host_store 48, test_ledger 5, test_web 26, test_threads 18, test_demo_dashboard 2, test_service 15, test_doctor 65). Live checks need the user and node1 and were not run: this review has no node contact.

| Goal / anti-goal | Check | Kind (unit test / live check / manual) | Status |
|---|---|---|---|
| G1 | `tests/test_sync.py::test_pass_order_on_one_connection`, `test_poll_error_fails_pass`, `test_board_failure_fails_pass_except_no_path`, `test_status_file_fields_and_atomic_write`, `test_failed_pass_keeps_last_ok_at`, `test_provisional_status_written_first`, `test_due_sources`, `test_due_sources_without_paths`, `test_unexpected_exception_is_internal`, `test_failure_after_storing_keeps_the_counts`, `test_clashing_inbound_id_is_named_in_status_and_line`; `tests/test_host_store.py::test_sweep_removes_old_stage_dirs_only`, `::test_sweep_removes_old_tmp_files_only` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G1 (R8 exemption) | `tests/test_sync.py::test_gpu_unavailable_is_recorded_without_failing_pass` (`gpu_status_unavailable`); `no_gpus` in a sync pass | unit test | `gpu_status_unavailable` passes (2026-11-10, hub, Python 3.12); `no_gpus` not verified: no test, and no node source reports it today (§13 row 9) |
| G1 (old node) | `tests/test_sync.py::test_old_node_hello_and_git_status_give_nulls`, `::test_old_node_stand_in_answers_like_the_old_node`, `::test_sync_pass_against_old_node_records_protocol_1`, `::test_mcp_nodes_after_old_node_pass` (old-node stand-in `tests/oldnode.py`, integration item 2); live: one pass against the node code installed on node1 | unit test; live check | unit tests pass (2026-11-10, hub, Python 3.12); live check not verified: no node contact in this review |
| G1 (error codes) | `tests/test_sync.py::test_transport_error_without_code_attribute` (a local stub exception class without `code`, R4), `test_transport_error_code_attribute_used`, `test_invalid_node_code_replaced`, `test_non_code_board_error_becomes_source_error` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G1 (git key) | `tests/test_sync.py::test_git_status_tree_key_and_trm_fallback` (`tree` first, `trm` fallback, `research` ignored; R5) | unit test | passes (2026-11-10, hub, Python 3.12) |
| R9 | `tests/test_sync.py::test_missing_host_json_one_line_error`, `tests/test_web.py::test_cli_web_serve_without_host_json` (exact line for a missing file), `tests/test_doctor.py::test_invalid_host_json_one_line_error` (`sync`, `web serve`: one line with the reason, §13 row 3) | unit test | passes (2026-11-10, hub, Python 3.12) |
| G2 | `systemd-analyze --user verify` on the filled templates; live: `rb service install`, timer runs, journal shows passes | manual; live check | verify passes (2026-11-10, hub, systemd 255) on the current text generated by `service.units()` into a temporary directory, with and without the `RB_HOST_ROOT` line; nothing installed; live check not verified: no node contact in this review and the units were not installed |
| G2 (timer after a failed pass) | Live: with the agent empty, check that `rb-sync.timer` keeps starting passes after each failed one (`systemctl --user list-timers rb-sync.timer`) | live check | not verified: units not installed in this review |
| G3 | `tests/test_host_tools.py::test_poll_returns_sync_stored_items_exactly_once`, `test_legacy_records_not_redelivered`, `test_poll_returns_stored_items_when_node_unreachable`, `test_poll_partial_fetch_returns_appended_items`; `tests/test_ledger.py::test_concurrent_claims_are_disjoint` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G4 | `tests/test_host_tools.py::test_send_message_writes_masked_outbox`, `test_ledger_line_never_contains_body`; `tests/test_host_store.py::test_store_outgoing_retry_same_body_ok_different_body_refused`, `::test_store_outgoing_retry_survives_pattern_change` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G5 | `tests/test_host_tools.py::test_nodes_status_from_sync_file`, `test_thread_rows_have_body_fields` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G6 | `tests/test_web.py::test_all_routes_render`, `test_pending_job_shows_command_and_no_form`; `tests/test_threads.py` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G7 | `tests/test_web.py::test_wrong_host_refused`, `test_only_get_and_head`, `test_path_traversal_is_404`, `test_non_loopback_bind_refused` (the message names `ssh -N -L PORT:127.0.0.1:PORT <hub>`, R7), `test_wildcard_bind_refused`; live: page through `ssh -L` from the laptop | unit test; live check | unit tests pass (2026-11-10, hub, Python 3.12); live check not verified: the page was not started in this review |
| G8 | `tests/test_host_tools.py::test_exact_tool_set` (unchanged) | unit test | passes (2026-11-10, hub, Python 3.12) |
| G9 | `tests/test_demo_dashboard.py::test_demo_pages_200_and_seeded_thread` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: body in a log | `test_ledger_line_never_contains_body`, `tests/test_sync.py::test_status_file_has_no_body_or_text`, `tests/test_web.py::test_access_log_has_route_names_only` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: withheld | `tests/test_web.py::test_body_remasked_at_render`, `tests/test_host_tools.py::test_poll_remasks_stored_body`, `test_poll_masks_stored_attachment_names`, `test_send_message_writes_masked_outbox`; `tests/test_host_store.py::test_store_outgoing_masks_and_records` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: page writes or connects | `tests/test_web.py::test_page_opens_no_connection`, `test_page_writes_no_file`, `test_no_http_client_or_mcp_import` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: escaping | `tests/test_web.py::test_body_and_fields_escaped_and_cleaned`, `test_security_headers` (allowed `href` values: the four navigation routes and `/thread/<id>`) | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: approval | `test_exact_tool_set`; `test_pending_job_shows_command_and_no_form` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: secret or socket path in a unit | Read the filled unit text: no `SSH_AUTH_SOCK`, `IdentityFile`, key path or passphrase; `tests/test_service.py::test_units_use_absolute_rb_path_and_no_ssh_auth_sock`, `::test_unit_text_matches_sync_design` | manual; unit test | text read in `rb_host/service.py` `units()` on 2026-11-10 (only `RB_HOST_CONFIG` and `RB_HOST_ROOT` lines); unit tests pass (2026-11-10, hub, Python 3.12) |
| Anti-goal: node connects to the hub; node change | `git diff --stat -- rb_node/` empty for this work; no new listening socket on the node side | manual | checked 2026-11-10: `git diff --stat ef42659 claude/ro-hub-sync -- rb_node/` is empty (the sync branch changed no node file; the integration changed only the `ak_duplicate` message in `rb_node/doctor.py`); the listening-socket part was not checked separately |

## 11. Decided by the user

- 2026-11-05: the hub is the Linux server.
- The runtime environment is managed by uv.
- Goals stated for this review (2026-11-10): material is gathered on the hub; session conversations are visible on a page served by the hub; SSH transport with automatic update after the first link; experiment handling following autoresearch practice; the project is not fixed to trm; flexible MCP synchronisation; scripts simplified so that the README is enough.

## 12. My calls (user to check)

Coordinator rulings after the design audit (kept in the gitignored review working directory, not in this repository; the points are listed below), approved by the coordinator on 2026-11-10, not by the user. Points this document earlier left open for the coordinator now refer to them:
- R1. Agent sockets: two orders as in setup design §7.4. Keys are loaded only into runtime-directory sockets; connecting (`NodeClient`, and so the units here) may also use `$SSH_AUTH_SOCK` (§6.10).
- R2. Host key comparison is deferred as in setup design §6.2 step 5; the step-count goal of that design is "at most 17".
- R3. One sync pass runs `hello`, poll, `git_status` on one connection, then the due board sources (§6.2); this branch may edit `rb_host/store.py`, `rb_host/board.py` and `scripts/demo_dashboard.py` (§13 rows 1 and 2). Contract §1.3 is superseded on the order and the file list.
- R4. Error codes are read with `getattr(exc, "code", None) or "transport"`; the missing-attribute test uses a local stub exception class (§5, §6.2, §10).
- R5. Git state is read from the key `tree` with fallback `trm`; a key named `research` is not accepted (§6.2 step 4).
- R6. Unit text: §6.10 is the single source. `RB_HOST_CONFIG` always; the `RB_HOST_ROOT` line only when the installing shell has it set, otherwise absent (not commented); the MCP registration printed by `rb setup` carries the same variables.
- R7. `rb web serve --bind` accepts only loopback addresses; any other value is refused with a message that names `ssh -N -L PORT:127.0.0.1:PORT <hub>` (§7).
- R8. `gpu_status_unavailable` and `no_gpus` are recorded in the status file's `board` map and do not fail a pass; transport errors, a poll error and other source errors (except `no_path`) do (§6.2).
- R9. A missing or invalid `host.json` makes `rb sync` and `rb web serve` print exactly `error: no usable host.json at <path>; run: rb setup --node NAME --host HOST --user USER` and exit 1 (§6.1). As built, the line is exact for a missing file and carries the reason for an invalid one (§13 row 3).
- R13. Accepted as written in the setup design (its §12): the extra `hello.state` key `withheld_source_set`, old-node `withheld_extra` never better than `warn`, `rb-node config set withheld_source` requiring a terminal, the filtered responder log with 14-day deletion, `withheld_hub` failing on zero patterns, `rb setup --research-root`, `rb setup --node NAME` alone on a rerun, and the releases-directory symlink swap in `node-install.sh`. None of them changes this design.

Design choices and contract defaults:
- Contract §3 item 1: the hub stores outgoing bodies under `outbox/`, masked, like inbound bodies under `inbox/`.
- Contract §3 item 2: the ten tools stay; flexibility comes from added result fields and the refined `poll`.
- Contract §3 item 3: no approval form on the page; approval stays `rb approve` in a hub terminal.
- Contract §3 item 4: unattended sync runs as systemd user units installed only when the user runs `rb service install`.
- Contract §3 item 6: `trm` naming on the wire stays; the hub's own output and status file use `tree_head`/`tree_dirty`.
- Pass order hello, poll, `git_status`, board (the contract lists git state after the board), so that the first three share one connection. Board sources keep their own connections and only due sources are fetched (half the cadence). Approved by the coordinator on 2026-11-10 (R3; §13 row 1).
- `poll` returns at most once: an item claimed by a call whose result is lost is not returned again.
- Records without `delivered` count as delivered.
- Only the stored copy of an outgoing body is masked; the node receives the body unchanged.
- `send_message` refuses an unsafe `msg_id`, an inbound record's id, and a retry whose body differs from the stored one.
- `nodes` always returns `status` (with `synced: false` when no file exists); `test_nodes` is updated. Stale after 900 s.
- The MCP `thread` tool stays one level; the page uses connected components.
- Board failure keeps previous items with their old `fetched_at`, so they show as stale.
- Page details: port 8767, refresh 30 s (60 s on one thread), 500 rows on `/threads`, bodies cut at 20 000 characters, query strings ignored, no `/sync` route (freshness is on `/` and `/nodes`).
- Non-loopback bind is refused (only loopback addresses; `127.0.0.1` in this branch), with the `ssh -N -L` command in the message, until the user answers open question 6 (R7).
- Units: no `PrivateTmp`/`ProtectSystem`; `OnActiveSec=60`; `RB_HOST_CONFIG` (absolute path of the loaded `host.json`) always written, `RB_HOST_ROOT` only when set in the installing shell, with that value made absolute, and otherwise absent (R6; §13 row 7); `ExecStart` is the `rb` of the environment that ran the install.
- A gpu source that reports `nvidia-smi not found` or `nvidia-smi failed` gets the code `gpu_status_unavailable`; that code and `no_gpus` are recorded but do not fail the pass (R8, departing from contract §1.3); open question 7.
- One staleness rule (§6.8, 900 s from `last_ok_at`) for `nodes`, the page and `rb doctor`.
- Board error strings that are not codes become `source_error`; node codes that are not codes become `invalid_code`.
- A pass writes a provisional status file (`stage: running`, `error: incomplete`) before it connects.
- The demo translates its own `Host` and `Origin` values to the 8765 names the vault page modules accept (brief).

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | Pass order hello, poll, `git_status`, board, while contract §1.3 lists board refresh before git state. Approved by the coordinator on 2026-11-10 (R3). | One more connection per pass if the contract order is kept (`git_status` would need its own connection after the board). | §6.2, §12 |
| 2 | Files outside the contract §1.3 list are changed: `rb_host/store.py` (`store_outgoing`, unique stage directory, `sweep_stage_dirs`), `rb_host/board.py` (two changes, §5) and `scripts/demo_dashboard.py` (G9). Approved by the coordinator on 2026-11-10 (R3). | Without `store.py` there is no outbox and the concurrent-poller `FileNotFoundError` stays; without `board.py` a failed source shows empty items and Linux shows two `missing` vault sources; without the demo change G9 is dropped. | §5, §9, brief §2 |
| 3 | One `host.json` helper for every `rb` command (`configure.host_cfg`, `configure.host_json_error`): the R9 line is exact for a missing file; an unreadable or invalid file adds the reason in parentheses. `rb sync` also exits 1 with one `error:` line when `host.json` lists no node or `--node` is unknown (§6.1). | A script matching the exact R9 text misses the invalid-file case; a hub with an empty `nodes` map reports a failed sync instead of doing nothing. | integration item 4; commits 5ec5f74, e4484c4; `tests/test_doctor.py::test_invalid_host_json_one_line_error`, `tests/test_sync.py::test_run_no_nodes_configured_fails` |
| 4 | The hub reads the git state from `tree`, then `trm` (R5); node 0.2.0 still sends only `trm`, so `tree` is read from no node today (§6.2 step 4). A result with neither key gives `tree_head` null and no `git_error`. | A node that renames the key to anything other than `tree` shows a null head without an error code, so the change is noticed only on the page. | ruling R5; commit bdbc15c; `tests/test_sync.py::test_git_status_tree_key_and_trm_fallback` |
| 5 | The status file and the output line gain `rejected_ids` (at most 10 valid ids); an inbound id that belongs to an outgoing or job record is counted as rejected and never acknowledged; counts stored before a failure are kept (§6.2 step 3, §6.3). | Ids (not text) of refused items stay in `sync/<node>.json`; a clashing id is refused on every pass until someone removes it by hand on the node. | integration items 11, 14; commit 4df6e3e; `tests/test_sync.py::test_failure_after_storing_keeps_the_counts`, `::test_clashing_inbound_id_is_named_in_status_and_line` |
| 6 | `provenance.json` gains `body_sha256`, the SHA-256 of the body as sent (before masking); a retry with the same `msg_id` is compared by that hash, so a pattern file changed between the two calls does not refuse a true retry; older records fall back to the masked text. Outbox files are mode 600 (§6.5). | The hub keeps a hash of the unmasked body: anyone who can read the data root and guesses a whole body, including one with withheld lines, can confirm the guess. The masked text alone would not allow that. | commit e4484c4; `tests/test_host_store.py::test_store_outgoing_retry_survives_pattern_change`, `::test_store_outgoing_files_are_mode_600` |
| 7 | `rb service install` writes `RB_HOST_ROOT` as an absolute path (not the shell's exact text), refuses paths with whitespace or `%`, an interval below 30, a port outside 1 to 65535 and a missing `host.json`, and honours an absolute `XDG_CONFIG_HOME` (§6.10). | A data root or checkout whose path contains a space cannot be used by the units; the user moves it or installs the units by hand. | commits d4f54cc, d2de29f; `tests/test_service.py::test_install_refuses_rb_host_root_with_space_and_absolutizes`, `::test_install_refuses_without_host_json` |
| 8 | Every page has one navigation line with links to the fixed routes `/`, `/threads`, `/jobs`, `/nodes`; the header test allows exactly those four `href` values plus `/thread/<id>` (§6.6, §7). The text said `/thread/<id>` links were the only URL attributes. | None for exposure (fixed internal routes, no data); a later route must be added to the test's allowed set. | integration item 13; commit 791cc60; `tests/test_web.py::test_security_headers`, `::test_body_and_fields_escaped_and_cleaned` |
| 9 | Of the two board codes exempted by R8, only `gpu_status_unavailable` occurs: the node's `gpu_status` returns an empty list (an `ok` source) when it reads zero GPUs, and `no_gpus` is a `job_submit` error, so the `no_gpus` exemption in `sync.TOLERATED` is never reached today. `hello` is read through `normalize_hello`, so a non-object result gives `closed`, not `internal` (§6.2). | None now; if a later node reports `no_gpus` from `gpu_status`, it is tolerated as R8 intends, untested. | ruling R8, R10; commit ceb27f9; `tests/test_sync.py::test_gpu_unavailable_is_recorded_without_failing_pass` |
| 10 | Board results that do not fail a pass are exactly `no_path`, `gpu_status_unavailable` and `no_gpus` (`sync.TOLERATED`), besides `ok` and `skipped`; every other board code fails the pass at stage `board` (R8, §6.2). | A node source that fails for a lasting reason other than these three keeps every pass failed and `stale` true, although the link and the poll work; `node_seen_at` still shows the link. | ruling R8; commit bdbc15c; `tests/test_sync.py::test_board_failure_fails_pass_except_no_path`, `::test_gpu_unavailable_is_recorded_without_failing_pass` |
| 11 | `rb web serve --bind` accepts only `127.0.0.1` (R7 allows loopback addresses; `::1` would need an IPv6 server class, not built); any other value exits 1 with one line naming `ssh -N -L PORT:127.0.0.1:PORT <hub>` before `host.json` is read (§6.1, §7). | A user who wants `::1` or `localhost` must pass `127.0.0.1`; nothing else changes. | ruling R7; commit 598fe56; `tests/test_web.py::test_non_loopback_bind_refused`, `::test_wildcard_bind_refused` |
| 12 | One staleness rule, 900 s since `last_ok_at` (`threads.STALE_AFTER_S`), read through `threads.read_status` / `threads.summary` by the MCP `nodes` tool, the page and `rb doctor` (`doctor.STALE_SECONDS` is the same constant); the doctor adds "never finished" for a pass left at `stage: "running"` longer than 900 s (§6.8). | With a timer interval above 300 s every node shows as stale between passes; the interval and the rule must change together. | integration item 3; commits eca6688, ceb27f9; `tests/test_host_tools.py::test_nodes_status_from_sync_file`, `tests/test_doctor.py::test_offline_sync_staleness_is_900_seconds` |

## 14. Left to the builder

Page layout and style, column order, wording of banners and empty states, the exact temporary-file names, the order of keys in JSON output, and helper names not listed in the brief.

## 15. Open questions

1. Does the hub have other user accounts, and how is the page protected from them? Decided 2026-11-10 by the user: one-time access key exchanged for a session cookie (§6.6a). The residual risk and the possible later Unix-socket forward are in §6.6a.
2. Should `poll` be at least once instead of at most once (a session may then see an item twice after a lost result)? Default: at most once.
3. May the outgoing copy be stored unmasked so that it can serve as a resend source? Default: masked.
4. Timer interval: 300 s? Default: 300 s.
5. Should the unit run from a release checkout (or a `uv tool install` of a tagged commit) instead of the development checkout's environment? Default: the environment that ran `rb service install`, with a warning for worktrees.
6. Is a non-loopback bind wanted at all? Default (coordinator ruling R7): refused (only loopback addresses; in this build only `127.0.0.1`); the SSH forward is the access path.
7. Should a node without a working `nvidia-smi` be exempt from failing the pass on the gpu source (so `stale` reflects the link and the poll only)? Default (coordinator ruling R8): yes, `gpu_status_unavailable` and `no_gpus` do not fail the pass; the user may restore contract §1.3's rule, under which every failed source other than `no_path` fails the pass.
