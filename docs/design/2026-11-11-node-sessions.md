# Sessions on the nodes, collected on the hub — design

Date: 2026-11-11 · Status: draft, not user-approved; built: steps 1–5 of §9 (node operation `sessions`, `rb-node sessions`, the doctor check, the `rb sync` step and hub store, the `/status` lines, documents) merged in PR 59, merge commit 1efd9c6; steps 6 and 7 are the user's · Author: research-bridge audit session (2026-11-11) · Code: `rb_node/sessions.py` (new), `rb_node/remote.py`, `rb_node/config.py`, `rb_node/doctor.py`, `rb_node/cli.py`, `rb_host/sessions.py` (new), `rb_host/sync.py`, `rb_host/share.py`, `rb_host/web.py`, tests · Data: node `<node data dir>/sessions-cache.json`; hub `<data_root>/sessions/<node>.json`

Status history:
- 2026-11-11 draft. The user gave the direction (§11) and had said to start without questions, so the design and the build go into one change.
- 2026-11-11 built on branch `claude/node-sessions` (on top of `claude/hub-status-page`): steps 1–5 of §9. The two live rows of §10 are not verified: no real record was read. Rulings in §13.
- 2026-11-11 merged in PR 59 (merge commit 1efd9c6). The hub runs the merged code since 10:36 UTC; node1 still runs rb_node 0.2.0, so the hub records `sessions: unsupported` until the user's steps of §9 step 6. The two live rows of §10 stay not verified.
- 2026-11-11 first live answer on the real node. The user updated node1, set `sessions_dir` and ran the checks on the node console; the 10:58 UTC sync pass got an answer and wrote the hub store. The answer was `files: 1, unparsed: 1, sessions: 0, outside: 0`, and the doctor warned that the assumed record format may be wrong. The one file was not a session record: it was a command log whose name is not a session id and whose lines have other keys. No `.jsonl` file was at depth 1 or depth 3 in the last 8 days. So the directory that was set holds no session record two levels down, and the warning blamed the format for a wrong directory. The record format is still not verified: no session record was in reach of the directory that was set. Branch `claude/sessions-diagnosis` makes the answer, the doctor and `/status` tell these cases apart (§13 rows 32 to 36).

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
| `rb-node doctor` check `sessions` | internal | `ok` with counts when configured and readable; a note when unset; `warn` when the directory is missing, or when no session is listed and the answer says why: id-named files that could not be read as sessions (the format may be wrong), session-named files one level deeper or shallower (the directory is one level off), or only files that are not named like a session record (§13 row 35). |
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
- A file named like a session record (stem is a session id) with no usable time is not a session; it adds to `unparsed`.
- A `.jsonl` file whose stem is not a session id is not opened; it adds to `ignored` (§13 row 32).

**Operation result.**

```json
{"days": 8, "now": "2026-11-11T09:00:00Z", "tree": "<last path component of trm_root>",
 "sessions": [{"id": "<file stem>", "label": "lab/experiments", "start": "...", "end": "...",
               "days": {"2026-11-10": 5400, "2026-11-11": 1200}}],
 "outside": 3, "unparsed": 0, "ignored": 0, "files": 41, "deeper": 0, "shallower": 0,
 "truncated": false}
```

`files` counts the `.jsonl` files of the window at the expected depth, `unparsed` and `ignored` included. `deeper` and `shallower` count session-named files one level below and above the expected depth, by name and modification time only, and only when no session is listed and none is outside (§13 rows 33 and 34). A node installed before 2026-11-11 sends neither `ignored`, `deeper` nor `shallower`.

`sessions` holds only sessions whose `end` is within the last `days` days; `days` inside a session holds only days of that window. `tree` is cleaned and masked like a label.

**Node cache**, `sessions-cache.json` beside `node.json` in the node data directory: per file path, the size and modification time last seen, the byte offset read so far, the last time read, and the reduced values. A file that only grew is read from the offset; a file that shrank or whose first bytes changed is read again from the start. A cache that is missing, unparseable or of another schema is rebuilt. Written atomically. It holds no record text.

**Hub store**, `<data_root>/sessions/<node>.json`:

```json
{"schema": 1, "node": "<node>", "fetched_at": "...", "attempted_at": "...", "ok": true, "error": null,
 "tree": "...", "outside": 3, "unparsed": 0, "ignored": 0, "files": 41, "deeper": 0, "shallower": 0,
 "truncated": false, "skipped": 0,
 "sessions": {"<id>": {"label": "...", "start": "...", "end": "...", "days": {"2026-11-10": 5400}}}}
```

