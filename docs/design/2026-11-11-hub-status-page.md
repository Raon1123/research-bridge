# Status page on the hub (sessions and experiment progress in one place) — design

Date: 2026-11-11 · Status: draft, not user-approved; built: `share.snapshot`, route `/status`, `rb share build|serve` and `share_serve.py` archived (branch `claude/hub-status-page`, PR 58, not merged) · Author: research-bridge audit session (2026-11-11) · Code: `rb_host/share.py`, `rb_host/web.py`, `rb_host/cli.py`, `tests/test_share.py`, `tests/test_web.py`; archived: `rb_host/share_serve.py` · Data: none written (the page reads `board/`, `ledger.jsonl`, `inbox/` and the optional files named in `host.json` `share.*`)

Status history:
- 2026-11-11 draft. The user asked for the direction (§11) and said to start without questions, so the design and the build go into one change.
- 2026-11-11 built on branch `claude/hub-status-page`: steps 1–3, 5 and 6 of §9. Step 4 (the read-only check against the real data root) was not run: the building session was not allowed to read the hub data root. Rulings in §13.
- 2026-11-11 open question 1 (where the session half comes from) answered by the user on 2026-11-11: the hub asks each node about the sessions that run there and stores them. Design and build: [Sessions on the nodes, collected on the hub](2026-11-11-node-sessions.md) (branch `claude/node-sessions`). The body below is left as it was.
- 2026-11-11 step 4 run by the coordinating session: the page renders from the real data root (five sections, no error line), the queue and GPU numbers agree with the board cache, the per-day table has 8 rows, nothing was written. The same check found one difference from `/nodes` (ruling 12 in §13), fixed with a test.

Replaces the serving half of [the shared status page design of 2026-11-06](2026-11-06-shared-status-page.md): its snapshot reducers stay, its separate server and its files do not.

## 1. Intent

The shared status page of 2026-11-06 answers "what did I work on, and how are the experiments going" on one screen. It was built for the time when the hub was the laptop: `rb share build` writes a snapshot on the machine that holds the session-calendar files, and `rb share serve` (port 8766) shows it to the user's other devices on the local network.

Since 2026-11-05 the hub is a Linux server and the user reads bridge state on the hub page (`rb web serve`, port 8767, reached from other devices through an SSH local forward). The share page was never run with real data (steps 2, 5 and 6 of its design are open), its server accepts any bind address and checks no `Host` header, and on the hub nothing calls it. The 2026-11-11 audit asked whether to keep it for the laptop or archive it (row U3 of `docs/issues/2026-11-11-audit.md`). The user's answer: see it combined here.

So the summary moves into the hub page as one more route, `/status`, which uses the access key, the `Host` check and the owner-of-socket check that every other route of that page already has.

## 2. Goals

- G1. `GET /status` on the hub page shows, for the last 7 days and today (UTC dates): the queue counts and GPU use of the nodes now, the number of pending approvals, the GPU-hours requested in the period, and one row per day with the bridge activity of that day (§8).
- G2. The page shows sessions per day and runs per day when their source files are configured (`share.calendar_sessions`, `share.runs` in `host.json`), and says in one plain line that no source is configured when they are not.
- G3. Every section names its sources with fetch time, age, and an error code or a stale mark (G4 of the 2026-11-06 design).
- G4. Rendering the page writes nothing: no file under the data root is created or changed by a request.
- G5. The queue counts are right for the state names the node reports (`jobs`, `processing`, `done`, `failed`). Before this change the reducer knew none of the first two and reported 0 queued and 0 running.
- G6. One server, one place: `rb share serve`, `rb share build` and `rb_host/share_serve.py` leave the code (archived, §9 step 5).

## 3. Non-goals

- No reader of Claude session records on the hub. Where the session half comes from on this machine is Open question 1.
- No list of single runs or job records: `/jobs` has the records, and `/runs` and `/job/<id>` belong to the experiment-records draft (`2026-11-10-experiment-records.md`). `/status` shows counts per day only and links to `/jobs` and `/nodes`.
- No view for other people and no export. The audience is the user (decided 2026-11-06).
- No new node operation, no MCP tool change, no ledger record kind.
- No change to `rb sync`, the systemd units or the board cache.

## 4. Anti-goals (failure even if it works)

