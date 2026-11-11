# Sessions on the nodes, collected on the hub — design

Date: 2026-11-11 · Status: draft, not user-approved · Author: research-bridge audit session (2026-11-11) · Code: `rb_node/sessions.py` (new), `rb_node/remote.py`, `rb_node/config.py`, `rb_node/doctor.py`, `rb_node/cli.py`, `rb_host/sessions.py` (new), `rb_host/sync.py`, `rb_host/share.py`, `rb_host/web.py`, tests · Data: node `<node data dir>/sessions-cache.json`; hub `<data_root>/sessions/<node>.json`

Status history:
- 2026-11-11 draft. The user gave the direction (§11) and had said to start without questions, so the design and the build go into one change.

Fills the "Sessions" section of [the status page on the hub](2026-11-11-hub-status-page.md), whose open question 1 asked where the session half comes from.

## 1. Intent

`/status` on the hub page shows experiment progress but has no session data: the session-calendar files exist only on the laptop. The user's answer to "where does the session half come from": the hub asks each node which Claude sessions run there, collects the answers and stores them.

A Claude session on a node leaves a record file per session in the Claude projects directory of the node account. This change lets the node reduce those files to a few numbers per session (when it started, when it was last active, how long it was active on each day, which part of the served research tree it worked in) and lets the hub fetch and keep them. No text of a session leaves the node.

## 2. Goals

- G1. A new read-only node operation `sessions` returns, for the sessions of the last N days whose working directory is inside the served research tree (`trm_root`): an id, start and last-activity times, active seconds per UTC day, and a label (the working directory relative to the tree).
- G2. The node reads session records only under one directory named in `node.json` (`sessions_dir`). The key is unset by default; unset answers `not_configured`.
- G3. `rb sync` fetches `sessions` from every node that offers it and merges the answer into `<data_root>/sessions/<node>.json`, so history accumulates on the hub beyond the node's window.
- G4. `/status` shows sessions per day, per node and per label from that store, and the number of sessions active in the last 15 minutes.
- G5. The page tells four states apart for each node: the node is too old to offer the operation, the directory is not configured on the node, the fetch failed with an error code, and the fetch worked and there are no sessions.
- G6. A node without the operation (node1 runs rb_node 0.2.0 until it is updated) does not fail a sync pass.
- G7. On the node console, `rb-node sessions` prints exactly what the operation would return, so the user can see what leaves the node; `rb-node doctor` has a `sessions` check.

## 3. Non-goals

- No session text, prompt, tool name, model name, token count or cost.
- No sessions of the hub itself. The user named the nodes; a read of the hub account's session records was declined on 2026-11-11 (Open question 1).
- No list of sessions outside the served tree: they are one number.
- No MCP tool. The ten tools stay; `sessions` is a bridge operation used by `rb sync`, as `git_status` is.
- No control of sessions (start, stop, message). The responder and `rb-node link` are unchanged.
- No change to the laptop's session calendar. The optional file source of `/status` (`share.calendar_sessions`) stays as a second source.

## 4. Anti-goals (failure even if it works)

- Any text from a session record, an absolute path, a git branch name or a file name of the node reaches the hub, the node audit log or the hub status file.
- A withheld pattern match in a label reaches the hub unmasked (hard rule 3).
- The node reads outside `sessions_dir`, follows a symlink out of it, or takes a path from the hub (hard rule 4).
- A large or growing record file makes the operation run long enough to time out the sync connection.
- A node that cannot parse its record files answers with zero sessions and no sign of a problem.
- The sync pass fails, or the status page breaks, because one node is old, unconfigured or returns malformed data.
- The page request writes the store, or the store is written by anything but `rb sync`.

## 5. Constraints

- `AGENTS.md` hard rules 1 to 4 and 6. Node code is standard library only, Python 3.8, `from __future__ import annotations`.
- **The record format is assumed.** No session record was read while designing this: the hub read was declined and node1 commands need the user's go-ahead. The assumed format (§8) comes from general knowledge of Claude Code. The operation therefore counts the files it could not use, the doctor check and the print command show the result on the node, and the live rows of §10 are "not verified".
- The sync timer of the hub runs every 300 s against a node that does not have the operation yet. The hub must ask only when `hello` lists it.
- The node gets this change only when the user runs `scripts/node-install.sh --update` on the node console, and data only after the user sets `sessions_dir` there.

