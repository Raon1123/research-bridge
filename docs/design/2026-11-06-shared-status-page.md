# Shared research status page (session calendar + experiment progress) — design

Date: 2026-11-06 · Status: built (steps 3–4; steps 2, 5, 6 open) · Author: research-bridge session "대시보드 기획 및 제안" · Code (proposed): `rb_host/share.py`, `rb share build|serve` CLI, `vault-export/dashboard/` (one link on existing pages) · Data (proposed): `D:/raw/research-bridge/share/` (laptop snapshot)

Status history:
- 2026-11-06 draft (proposal; nothing built)
- 2026-11-06 audience decided by the user: only the user's own devices (Open question 1). Outside-viewer tier removed.
- 2026-11-06 built: rb_host/share.py, rb_host/share_serve.py, rb share build|serve, tests/test_share.py (commits e68109a, 218d60a; suite 315 passed). Steps 2, 5 and 6 of §9 still open.

## 1. Intent

The 8765 dashboard already answers most status questions for the user sitting at the laptop: the session calendar (`/session-calendar`), its run view (`session-calendar-runs.html`, fed by the server's `list_runs` / `get_run_context`), the agent-sequence view (`/agents`), the priorities board (`/priorities`), the team dashboard (`/team-dashboard`), the approval page (`/rb/pending`), and, once its patch is applied, the unified board (`/board`, design `2026-11-02-unified-board.md`).

Two things are missing:

1. **One page for "what did I work on, and how are the experiments going".** The session calendar and the experiment views are separate pages built by separate generators; there is no single summary of a week's sessions next to the state of the runs and the queue.
2. **A way to see that summary on the user's other devices** (phone, tablet, the development server's browser) **without exposing the vault.** Today 8765 binds `0.0.0.0` and serves vault files (`/md`, `/raw-file`, `/browser`, `/search`) with no login, so the only sharing mechanism is "give someone LAN access to everything". The research-bridge pages are loopback-only for that reason (PM-06).

This design proposes a **share page**: a snapshot built on the laptop from data the existing generators already produce, reduced to an allowlist of fields, and served or exported separately from 8765.

It extends the unified board rather than replacing it:

| Reused from `2026-11-02-unified-board.md` | Added here |
|---|---|
| Node data only through research-bridge; board cache `D:/raw/research-bridge/board/`; reducers (stage codes, counts, ages; no status words, Open question 1 default) | Session-calendar sources (`status.json`, per-day session counts, machine lanes) |
| `fetched_at` / stale marking per source (G4) | Run view summary (runs started / ended / failed per day, by project) |
| Loopback rule for pages that show pending-job metadata | A LAN surface for the user's other devices, separate from 8765 |
| Open question 6 (`events.jsonl` refused by the node) as a dependency | An allowlist schema that is the only thing the share page can read |

## 2. Goals

- G1. One page shows, for a chosen period (default: the last 7 days and today): sessions per day and per project, active hours, laptop vs server lanes; and for experiments: queue counts by state, GPU use, runs started / finished / failed per day by project, autoresearch stage code and age per track.
- G2. The page is built only from a snapshot file `share/snapshot.json` whose fields are on a written allowlist (§8). The renderer cannot read any other file.
- G3. A viewer of the shared page cannot reach any vault file, the ledger, `/rb/*`, or any 8765 route through it.
- G4. Each section shows its source's fetch time and a stale marker, as unified-board G4.
- G5. Building the snapshot writes nothing to any source it reads (session-calendar files, run view data, board cache, `portfolio.json`, `live.json`).
- G6. The owner view (loopback) adds the "waiting on you" list from the unified board; the shared view never contains it.

## 3. Non-goals

- Replacing the session calendar, run view, `/board` or the server dashboards. The share page links nothing back into them for outside viewers.
- Experiment values, metrics, plots, verdict or hypothesis status words. Progress is shown as counts, stage codes, durations and GPU-hours only.
- Session titles, prompts, summaries or digests. These are free text written by sessions and can contain anything; the share page shows counts and project labels only (Open question 3 covers whether titles may be shown to the owner tier).
- Authentication of 8765 itself. That is a separate problem (the vault server is LAN-open today); this design avoids depending on it.
- Any write action (approve, toggle, grade) from the share page.