Merge rule: an id already in the store keeps its entry and takes the new `label`, the earlier `start`, the later `end`, and for each day the larger number of active seconds (the node's number for a day only grows). Ids not in the answer stay. A failed fetch keeps `sessions` and `fetched_at` and sets `ok`, `error` and `attempted_at`. Entries are not pruned (about 150 bytes each).

**`share.snapshot`.** One source row per node, `<node>:sessions`, with the state of G5. `sessions.per_day` gains rows from the store: date, lane = the node name, project = the label, count = sessions with activity on that day (a session with no gap-based activity counts on the day of its `start`), active hours. A new field `sessions.active_now`: sessions whose `end` is at most 900 s before the store's `fetched_at`, over all nodes. `outside`, `unparsed`, `ignored`, `files`, `deeper`, `shallower` and `truncated` are passed through per node (a count missing from an older store is 0).

**Page.** The "Sessions" section shows, per node, one of: "node `<name>` does not offer the sessions operation (update rb_node on the node)", "sessions directory is not configured on node `<name>` (`rb-node config set sessions_dir ...` on the node console)", an error line with the code, or the numbers. With numbers: active now, the per-day table, and when above 0 the outside count, the unparsed count ("record files the node could not read as sessions"), the ignored count (files that are not session records), a line when `deeper` or `shallower` says the node's directory is one level off, and the truncated note. The "no source configured" line of the earlier design is shown only when no node and no file source exists.

## 9. Scope of this phase

1. `rb_node/sessions.py`: scan, reduction, cache, bounds; `sessions_dir` in `rb_node/config.py`; the op in `rb_node/remote.py`; tests with record files written under `tmp_path` (fixtures labelled as the assumed format).
2. `rb-node sessions` and the doctor check.
3. `rb_host/sessions.py`: validation, merge, store; the step in `sync.run_pass`: after `git_status`, the last call on the connection, only when `hello.ops` lists `sessions`, every exception caught, a code in the status file, never a pass failure. Test a pass against a node without the operation and against one with it unconfigured.
4. `share.snapshot` and the `/status` section with the four states; the no-write test with a store present.
5. Documents: this design's index row; a dated line on the hub-status-page design (open question 1 answered); the sync design (pass steps, status field), `AGENTS.md` (layout, node and hub data lists, the node console command list is unchanged: `rb-node config set` and `rb-node sessions` need no terminal check but any command on node1 is ask-first), both node manuals and both hub manuals (English and Korean), `docs/session-dashboard.md`, `docs/HANDOFF.md` (the user's steps below).
6. **User, after the merge:** the post-merge step on the hub (`docs/HANDOFF.md`); on the node console `scripts/node-install.sh --update`, then `rb-node config set sessions_dir <the Claude projects directory of the node account>`, then `rb-node sessions` to see what would be sent and `rb-node doctor`.
7. **Verification on real data (open):** compare the output of `rb-node sessions` with what the user knows ran on the node; if id-named files are found and all of them are `unparsed`, the assumed format is wrong and §8 has to be corrected. A count in `ignored`, `deeper` or `shallower` with no session says the directory is wrong, not the format (first live answer, status history).

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_node_sessions.py`: reduction, window, label, outside count | unit test | passed: `test_plain_reduction`, `test_gap_rule_and_day_of_the_earlier_time`, `test_session_spanning_two_days`, `test_a_full_day_is_capped_at_86400_seconds_and_the_hub_keeps_it`, `test_one_line_session_counts_with_no_active_seconds`, `test_days_window`, `test_label_rules`, `test_outside_and_missing_cwd_are_only_counted`, `test_hello_lists_sessions_and_a_subprocess_node_answers` |
| G1 on real records | `rb-node sessions` on the node | live check (user) | not verified: no real record was read (§5); the first live answer (2026-11-11) reached no session record, because the directory that was set holds none two levels down (status history) |
| G2 | unset key gives `not_configured`; a path outside the directory or through a symlink is not read | unit test | passed: `test_op_unset_or_missing_directory`, `test_only_depth_two_jsonl_files_inside_the_directory_are_read`, `test_config_key` |
| G3 | merge rule, failed fetch keeps data, atomic write | unit test | passed: `test_sessions_merge_by_id`, `test_sessions_failure_keeps_the_store`, `test_sessions_from_a_configured_node_are_stored` (one file, mode 600; the write is a temporary file and `os.replace`) |
| G4 | `/status` content from a seeded store | unit test | passed: `test_status_node_sessions_content`, `test_node_sessions_rows_from_the_store` |
| G5 | the four states give four different lines | unit test | passed: `test_status_node_sessions_four_states_four_lines`, `test_node_sessions_four_states`, `test_sessions_state_follows_the_node_after_an_ok_fetch` |
| G6 | a sync pass against a node whose `hello.ops` lacks `sessions` ends ok with `sessions: unsupported` | unit test | passed: `test_sessions_unsupported_when_hello_does_not_list_it`, `test_sessions_not_configured_on_the_node` |
| G7 | `rb-node sessions` prints the op result; doctor check states | unit test | passed: `test_cli_sessions_prints_what_the_op_returns`, `test_cli_sessions_not_configured`, `test_doctor_sessions_check` |
| Anti-goal: nothing else leaves the node | a record with marker strings in its message text, branch and paths: no marker in the op result, the audit line or the cache | unit test | passed: `test_nothing_else_leaves_the_node`; hub side `test_sessions_from_a_configured_node_are_stored` |
| Anti-goal: withheld label | masked on the node; a hit injected into the answer is dropped on the hub | unit test | passed: `test_label_rules`, `test_malformed_sessions_answer_is_checked_entry_by_entry`, `test_node_store_codes_and_labels_are_checked`, `test_status_node_store_escapes_and_masks` |
| Anti-goal: bounds | a file larger than the per-call budget is finished over several calls; the result says `truncated` | unit test | passed: `test_big_file_is_finished_over_several_calls`, `test_session_and_file_bounds`, `test_old_files_are_not_opened`, `test_very_long_line_is_handled` |
| Anti-goal: silent zero | files that do not parse give `unparsed` above 0 and a line on the page | unit test | passed: `test_files_without_usable_time_are_unparsed`, `test_doctor_sessions_check`, `test_status_node_counts_lines`; for the cases of §13 rows 32 to 36: `test_file_not_named_like_a_session_is_ignored_and_never_opened`, `test_files_one_level_off_are_counted_by_name_and_time_only`, `test_level_counts_only_when_no_session_is_listed_and_none_is_outside`, `test_level_listing_shares_the_listing_bound`, the `test_doctor_*` tests of `tests/test_node_sessions.py` (one per message), `test_sessions_file_counts_are_stored`, `test_node_file_counts_are_passed_through`, `test_status_node_file_lines_only_when_above_zero` |
| Anti-goal: page writes | the data root is identical before and after `/status` with a store present | unit test | passed: `test_status_writes_nothing_with_a_node_store`, `test_snapshot_writes_nothing_with_a_node_store` |
| Whole path on node1 | after the user's steps of §9: the page shows node sessions | live check (user) | not verified: needs the user's steps of §9 step 6; the first live answer (2026-11-11) was stored on the hub but listed no session (status history) |

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
| 1 | A `.jsonl` file at depth 2 whose stem is not an id is not read but counts in `files` and `unparsed`, so a wrong file-name assumption shows as a number, not as zero sessions. | A noisy `unparsed` count if such files are normal on the node. | `rb_node/sessions.py` `collect` |
| 2 | Lines are parsed with `json.loads` up to 8 MiB (`LINE_MAX`); a longer line is read through and skipped, never held. A line in progress is always finished, so one call can read one line past the 64 MiB budget. A wall-clock bound of 20 s per call (`MAX_SECONDS`) is added to the design's bounds, because the hub client has no read timeout. | A session whose only times are on lines above 8 MiB counts as unparsed. | `rb_node/sessions.py` constants, `_read` |
| 3 | The read offset moves only past newline-terminated lines; a half-written last line waits for its newline (`tail` in the cache). | A record file whose last line never gets a newline loses that line. | `_read` |
| 4 | A gap counts only when 0 ≤ gap ≤ 300 s between consecutive times in file order; an earlier time after a later one adds no active time. `start` and `end` are the minimum and maximum. | Out-of-order records undercount activity. | `_take` |
| 5 | A session with times but no top-level `cwd`, or with a relative `cwd`, counts as `outside`. | Such sessions are never listed. | `label_for`, `collect` |
| 6 | Two files with the same id (two project directories) are one session on the node, merged by the hub's rule; the label is the more recently active file's. | Two different sessions with one id would merge. | `_merge` |
| 7 | Files whose modification time is older than the window are not opened and not counted; `files` counts record files in the window (at most 2000, newest first); `outside` and `unparsed` count within the window. | A file whose times are newer than its modification time is missed. | `collect` |
| 8 | Cache at `<mailbox_root parent>/sessions-cache.json` (the directory of `install.json`; beside `node.json` in the default layout). Keys are a hash of the path below `sessions_dir`; an entry holds sizes, offset, a hash of the first 4096 bytes, times, seconds per day and the relative label, never a `cwd` or path. A cache made for another `sessions_dir` or tree is rebuilt. A file of the same size with a new modification time is read again from the start. | One full re-read after a `touch`. | `cache_path`, `_load_cache`, `_update` |
| 9 | The window and the withheld mask are applied when the answer is built, not when the cache is filled, so a pattern added later covers cached labels. The tree root is matched both as configured and resolved. | None known. | `collect`, `tree_roots` |
| 10 | `rb-node sessions` and the doctor check do not write the cache (the design says "reads only"; the doctor never writes). | Each run reads the files again, within the bounds. | `rb_node/cli.py` `_sessions`, `rb_node/doctor.py` `_sessions_check` |
| 11 | The doctor has no "note" level: unset `sessions_dir` is level `ok` with a message saying the operation is off. | A user may miss that the operation is off. | `_sessions_check` |
| 12 | A `sessions_dir` that is not a directory answers `not_found`. | None known. | `collect` |
| 13 | On the hub a label is dropped (counted in `skipped`) when it is empty, longer than 120 characters, has a control, format or separator character, or a withheld hit. (As first built it was also dropped for an HTML-special character; the coordinating session removed that on 2026-11-11, because such characters are legal in a directory name and the page escapes every string.) The page escapes all text as well; a label in a store not written by `rb sync` is cleaned and escaped by the page's label rule. | A real directory name with one of those characters never shows. | `rb_host/sessions.py` `label_ok` |
| 14 | An answer that is not an object with a `sessions` list gives the code `bad_answer`. | None known. | `rb_host/sessions.py` `validate` |
| 15 | A hub store that cannot be read is replaced on the next good fetch; no copy is kept. | History older than the node's window is lost after a corrupted store. | `record` |
| 16 | A failed or refused fetch (`unsupported` and `not_configured` included) updates an existing store (`ok` false, `error`, `attempted_at`); without a store nothing is written. So the store always says how the last pass went. | None known. | `record_failure`, `sync._sessions_step` |
| 17 | Stored entries are checked again at each merge, so a pattern added on the hub later drops its hits from the store. | None known. | `_old_sessions` |
| 18 | The store also keeps the node's `files` count, so the page can say "N of M record files". | None known. | `record` |
| 19 | `share.snapshot` takes the state from the store, else from the status field. A node with neither ("never asked") has no source row and no line, so the old no-source line stays until a pass with this code ran. A status field `ok` with no store is the error `missing`. | None known. | `share.node_sessions` |
| 20 | The per-day rows come from the stored sessions whatever the state of the last fetch, so history stays visible beside an error line (the design's "one of" applies to the node's line only). | None known. | `share.node_sessions`, `web._status_sessions` |
| 21 | Node labels go through the page's label rule: `share.labels`, when set, turns other labels into `other`; labels are cut at 60 characters on the page. | With an allowlist set, node labels show as `other` until they are added. | `share.node_sessions` |
| 22 | `totals` stay the file source's; node numbers are per node in `sessions.nodes`. `SCHEMA_VERSION` stays 2 (the new keys `active_now` and `nodes` are additions). | None known. | `share.snapshot` |
| 23 | A node source row is stale after 900 s (three timer periods). `unsupported` is shown as "not offered by the node" and never stale. | None known. | `share.SESSIONS_CADENCE_S`, `web._status_sources` |
| 24 | An error code with a digit (allowed in the sync status file) shows as `bad_error_code` on the page, whose code pattern has no digits; asserted in a test. | A real code with a digit is hidden. | `share.ERROR_CODE` (unchanged) |
| 25 | No version change of `rb_node` (`0.2.0`, pinned by tests): the operation is announced by `hello.ops`. `hello.state` gains no field. | `rb-node doctor` cannot tell an updated node from an old one by version. | `rb_node/__init__.py` (unchanged) |
| 26 | The hub asks `days=8` on every pass; no hub command prints the store (§14, not added). | None known. | `rb_host/sessions.py` `DAYS` |
| 27 | Seconds per day are capped at 86400 in the answer: a gap goes to the day of its earlier time, so a session active through a whole UTC day could report up to 86400 + 299 s, and the hub check (at most 86400 per day) would drop it on every pass. Found by review after the first build; fixed with a test. | A full day shows at most 24 h, which is right. | `rb_node/sessions.py` `DAY_S`, `test_a_full_day_is_capped_at_86400_seconds_and_the_hub_keeps_it` |
| 28 | The hub also drops an entry whose `start` is after its `end`; `tree` is null when it fails the label check. `/status` shows a line when the hub left entries of the last answer out (`skipped` above 0). | None known. | `rb_host/sessions.py` `_entry`, `validate`; `web._node_sessions_lines` |
| 29 | Listing stops after 20000 directory entries (`MAX_LISTED`) and says `truncated`; this bound is not in §7. A label that is empty after cleaning is sent as `(unnamed)`. A record file that cannot be opened, or vanished between the listing and the read, counts as `unparsed`. | A vanished file adds 1 to `unparsed` for one call. | `rb_node/sessions.py` |
| 30 | Additions outside the design's list: the op error `not_found` (§6.1 names only `not_configured`, `denied`, `io_error`), the sync code `bad_answer`, the store field `files` (§8), the key `sessions` in the one-line output of `rb sync`, and `sessions_dir` with a note in `deploy/node.json.example`. | None known. | §6.1 and §8 above are not rewritten; this row records the difference |
| 31 | Review by the coordinating session (2026-11-11): the node module was read whole against §7 (what leaves the node, path confinement, bounds); ruling 13 was narrowed (see there); `/status` was rendered from the real data root with this code (no store yet: the section shows the no-source line, nothing written). | A missed leak or an unbounded read reaches node1 with the next node update. | this table |
| 32 | After the first live answer (2026-11-11, status history), `unparsed` is split. A `.jsonl` file at depth 2 whose name is not a session id counts in a new field `ignored` and is not opened; `unparsed` counts only id-named files that gave no usable time or could not be opened; `files` still counts both. This replaces ruling 1, which put both in `unparsed`. §8 (reduction, "Operation result", "Hub store", "Page"), §6.1 (the doctor row) and §9 step 7 were rewritten to match on 2026-11-11. | A file-name assumption that is wrong shows as `ignored`, not `unparsed`; the doctor warns on `ignored` when nothing else is found. | `rb_node/sessions.py` `collect` |
| 33 | New fields `deeper` and `shallower`: id-named regular `.jsonl` files modified inside the window at depth 3 and at depth 1, under the confinement of `_list` (resolved path inside the resolved `sessions_dir`, no symlink out). They are counted by name and modification time and never opened. A depth-2 directory that resolves to an ancestor of its depth-1 directory is not entered. | In a correct directory, id-named records of sub-sessions at depth 3 would count as `deeper`. The doctor puts the format warning first (row 35), so they cause no wrong "too high" while an id-named file is at depth 2 in the window; when none is, they do. | `rb_node/sessions.py` `_levels` |
| 34 | The level counts are computed only when the answer lists no session, `outside` is 0 and the depth-2 listing did not hit `MAX_LISTED`; otherwise both are 0. The level listing shares `MAX_LISTED` with the depth-2 listing (counted together per call) and sets `truncated` when it hits the bound. It neither reads nor writes the cache. | One more listing of depths 1 and 3 on each call while nothing is listed. | `collect` |
| 35 | Doctor order when no session is listed and none is outside: `unparsed` above 0 gives the format warning, with the `deeper` and `shallower` counts added when above 0 (id-named files at the expected depth show that the level is right); then `deeper` ("one level too high"), `shallower` ("one level too low"), `ignored` only ("probably not the Claude projects directory"); `files` 0 is `ok`, "no record file in the last N days"; otherwise `ok` with the counts (id-named files whose times are all before the window). With sessions or outside sessions the check is `ok` with the counts and the `ignored` count when above 0. The request for this change listed the level cases before the format case; the order was changed for the reason above. | When an id-named file that is not a session record sits at depth 2 of a directory one level too high, the doctor names the format first, and the deeper count with it. | `rb_node/doctor.py` `_sessions_check` |
| 36 | Hub: `ignored`, `deeper` and `shallower` go through `_count` (0 when missing or not a non-negative integer), are kept in the store and passed into the per-node entry of `share.snapshot`. Store `SCHEMA` 1 and `SCHEMA_VERSION` 2 stay (additions). `/status` shows `ignored` as a plain line and `deeper`, `shallower` as error lines that name the `sessions` check of `rb-node doctor`, each only when above 0. The fix text of the doctor check names the layout and `~/.claude/projects`. | None known. | `rb_host/sessions.py` `COUNTS`, `share.node_sessions`, `web._node_sessions_lines` |

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