## 6. Architecture

```
node                                             hub
───────────────────────────────────────────      ─────────────────────────────────────────────
<sessions_dir>/<project dir>/<id>.jsonl          rb sync (run_pass), same connection as hello/poll/git:
        │ read: top-level time and cwd only        if "sessions" in hello.ops:
        ▼                                             c.call("sessions", days=N) ──► validate, re-check
rb_node/sessions.py ── cache ──►  op "sessions" ◄──┘      │ merge by session id
  (per file: offset, per-day                              ▼
   active seconds)                               <data_root>/sessions/<node>.json
                                                          │ read only
                                                          ▼
                                                 share.snapshot ──► /status "Sessions"
```

Connections are hub to node only. The page opens none.

### 6.1 Interfaces

| Name | Kind | Notes |
|---|---|---|
| node op `sessions` (`args`: `days`, integer 1 to 31, default 8) | read | Listed in `hello.ops`. Returns the object of §8. `not_configured` when `sessions_dir` is unset; `denied` or `io_error` as other ops. Protocol number unchanged: the operation is additive and announced by `hello`. |
| `node.json` `sessions_dir` | config | Directory that holds one subdirectory per project with `<id>.jsonl` files. Unset by default. Set with `rb-node config set sessions_dir <path>` on the node console. |
| `rb-node sessions [--days N]` | internal (node console) | Prints the JSON the operation would return. Reads only. |
| `rb-node doctor` check `sessions` | internal | `ok` with counts when configured and readable; a note when unset; `warn` when the directory is missing or when files were found but none could be used. |
| `rb sync` | internal | One more step in a pass (§9). Status file field `sessions`: `ok`, `unsupported`, `not_configured` or an error code. None of them fails the pass. |
| `<data_root>/sessions/<node>.json` | file | §8. Written only by `rb sync`, atomically. |
| `GET /status` | read | "Sessions" section fed by the store (§8). |

The MCP tool set is unchanged.

## 7. Security

- **What leaves the node** is fixed by an allowlist in code: session id (the file stem, accepted only when it matches `^[0-9a-f-]{8,64}$`), ISO times, integers, and one label per session. Nothing else from a record is copied.
- **Label.** The record's working directory, made relative to `trm_root`; `.` for the tree root. A working directory outside the tree makes the session part of the `outside` count and nothing else. The label is cleaned of control characters, cut at 120 characters, and replaced by `(withheld)` when it matches a withheld pattern. The hub checks it again and drops the session on a hit.
- **Reading.** Only regular files at depth 2 under `sessions_dir` with the `.jsonl` suffix; the resolved path must stay inside the resolved `sessions_dir` (no symlink out). From each line only the top-level `timestamp` and `cwd` values are taken. Lines are never logged or returned.
- **Bounds.** Per call: at most 2000 files looked at, at most 64 MiB newly read, at most 500 sessions returned (most recently active first); a `truncated` flag says when a bound was hit. The cache makes the next call continue where this one stopped.
- **Audit.** The node audit line of the operation has the usual fields (id, op, ok, code) and nothing from the records. The hub status file holds a code only.
- **Hub side.** The answer is untrusted data: every field is type-checked, times are parsed, ids matched, labels cleaned and re-checked; an entry that fails is skipped and counted. The page escapes every string.
- **Scope of reading on the node.** The node account's session records include sessions of other projects on that machine. They are counted (`outside`), never listed. The directory is read only after the user names it in `node.json`.

## 8. Data and ledger

No ledger record kind or field changes.