## 4. Anti-goals (failure even if it works)

- Withheld content (`AGENTS.md` hard rule 3), experiment values, or status words appear in the snapshot, the page, an export, or a log.
- Sharing the page gives the viewer a path into the vault: a link, an embedded `/md` or `/raw-file` URL, or a server that also serves other directories.
- The snapshot carries pending-job details (GPU ids, budgets, config paths) to the shared tier. A count of pending approvals is the most it may show.
- A snapshot leaves the LAN: it is sent to an external service (artifact page, cloud drive, chat) or the share port is reachable from outside. The audience is the user's own devices only (§11).
- The node gets a new connection path, or the MCP tool set changes (hard rules 1 and 2).

## 5. Constraints

- `AGENTS.md` hard rules 1–4 and 6; "Ask the user before" (restarting 8765, editing vault files outside `vault-export/`).
- The 8765 server and the session-calendar generators live in the vault. This design reads their outputs; it does not change them, except for one optional link patch shipped through `vault-export/`.
- The run view's experiment data comes from the server through the `trm-research` MCP (`list_runs`, `get_run_context`; vault `session-calendar/README.md`), not through research-bridge. The share builder reads the laptop files that the run view already wrote; it makes no server call of its own.
- Node-side autoresearch events are blocked until unified-board Open question 6 is decided (`.jsonl` is refused by `MASK_EXT`). Until then the stage section shows the node's refusal.
- The repository is public: placeholders only (`<HUB_LAN_IP>`, `<NODE_HOST>`, …).

## 6. Architecture

```
laptop
──────────────────────────────────────────────────────────────────────────────
session-calendar outputs ─┐
  status.json, per-day     │
  session/lane data        │
run view data ─────────────┤   rb share build          share/snapshot.json   ┌─ owner tier: 8765 /share (loopback)
  (written by runs_view.py)├──► (read-only, allowlist ──► share/index.html ───┼─ LAN tier:   rb share serve  (port <SHARE_PORT>,
board cache ───────────────┤    reducer, withheld         (static, no JS        │               serves share/ only)
  (rb board refresh)        │    re-check)                 fetches)            └─ (no outside tier: own devices only)
priorities live.json ──────┘
```

- **Build.** `rb share build` reads the sources above, keeps only allowlisted fields (§8), runs the laptop withheld check (the same function `store_incoming` uses) over every string, and writes `snapshot.json` plus a self-contained `index.html` (data inlined, no network requests). Writes use `*.part` then rename. Run by hand or by a laptop scheduled task after `refresh.py`.
- **Owner tier.** 8765 `/share` (loopback only, same check as `/rb/pending`) renders the snapshot plus the waiting-on-you list from the unified board.
- **LAN tier.** `rb share serve --port <SHARE_PORT>` is a stdlib static server rooted at `share/` with directory listing off and only `index.html` and `snapshot.json` served. It is separate from 8765, so opening it to the LAN or a phone does not open the vault.
- **No outside tier.** The page is for the user's own devices only (§11). The LAN tier is still visible to anyone else on the same LAN, so the shared-tier field rules in §7 stay.
- No SSH from any page load or from `rb share build`. Node data enters only through `rb board refresh` (unified board).

### 6.1 Interfaces

| Name | Kind | Notes |
|---|---|---|
| `rb share build [--days N] [--tier owner\|shared]` | internal (CLI) | Read-only over sources. Exit 0 if a source is missing; the section shows `unavailable`. Exit 1 if the withheld re-check drops anything, with a count (no content) on stderr. |
| `rb share serve [--port <SHARE_PORT>] [--bind 127.0.0.1\|0.0.0.0]` | internal (CLI) | Default bind loopback; default port 8766 (`<SHARE_PORT>`). Serves exactly two files. Threaded server with a 10 s handler timeout; the page refreshes every 300 s through a meta tag; stale flags are as of build time. |
| `GET /share` on 8765 | read, loopback only | Owner tier. Patch in `vault-export/dashboard/`. |
| `share/snapshot.json` | file | Schema in §8; `schema_version` field. The owner tier is written to `share/owner/` (outside the served root); `rb share serve` refuses a root whose `snapshot.json` has `tier` other than `shared`. |