- Withheld content, an event body, or a status word that matches a withheld pattern appears on the page.
- A request to `/status` is answered without the access-key session that `/jobs` requires.
- A string from a file or from the board cache reaches the page without HTML escaping.
- A request writes to the data root, or opens a connection to a node.
- A source that cannot be read makes the whole page fail, or is shown as a row of zeros with no error.

## 5. Constraints

- `AGENTS.md` hard rules 1, 2, 3 and 6. The MCP tool set is unchanged.
- `web.render` reads files only (`docs/design/2026-11-10-sync-and-hub-page.md` §6.6). `share.build` wrote two files and an audit line, so the page cannot call it.
- `rb_host/share.py` stays free of module-level imports of the client, the server and the board module (its present rule), so that a page request does not load `mcp`.
- The hub page goes live only when the user updates the main checkout and restarts `rb-web.service` (`docs/HANDOFF.md`). A session does not restart it.
- The formats of the session and run files are still assumed (2026-11-06 design §8); no real file of either kind exists on the hub.

## 6. Architecture

```
hub (one process: rb web serve, loopback 8767)
──────────────────────────────────────────────────────────────────────
board/<node>_queue.json ─┐
board/<node>_gpu.json   ─┤
board/<node>_events.json ┤   share.snapshot(cfg)        web._status_page
ledger.jsonl ────────────┼──► (pure: reads, reduces, ──► (tables; every string
inbox/ event bodies ─────┤    withheld check; no write)   through _t and _cell)
share.calendar_sessions ─┤
share.runs (optional) ───┘
```

No connection is opened. The board cache is filled by `rb sync` as before.

### 6.1 Interfaces

| Name | Kind | Notes |
|---|---|---|
| `GET /status` | read | New route of the hub page, same checks as `/jobs`. Linked from the navigation line of every page. Refreshes every 60 s. |
| `share.snapshot(cfg, days=7, today=None)` | internal | Returns the snapshot dictionary of §8. Reads only. Never raises for an unreadable or malformed source: the source gets an error code. |
| `rb share build`, `rb share serve` | removed | Archived with `rb_host/share_serve.py` (§9 step 5). |
| `host.json` `share.calendar_sessions`, `share.calendar_status`, `share.runs`, `share.labels` | config, kept | Same keys and meanings; they now feed `/status`. |

The MCP tool set is unchanged.

## 7. Security

- **Access.** `/status` is served by the same handler as the other routes: loopback bind only, allowed `Host` values only, client socket owned by this account, access-key session required. A test requests `/status` without a session and expects the refusal `/jobs` gives.
- **Inputs.** The board cache was reduced and checked against the withheld patterns when `rb sync` wrote it; the snapshot checks every kept string again. The optional session and run files are named by the operator in `host.json`, but their content is treated as untrusted: wrong types are skipped, strings are cleaned (`jobs.clean`) and cut, a withheld hit drops the item and adds to a `dropped` count shown on the page.
- **Event bodies.** The per-day table counts failed `job_finished` events. The status is read through the masked body reader the `/jobs` page uses; only the classification (failed or not) is kept, no text from the body is shown.
- **Output.** Every cell goes through `_t` (clean, withheld re-check) and `_cell` (HTML escape). Error codes shown are limited to `^[a-z_]{1,40}$`; anything else is shown as `bad_error_code`.
- **Labels.** Rule in §8. The 2026-11-06 rule ("a label not on the allowlist is shown as `other`") was written for a page other people on the local network could open; this page is behind the access key and already shows thread subjects and job notes.
- **Removed surface.** `rb share serve` could bind any address and checked no `Host` header; it is gone.

## 8. Data and ledger

No ledger record kind or field changes. Nothing is written under `share/`; the directory is no longer part of the hub data.

Snapshot (returned by `share.snapshot`, never stored):