**Assumed record format (to verify on the node, §10).** One file per session, `<sessions_dir>/<project dir>/<session id>.jsonl`, one JSON object per line. Most lines have a top-level `timestamp` (ISO 8601, UTC, `Z` suffix, fractional seconds allowed) and a top-level `cwd` (absolute path of the session's working directory). Some lines have neither. Files in deeper subdirectories (records of sub-sessions) are not read.

**Reduction on the node, per file.**
- Times: all top-level timestamps in file order.
- `start`: the earliest; `end`: the latest.
- Active seconds: the sum of the gaps between consecutive times that are at most 300 s, attributed to the UTC day of the earlier time. A session with one time has 0 active seconds and still counts.
- Working directory: the first `cwd` found.
- A file with no usable time is not a session; it adds to `unparsed`.

**Operation result.**

```json
{"days": 8, "now": "2026-11-11T09:00:00Z", "tree": "<last path component of trm_root>",
 "sessions": [{"id": "<file stem>", "label": "lab/experiments", "start": "...", "end": "...",
               "days": {"2026-11-10": 5400, "2026-11-11": 1200}}],
 "outside": 3, "unparsed": 0, "files": 41, "truncated": false}
```

`sessions` holds only sessions whose `end` is within the last `days` days; `days` inside a session holds only days of that window. `tree` is cleaned and masked like a label.

**Node cache**, `sessions-cache.json` beside `node.json` in the node data directory: per file path, the size and modification time last seen, the byte offset read so far, the last time read, and the reduced values. A file that only grew is read from the offset; a file that shrank or whose first bytes changed is read again from the start. A cache that is missing, unparseable or of another schema is rebuilt. Written atomically. It holds no record text.

**Hub store**, `<data_root>/sessions/<node>.json`:

```json
{"schema": 1, "node": "<node>", "fetched_at": "...", "attempted_at": "...", "ok": true, "error": null,
 "tree": "...", "outside": 3, "unparsed": 0, "truncated": false, "skipped": 0,
 "sessions": {"<id>": {"label": "...", "start": "...", "end": "...", "days": {"2026-11-10": 5400}}}}
```

Merge rule: an id already in the store keeps its entry and takes the new `label`, the earlier `start`, the later `end`, and for each day the larger number of active seconds (the node's number for a day only grows). Ids not in the answer stay. A failed fetch keeps `sessions` and `fetched_at` and sets `ok`, `error` and `attempted_at`. Entries are not pruned (about 150 bytes each).

**`share.snapshot`.** One source row per node, `<node>:sessions`, with the state of G5. `sessions.per_day` gains rows from the store: date, lane = the node name, project = the label, count = sessions with activity on that day (a session with no gap-based activity counts on the day of its `start`), active hours. A new field `sessions.active_now`: sessions whose `end` is at most 900 s before the store's `fetched_at`, over all nodes. `outside`, `unparsed` and `truncated` are passed through per node.

**Page.** The "Sessions" section shows, per node, one of: "node `<name>` does not offer the sessions operation (update rb_node on the node)", "sessions directory is not configured on node `<name>` (`rb-node config set sessions_dir ...` on the node console)", an error line with the code, or the numbers. With numbers: active now, the per-day table, and when above 0 the outside count, the unparsed count ("record files the node could not read as sessions") and the truncated note. The "no source configured" line of the earlier design is shown only when no node and no file source exists.

## 9. Scope of this phase

1. `rb_node/sessions.py`: scan, reduction, cache, bounds; `sessions_dir` in `rb_node/config.py`; the op in `rb_node/remote.py`; tests with record files written under `tmp_path` (fixtures labelled as the assumed format).
2. `rb-node sessions` and the doctor check.
3. `rb_host/sessions.py`: validation, merge, store; the step in `sync.run_pass`: after `git_status`, the last call on the connection, only when `hello.ops` lists `sessions`, every exception caught, a code in the status file, never a pass failure. Test a pass against a node without the operation and against one with it unconfigured.
4. `share.snapshot` and the `/status` section with the four states; the no-write test with a store present.
5. Documents: this design's index row; a dated line on the hub-status-page design (open question 1 answered); the sync design (pass steps, status field), `AGENTS.md` (layout, node and hub data lists, the node console command list is unchanged: `rb-node config set` and `rb-node sessions` need no terminal check but any command on node1 is ask-first), both node manuals and both hub manuals (English and Korean), `docs/session-dashboard.md`, `docs/HANDOFF.md` (the user's steps below).
6. **User, after the merge:** the post-merge step on the hub (`docs/HANDOFF.md`); on the node console `scripts/node-install.sh --update`, then `rb-node config set sessions_dir <the Claude projects directory of the node account>`, then `rb-node sessions` to see what would be sent and `rb-node doctor`.
7. **Verification on real data (open):** compare the output of `rb-node sessions` with what the user knows ran on the node; if `unparsed` equals `files`, the assumed format is wrong and §8 has to be corrected.

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_node_sessions.py`: reduction, window, label, outside count | unit test | not run |
| G1 on real records | `rb-node sessions` on the node | live check (user) | not verified: no real record was read (§5) |
| G2 | unset key gives `not_configured`; a path outside the directory or through a symlink is not read | unit test | not run |
| G3 | merge rule, failed fetch keeps data, atomic write | unit test | not run |
| G4 | `/status` content from a seeded store | unit test | not run |
| G5 | the four states give four different lines | unit test | not run |
| G6 | a sync pass against a node whose `hello.ops` lacks `sessions` ends ok with `sessions: unsupported` | unit test | not run |
| G7 | `rb-node sessions` prints the op result; doctor check states | unit test | not run |
| Anti-goal: nothing else leaves the node | a record with marker strings in its message text, branch and paths: no marker in the op result, the audit line or the cache | unit test | not run |
| Anti-goal: withheld label | masked on the node; a hit injected into the answer is dropped on the hub | unit test | not run |
| Anti-goal: bounds | a file larger than the per-call budget is finished over several calls; the result says `truncated` | unit test | not run |
| Anti-goal: silent zero | files that do not parse give `unparsed` above 0 and a line on the page | unit test | not run |
| Anti-goal: page writes | the data root is identical before and after `/status` with a store present | unit test | not run |
| Whole path on node1 | after the user's steps of §9: the page shows node sessions | live check (user) | not verified |

## 11. Decided by the user

- 2026-11-11, asked where the session half of `/status` comes from (a file copied from the laptop, or a reader of the hub account's session records): "host는 hub 쪽에서 진행한다. hub 쪽에서 각 node에서 실행되는 session이 있다면 이에 대해 조회를 하고, 모아서 저장을 하는 것이 좋겠다." (The hub hosts it. The hub should ask each node about the sessions that run there, and collect and store them.)
- 2026-11-11: optional arguments may be added to MCP tools; the ten tools and their names stay. Not used here: this change adds no tool and no tool argument.
- 2026-11-11: start without questions; the session owns the repository and may change and build freely.

## 12. My calls (user to check)

- "Sessions that run on a node" is read as the Claude sessions of the node account whose working directory is inside the research tree the node serves. Sessions elsewhere on that account are a count only.
- The directory is not read until the user sets `sessions_dir` on the node (it follows `harness_root`: unset means off). This costs the user one more command on the node console.
- What is sent per session: id, two times, active seconds per day, one relative directory label. No branch name, although it would be useful, because it is free text.
- Activity is measured from gaps of at most 300 s between record lines. A long tool run without output counts as idle.
- Runs of the responder (`rb-node respond`) are sessions like any other when their working directory is inside the tree; they are not marked.
- The hub keeps every session it has seen and does not prune.
- The fetch runs on every sync pass; the node cache keeps a pass cheap.
- "Active now" means last activity at most 900 s before the fetch, so with a 300 s timer the number can be up to 20 minutes old; the page shows the fetch time beside it.
- The session id is the record file's name. It is not secret and is needed to merge; it is not shown on the page.
- Days are UTC days, as on the rest of the hub page.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | | | |

## 14. Left to the builder

- How a line's top-level `timestamp` and `cwd` are extracted (full JSON parse or a bounded scan), as long as memory stays bounded for very long lines and nested values of the same name are not taken.
- The cache's field names, and how "the first bytes changed" is detected.
- Function names, the wording of the page lines and of the doctor messages.
- Whether `rb sessions` (a hub command that prints the store) is worth adding; not required.

## 15. Open questions

1. **The hub's own sessions.** Sessions also run on the hub. They are not collected: the user named the nodes, and a read of the hub account's records was declined. Default: left out; lane `hub` stays empty.
2. **Sessions outside the served tree.** Default: counted, not listed. Listing them would send directory names of unrelated projects to the hub.
3. **Marking responder runs.** Default: not marked.
4. **Pruning the hub store.** Default: never.