The MCP tool set is unchanged.

## 7. Security

- **Allowlist, not denylist.** The builder copies named fields from named sources. A new field in a source does not reach the page until it is added to the allowlist in code with a test.
- **No free text.** Strings allowed in the shared tier: project labels, track labels, stage codes (`S0`–`S8`), machine names as placeholders (`laptop`, `node1`), ISO timestamps, source ids, error codes. Project and track labels are checked against the withheld patterns and against a configurable label allowlist (Open question 4).
- **Withheld re-check** over every string in the snapshot before write; a hit drops the item and is counted.
- **Separation from the vault.** The LAN and outside tiers never go through 8765. The share server's root is `share/`; it rejects every other path and does not follow symlinks.
- **Pending jobs.** Shared tier: one integer (`pending_approvals`). Owner tier: the unified-board list.
- **External sends.** None. No code path publishes or uploads the snapshot.
- **Audit.** `rb share build` appends one line: time, tier, source ids, item counts, dropped count, sha256 of the snapshot. No payload.

## 8. Data and ledger

`share/snapshot.json` (shape; field names left to the builder where marked):

```json
{"schema_version": 1, "tier": "shared", "built_at": "2026-11-06T07:00:00Z", "period": {"from": "2026-10-31", "to": "2026-11-06"},
 "sources": [{"id": "calendar:status", "fetched_at": "...", "ok": true, "stale": false}],
 "sessions": {"per_day": [{"date": "2026-11-05", "lane": "laptop", "project": "<label>", "count": 0, "active_h": 0.0}],
              "totals": {"sessions": 0, "routines": 0, "active_h": 0.0}},
 "experiments": {"queue": {"queued": 0, "running": 0, "done": 0, "failed": 0, "pending_approvals": 0},
                 "gpu": {"in_use": 0, "total": 0},
                 "runs_per_day": [{"date": "2026-11-05", "project": "<label>", "started": 0, "finished": 0, "failed": 0}],
                 "tracks": [{"track": "<label>", "stage": "S5", "last_event_age_s": 0}]}}
```

The numbers above are layout examples, not data.

| Section | Source (laptop file) | Fields kept |
|---|---|---|
| Sessions | session-calendar outputs (`status.json`; per-session records used by `render.py`) | date, lane, project label, count, active hours, routine count |
| Runs | data written by `runs_view.py` | date, project label, start / end state counts |
| Queue, GPU | board cache `node1:queue`, `node1:gpu` | counts by state; GPUs in use / total |
| Stages | board cache `node1:events` (blocked, unified-board OQ6) | track, stage code, age |
| Priorities (owner tier only) | `live.json` | as the unified board |

The session-calendar and run-view file shapes in this table are assumed, not read from the laptop files; they are documented in the [plan, Global Constraints §A](../superpowers/plans/2026-11-06-shared-status-page.md) and must be verified against the real files (§9 step 2).

Weekly cost (`status.json` `cost_usd`) is owner tier only by default (Open question 5). No ledger record kinds change.

## 9. Scope of this phase