```json
{"schema_version": 2, "built_at": "...", "period": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
 "sources": [{"id": "node1:queue", "fetched_at": "...", "ok": true, "error": null, "stale": false}],
 "sessions": {"per_day": [{"date": "...", "lane": "hub", "project": "<label>", "count": 0, "active_h": 0.0}],
              "totals": {"sessions": 0, "routines": 0, "active_h": 0.0, "cost_usd": null}},
 "experiments": {"queue": {"queued": 0, "running": 0, "done": 0, "failed": 0, "other": 0, "pending_approvals": 0},
                 "gpu": {"in_use": 0, "total": 0, "gpu_hours_period": 0.0},
                 "runs_per_day": [{"date": "...", "project": "<label>", "started": 0, "finished": 0, "failed": 0}],
                 "tracks": [{"track": "<label>", "stage": "S5", "last_event_age_s": 0}]},
 "activity": [{"date": "...", "submits": 0, "cancels": 0, "approved": 0, "finished": 0, "failed": 0,
               "sent": 0, "received": 0}],
 "dropped": 0}
```

The numbers are layout examples, not data.

| Part | Source | Rule |
|---|---|---|
| `queue` | board cache `<node>:queue`, summed over nodes | `jobs` and `queued` and `pending` count as queued; `processing` and `running` as running; `done` and `finished` as done; `failed` and `error` as failed; any other state name adds to `other`. |
| `pending_approvals`, `gpu_hours_period` | ledger job records | as before |
| `gpu` | board cache `<node>:gpu` | in use = utilization or memory used above 0 |
| `tracks` | board cache `<node>:events` | as before (stage codes `S0`–`S8` only) |
| `activity`, one row per day of the period, newest first | ledger and stored event bodies | `submits`, `cancels`: job records by `op` and the date of `created`. `approved`: job records by the date of `approved_at` (a refused approval has none). `finished`: `job_finished` events by node time (`threads.node_time`); `failed`: those whose status is `failed`, `error` or `crashed`. `sent`, `received`: message records that are not events, by direction and date. |
| `sessions` | file at `share.calendar_sessions` | as before, except the lane: `laptop`, `hub`, `server` or a configured node name is kept, anything else is `other`. |
| `runs_per_day` | file at `share.runs` | as before |
| `cost_usd` | file at `share.calendar_status` | shown when present |

Label rule (project and track labels): a non-string is `other`; a string with a withheld hit drops the item; when `share.labels` is a list, a label outside it is `other`; when `share.labels` is not set, the cleaned label is shown (cut at 60 characters).

Page layout, top to bottom: the banners of the other pages; "Now" (queue counts, GPUs in use of total, pending approvals with a link to `/jobs`, GPU-hours requested in the period, a link to `/nodes`); "Per day" (the activity table); "Sessions"; "Runs"; "Stages" (only when there is a track); "Sources"; the dropped count when it is above 0.

Relation to the experiment-records draft: when its run records exist on the hub, they replace the `share.runs` file as the source of "Runs", and the day rows link to `/runs`. Until then "Runs" has no source on the hub.

## 9. Scope of this phase