0. **User:** answer Open questions 1–2 (audience and surface). Everything after depends on them.
1. **User:** apply the unified-board patch and PM-03 files, restart 8765 (`HANDOFF.md` §Before B3 item 3). `/board` currently returns 404.
2. (open) Read the exact output files of `render.py` and `runs_view.py` (read-only) and fix the source table in §8; record any field that carries free text.
3. (done 2026-11-06) `rb_host/share.py`: allowlist reducers per source, withheld re-check, snapshot writer; tests with fixture copies of the session-calendar and run-view outputs (never the live vault).
4. (done 2026-11-06) `index.html` renderer (inline data, no external scripts) and `rb share serve`.
5. (open) `vault-export/dashboard/` patch for `GET /share` (loopback) and a link from `/board`; user applies and restarts.
6. (open) Live check: build, open owner and LAN tiers, try vault paths through the share port.

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_share.py::test_all_sections_present` | unit test | passes (2026-11-06, dev server) |
| G2 | `tests/test_share.py::test_unknown_source_field_not_copied` (add a field to a fixture; it must not appear) | unit test | passes (2026-11-06, dev server) |
| G3 | `tests/test_share.py::test_serve_only_two_files` (`/`, `/../`, `/md?…`, encoded traversal, symlink → 404); live: same paths against `<HUB_LAN_IP>:<SHARE_PORT>` | unit test; live check | unit test passes (2026-11-06, dev server); live check not run |
| G4 | `tests/test_share.py::test_stale_and_failed_sources_marked` | unit test | passes (2026-11-06, dev server) |
| G5 | `tests/test_share.py::test_sources_unchanged` (sha256 before and after) | unit test | passes (2026-11-06, dev server) |
| G6 | `tests/test_share.py::test_shared_tier_has_no_waiting_list_or_pending_details` | unit test | passes (2026-11-06, dev server) |
| Anti-goal: withheld | `tests/test_share.py::test_withheld_label_dropped`, `test_audit_has_no_payload` | unit test | passes (2026-11-06, dev server) |
| Anti-goal: leaves the LAN | `tests/test_share.py::test_no_network_client_imported` (builder imports no HTTP client); manual: share port not forwarded on the router | unit test; manual | unit test passes (2026-11-06, dev server); manual not run |
| Anti-goal: tool set | existing tool-set test | unit test | passes today |
| Extra: CLI variants | `tests/test_share.py::test_cli_build_variants` | unit test | passes (2026-11-06, dev server) |
| Extra: label allowlist | `tests/test_share.py::test_labels_not_on_allowlist_become_other` | unit test | passes (2026-11-06, dev server) |
| Extra: atomic write | `tests/test_share.py::test_snapshot_written_atomically` | unit test | passes (2026-11-06, dev server) |
| Extra: no script or external URL | `tests/test_share.py::test_html_has_no_script_or_external_url` | unit test | passes (2026-11-06, dev server) |
| Extra: robustness (G5) | `tests/test_share.py::test_bad_records_do_not_raise` | unit test | passes (2026-11-06, dev server) |
| Extra: node cache strings (G2, withheld) | `tests/test_share.py::test_node_cache_strings_are_checked` | unit test | passes (2026-11-06, dev server) |
| Extra: node names (G2, withheld) | `tests/test_share.py::test_bad_node_name_skipped` | unit test | passes (2026-11-06, dev server) |
| Extra: withheld source error (G4) | `tests/test_share.py::test_withheld_source_error_reported` | unit test | passes (2026-11-06, dev server) |
| Extra: idle connection | `tests/test_share.py::test_idle_connection_does_not_block` | unit test | passes (2026-11-06, dev server) |
| Extra: track order | `tests/test_share.py::test_tracks_order_independent` | unit test | passes (2026-11-06, dev server) |
| Extra: negative days | `tests/test_share.py::test_cli_negative_days_rejected` | unit test | passes (2026-11-06, dev server) |
| Extra: PUT response (G3) | `tests/test_share.py::test_put_has_plain_405_with_headers` | unit test | passes (2026-11-06, dev server) |

## 11. Decided by the user

- 2026-11-06: plan and propose a dashboard that can share the session calendar and experiment progress, in the manner of the 8765 pages.
- 2026-11-06: the page is for the user's own devices only, not for other people.

## 12. My calls (user to check)

- Build a static snapshot instead of a live page on the LAN. A snapshot can be checked before it is served and cannot be used to reach other routes; other people on the same LAN could still open the share port.
- Keep the shared surface off 8765 (separate port or export), because 8765 serves the vault without login.
- Reuse the unified board for node data; the share builder makes no SSH or MCP call.
- No session titles, digests or experiment values in the shared tier.
- Default period: last 7 days plus today.
- Code in `rb_host/` (this repository) rather than in the vault, so it is tested with the rest of the suite. Alternative: put the builder next to `runs_view.py` in the vault session-calendar tools.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | Input formats of session-calendar sessions/status and run-view files are assumed (no vault on the build machine); reducers tolerate missing or wrong-typed fields. | Reducers rewritten after a masked laptop sample. | Plan Global Constraints §A; this log |
| 2 | Owner tier is written to `share/owner/` (outside the served root); `rb share serve` refuses a root whose snapshot has tier other than `shared`. | None (safety). | `share.py`, `share_serve.py`, `test_shared_tier_has_no_waiting_list_or_pending_details` |
| 3 | `index.html` has no `<script>`; tables are rendered in Python with `html.escape`. | None. | `share_serve.py`, `test_html_has_no_script_or_external_url` |
| 4 | Label allowlist absent: every label is `other` (Open question 4 default kept); `rb share build` prints a hint. | User adds `share.labels`. | `share.py`, `cli.py` |
| 5 | `gpu_hours_period` is summed from ledger job records created in the period (Open question 5 default: GPU-hours yes, cost no). | Wrong source if node-side GPU-hours are wanted. | `share.py` `_ledger` |
| 6 | The audit line carries source ids (§7), not session labels or timestamps. | None. | `test_audit_has_no_payload` |
| 7 | Three tasks were implemented in parallel by subagents with disjoint files; one integration fix round (tracks wording `unavailable (<error>)`, `//` raw-path check, dropped count on stderr). | None. | Plan |
| 8 | Branch not rebased on `claude/linux-hub` (PR #38 unmerged); edits to `config.py`, `cli.py`, `configure.py` kept minimal. | A small conflict when #38 merges. | This log |
| 9 | Routines are counted in totals only (no per-day row, no active hours); run `finished`/`failed` counted on the end date, `started` on the start date; `fetched_at` of calendar and runs files is the file mtime; unset source path gives error `not_configured`, missing file `missing`. | A per-day routine row or different attribution needed later. | `share.py` |
| 10 | Whole-branch review findings fixed in one wave: no exception leaves `build` (OverflowError, OSError, non-UTF-8), node-cache `fetched_at` normalised and error codes / node names shape-checked, page rendered before either file is written, failed runs without an end date counted on the start date, `withheld:patterns` source reports a broken pattern file, newest event per track chosen by timestamp (a newest event with a bad stage drops the track), ThreadingHTTPServer with a 10 s handler timeout, request log never echoes an unknown path, own 404/405 bodies with uniform headers. | None. | Commit 218d60a, tests above |
| 11 | Parked: no `Host` header check on `rb share serve` (the LAN server is reached by IP; a check would block the intended use; exposure is counts only). | A DNS-rebinding page on a LAN device could read the shared snapshot. | This log |
| 12 | Parked: owner files stay at `share/owner/`, under the share directory; they are unreachable through `rb share serve` (exact-path allowlist, tested) and `share/` must never be served by a generic static server. | A leak if someone serves `share/` with another server. | Plan §B, this log |

## 14. Left to the builder

Visual layout (calendar strip vs table), colours, CLI flag names, exact field names in §8 marked as examples.

## 15. Open questions

1. ~~Who is the page for?~~ — decided 2026-11-06: only the user's own devices (§11).
2. **How do the devices reach it?** (a) LAN only through `rb share serve`; (b) also from outside the LAN through a VPN the user already runs to the laptop. Default: (a).
3. May the owner tier show session titles? Default: no; titles are free text written by sessions.
4. Project and track labels: show as they are, or map to public names through a label allowlist file? Default: labels pass only if they are on the allowlist; others show as `other`.
5. May the shared tier show weekly cost and GPU-hours used? Default: GPU-hours yes, cost no.
6. Unified-board Open question 6 (node events `.jsonl`): decides whether the stage section has data. Default: the section shows the node's refusal.