1. `share.snapshot`: split the reading and reducing out of `build` into a function that writes nothing; queue state names (G5); `other` count; lane rule; label rule; schema version 2. Tests first.
2. `activity` rows from the ledger and the event bodies.
3. `web.py`: route `/status`, the page, the navigation link; tests for content, escaping with an HTML-special and a withheld-pattern payload, the no-source lines, a broken source, the access refusal, and no write under the data root.
4. Read-only check on the hub against the real data root through `web.render` (no serving, no restart): the page renders, the queue and GPU numbers agree with `/nodes`, and no `share/` directory appears.
5. Separate commit: remove `rb share build|serve`, `build`, the audit line and the tiers; move `rb_host/share_serve.py` and the tests that only covered it to `docs/99_Archive/shared-status-page/` with a row in the archive index.
6. Documents: this design's index row, a dated status line on the 2026-11-06 design, `docs/session-dashboard.md` (route list), the sync-and-hub-page design (route list), `AGENTS.md` (layout, data list, the "open no connection" command list), both hub manuals (English and Korean), audit row U3, triage row 39, `docs/HANDOFF.md`.
7. **User:** after the merge, the post-merge step of `docs/HANDOFF.md` (update the main checkout, restart `rb-web.service`); then open `/status`.

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_web.py`: `/status` content from a seeded data root | unit test | pass (`test_status_page_content`, `test_status_link_on_every_page`, `test_status_shows_cost_when_its_file_is_configured`) |
| G2 | `tests/test_web.py`: no-source lines; `tests/test_share.py`: reducers with fixture files | unit test | pass (`test_status_says_when_no_source_is_configured`; `test_all_sections_present`, `test_snapshot_lane_rule`, `test_snapshot_label_rule_without_allowlist`, `test_snapshot_activity_rows`) |
| G3 | `tests/test_web.py`: a missing and an unparseable board file show an error code, not zeros alone | unit test | pass (`test_status_broken_board_files_show_error_codes`, `test_status_unreadable_ledger_shows_its_error_beside_the_numbers`; `tests/test_share.py` `test_snapshot_never_raises_for_broken_sources`, `test_snapshot_error_codes_are_filtered`, `test_stale_and_failed_sources_marked`) |
| G4 | `tests/test_web.py`: the data root tree is identical before and after a request; step 4 on the real data root | unit test, live check | unit test pass (`test_status_writes_nothing`, `test_page_writes_no_file` with `/status` in its route list; `tests/test_share.py` `test_snapshot_writes_nothing`); live check pass on 2026-11-11 (coordinating session, `web.render` and `share.snapshot` against the real data root, nothing served): the file list, sizes and modification times of the data root were the same before and after, and no `share/` directory exists |
| G5 | `tests/test_share.py`: `jobs` and `processing` counted; unknown state in `other`; step 4 compares with `/nodes` | unit test, live check | unit test pass (`test_queue_states_of_the_node_are_counted`, `test_snapshot_counts_node_queue_states`); live check pass on 2026-11-11 (coordinating session, `web.render` and `share.snapshot` against the real data root, nothing served): queued, running, done and failed equal the sums of the board cache files (the total is above 0, `other` is 0), and GPUs in use and total agree |
| G6 | `rb share` is not a command; the test that pins the CLI command list, if any | unit test | pass (`tests/test_share.py` `test_share_is_no_longer_a_command`; no test pins the command list; the three host.json tests of `tests/test_doctor.py` no longer list `rb share`) |
| Anti-goal: escaping, withheld | `tests/test_web.py`: HTML-special and withheld-pattern payload in a label, a node error and an event status | unit test | pass (`test_status_escapes_and_masks`; `test_security_headers` with `/status` in its route list) |
| Anti-goal: access | `tests/test_web.py`: `/status` without a session is refused like `/jobs` | unit test | pass (`test_status_needs_a_session_like_jobs`, `test_every_protected_route_needs_a_session`, `test_wrong_host_refused`) |
| Anti-goal: no connection | `tests/test_web.py`: no node client, `jobs.connect` or subprocess on `/status` | unit test | pass (`test_page_opens_no_connection` with `/status` in its route list; `tests/test_share.py` `test_no_network_client_imported`) |
| Snapshot failure | `tests/test_web.py`: an exception in the snapshot gives one error line and no exception text | unit test | pass (`test_status_snapshot_failure_gives_one_error_line`) |
| Page in the browser | open `/status` after the post-merge step | manual (user) | not run |

## 11. Decided by the user

- 2026-11-06: the audience of the status summary is the user's own devices only.
- 2026-11-11, asked whether the shared status page stays as a laptop-only tool or goes to the archive: "여기에서 합쳐서 보는게 좋지 않을까 싶네" (better to see it combined here).
- 2026-11-11: "질문 없이 바로 시작해. 이 repo에 대한 소유권을 가지고 있으니 자유롭게 수정하고, 만들 수 있게 해라" (start without questions; the session owns the repository and may change and build freely).

## 12. My calls (user to check)

- "Here" is read as the hub page on port 8767, and "combined" as one more route of that page, not a second server.
- `rb share build`, `rb share serve` and `share_serve.py` are archived in the same change, in a commit of their own so that it can be reverted alone. A laptop that still wants the old page can run it from a commit before this change.
- The snapshot is computed per request and never stored. The inputs are small files; the ledger is already read on every page request.
- Labels are shown when no allowlist is configured (§8), because the page is behind the access key.
- Dates are UTC days, as everywhere on the hub page. For a user in another time zone a "day" starts at a shifted hour (Open question 3).
- The per-day table sums all nodes and has no node column; `/nodes` shows each node.
- Weekly cost is shown when its file is configured (it was owner-tier only before; this page is the owner's).
- The board's "waiting on you" list is not repeated: the overview page already lists pending approvals.
- Unknown queue state names are counted as `other` instead of being ignored, so that a new state on a node shows up as a number.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | `finished` counts the events that `threads.load` treats as `job_finished` (those `/jobs` shows beside a job or under "Events whose job is not in the ledger"); a `job_finished` event without a string `job_id` is not counted. | An event without a job id is missing from the count. | `share._ledger_part` |
| 2 | `failed` is read with the masked body reader. A body whose line is blanked by a withheld hit, or that does not parse, counts as finished but not as failed. The status is compared after cleaning, in lower case. | A failed run whose event carries withheld text shows as finished only. | `share._ledger_part`, `test_snapshot_activity_rows` |
| 3 | Day of a message or event: `threads.node_time` (the node's time for inbound records with a node id, the hub's `created` otherwise), the time the thread pages show. | A day boundary differs by the clock skew between node and hub. | `share._ledger_part` |
| 4 | Every source error code, the pattern-file one included, goes through `^[a-z_]{1,40}$` and the withheld check; a hit shows `withheld` and adds to `dropped`. A missing board file is `never_fetched` (as `board.load` reports it), another read error `unreadable`. A reducer exception on one source makes that source `unparseable`. | None (stricter). | `share._error_code`, `share.snapshot` |
| 5 | A label is withheld-checked before and after cleaning; a label empty after cleaning is `other`; the allowlist is compared with the raw value. The lane of a session that is not a string is `other`; a configured node name that fails the node-name rule or the withheld check is not a lane. | A label that differs from the allowlist entry only by control characters shows as `other`. | `share._label`, `share.reduce_sessions` |
| 6 | `share.py` has its own copy of the `jobs.clean` rule instead of importing `jobs` or moving the function, so that importing `share` loads no node client and `jobs.py` is not touched. | Two copies of one rule can drift. | `share._clean` |
| 7 | A failed queue or GPU source gets an error line under "Now"; a failed ledger read gets one under "Now" (pending approvals, GPU-hours) and one under "Per day"; an unconfigured source is shown as "not configured" without a stale mark; an exception in the snapshot gives one line, "status summary unavailable". | None. | `web._status_page`, `test_status_unreadable_ledger_shows_its_error_beside_the_numbers` |
| 8 | `snapshot(days < 0)` raises `ValueError`: it is a caller error, not a source. The period has `days + 1` UTC dates (7 days and today: 8 rows). | None. | `share.snapshot` |
| 9 | Until the removal commit, `share.build` was a wrapper over `snapshot`, so that every commit passes the suite and the removal can be reverted alone. The archived tests are the versions of that commit. | None. | git history |
| 10 | When no session file is configured but `share.calendar_status` gives a cost, the page shows the cost alone, not a totals line of zeros. | None. | `web._status_sessions`, `test_status_shows_cost_when_its_file_is_configured` |
| 11 | Step 4 of §9 (render against the real data root) was not run by the building session; it is left to the user or the coordinating session. | A difference from `/nodes` on real data is found later. | this table, §10 |
| 12 | A board source whose cache file is missing is reported as `no_path` ("no path configured", no stale mark) when the node's sync status file gives that reason, as `/nodes` does; otherwise it stays `never_fetched`. Found by the live check: the events source of the real node has no path. | A source with no path is read as a fetch that failed. | `tests/test_web.py` `test_status_source_without_a_path_on_the_node_says_so`; coordinating session |

## 14. Left to the builder

- Function and helper names inside `share.py` and `web.py`, the exact column headings, the wording of the no-source lines.
- Whether the activity rows are computed in `share.py` from records handed in, or in `web.py` beside the event helpers; the rule that `share.py` does not import the board module at module level holds either way.
- Which of the existing `tests/test_share.py` cases move to the archive and which are rewritten against `snapshot`.

## 15. Open questions

1. **Where does the session half come from on the hub?** The session-calendar files exist only on the laptop. (a) The laptop copies its session list to the hub path named in `share.calendar_sessions` (the format the reducer reads is in §8 of the 2026-11-06 design and its plan). (b) A reader of this account's Claude session records on the hub; a read of those records was declined in the session of 2026-11-11, so nothing of that kind is built. Default until answered: no source; the page says so.
2. **Runs before the experiment-records design is built.** Default: no source on the hub.
3. **UTC days or local days** in the per-day table. Default: UTC.
