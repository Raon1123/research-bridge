# Unified research board (autoresearch + research-bridge) — design

Date: 2026-11-02 · Status: building (steps 3–5 done 2026-11-03; steps 1, 2, 6 wait on the user) · Author: research-bridge session "Design/postmortem templates" · Code: `rb_host/` (new `board` module and `rb board` CLI), `vault-export/dashboard/` (8765 route patch), `deploy/node.json.example` (read roots) · Data: `D:/raw/research-bridge/board/` (laptop cache)

Status history:
- 2026-11-02 draft
- 2026-11-03 building: `rb_host/board.py`, `rb board refresh|show`, `vault-export/dashboard/rb_board.py` + `server.py.board.patch`, tests (§10). Open questions answered with their defaults in code, not by the user (§13).

## 1. Intent

Research state is spread over five boards on two machines. On node1 the autoresearch framework (the server-side research loop in the `trm` working tree; GitHub remote `Raon1123/analysis_trm`, with `lab/` kept out of git) has its own observation surfaces: a research dashboard on port 8992, a static kanban on 8990 with an editor on 8991, a loop event log (`events.jsonl`), and `STATE.md`. On the laptop, the 8765 dashboard shows the paper kanban (`/portfolio`), the priorities board (`/priorities`), the session browser, and the research-bridge approval page (`/rb/pending`). To answer "what is running, what is waiting on me, what changed since yesterday", the user has to open several pages, some of them on the server.

This design adds one laptop-side board that reads all of these sources and shows them on one page, using research-bridge as the only channel to node1.

Terms used below:
- **autoresearch loop stages S0–S8**: the stage codes of the server's `AUTORESEARCH.md` (S0 session start, S1 hypothesis, S2 literature, S3 adversarial challenge, S4 preregistration, S5 run, S6 analysis, S7 writeback, S8 routing). Source: the user's private artifact "TRM Autoresearch pipeline map" (2026-10-19 snapshot).
- **observation plane**: in that map, the read-only layer (event log, dashboards, digests) that reads the record layer and never writes to it.

## 2. Goals

- G1. One page on the laptop (8765 route `/board`) shows, per source, the latest state and its age: research-bridge ledger (messages, replies, events, jobs by status), autoresearch loop events (stage, time, track), node queue counts and GPU usage, the paper kanban, and the priorities board.
- G2. Items waiting on the user appear first: `pending_approval` jobs, unanswered node replies, autoresearch items waiting on a user decision.
- G3. Every node-side value reaches the laptop only through research-bridge `read_doc` / `fetch_file` / `queue_status` / `gpu_status`, so withheld masking (hard rule 3) and the laptop re-check apply to it.
- G4. Each source shows its fetch time and whether it is stale (older than its expected cadence). A source that fails shows its error code, not old data presented as current.
- G5. The board makes no write to any source. It reads `portfolio.json` and `live.json` as they are.

## 3. Non-goals

- Merging repositories. `analysis_trm` is a public fork of a third-party codebase and does not contain the autoresearch documents (`lab/` is a gitignored symlink); research-bridge is the transport. They stay separate. What is merged is the data, on one page.
- Writing to any server document. Server registries, experiment documents, audits and reports are edited only on the server (contract §1.1). Corrections go through the intake path or a server session.
- Replacing the 8992 dashboard or the server kanban. They remain the server's operational views; this board summarises them.
- Approving jobs from the board. Approval stays on `/rb/pending` and `rb approve` (hard rule 1).
- Showing experiment values, verdicts or hypothesis status words (see §7 and Open question 1).

## 4. Anti-goals (failure even if it works)

- Withheld content, experiment values or verdict text reaches the laptop page, the cache, or a log.
- The board opens a connection from node1 to the laptop, or a second channel to node1 that bypasses research-bridge (for example a direct HTTP call to 8992 or to the `trm-research` server).
- The board is reachable from the LAN (it shows pending-job metadata, like `/rb/pending`).
- A board refresh changes a file it reads (`portfolio.json` byte layout, `live.json`, ledger).
- The MCP tool set changes as a side effect (hard rule 1 pins ten tools).

## 5. Constraints

- `AGENTS.md` hard rules 1–4 and 6. In particular: paths come from node config only (rule 4), so every new node-side source needs a read root in `node.json`, set on the node.
- Contract §1.1 (server registry is server-only), §7 (allowlisted SSH alias, argv not shell, no secrets in arguments or audit, bounded timeouts, prefer SSH stdio over daemon ports).
- The 8765 dashboard lives in the vault; changes ship as a patch in `vault-export/dashboard/` and are applied by the user (`AGENTS.md` "Ask the user before").
- `portfolio.json` is CRLF, indent 2, about 530 KB, and round-trips byte for byte through `json.dumps`; the Kanban session edits it. Read only; announce any new field to that session first.
- Server paths moved in the 2026-10-15 restructuring. The read roots in `deploy/node.json.example` still use the old names (`lab/registry/`, `lab/experiments/`, `lab/reports/`).

## 6. Architecture

```
laptop                                                        node1
──────────────────────────────────────────────                 ───────────────────────────────
8765 /board (loopback only) ◀── board cache ◀── rb board refresh ──ssh(rb-node1)──▶ rb-node serve-remote
     │                          (JSON per source)    │  read_doc / fetch_file /          │
     │                                               │  queue_status / gpu_status        ├─ lab/…/STATE.md
     ├── reads D:/raw/research-bridge/ledger.jsonl   │                                   ├─ lab/…/events.jsonl
     ├── reads portfolio.json (as is)                │                                   ├─ kanban data (path TBD)
     └── reads D:/raw/priorities/live.json (as is)   │                                   └─ scripts/queue/
```

- `rb board refresh` (laptop CLI, run by hand or by a laptop scheduled task) calls the existing host client functions, writes one JSON file per source under `D:/raw/research-bridge/board/` with `fetched_at`, `source`, `ok`, `error`, and a reduced payload. Writes use `*.part` then rename.
- The 8765 route `/board` renders those files plus the three laptop sources. It does not call SSH itself, so a page load never opens a connection.
- No new MCP tool. A Claude session that wants board data reads the cache files or calls the existing tools.

### 6.1 Interfaces

| Name | Kind | Notes |
|---|---|---|
| `rb board refresh [--node node1] [--source ...]` | internal (CLI) | Composes `read_doc`, `fetch_file`, `queue_status`, `gpu_status`. Bounded timeout per source. Exit code 0 even if a source fails; failure is recorded in that source's file. |
| `rb board show` | internal (CLI) | Prints the same summary as the page, for terminal use. |
| `GET /board` on 8765 | read, loopback only | Same loopback check as `/rb/pending`. No POST. Links to `/rb/pending` for approval. |
| `board/<source>.json` | file | Schema in §8. |

The MCP tool set is unchanged.

## 7. Security

- **Channel.** Node data comes only through `rb-node1` (forced command, `restrict`, `from=`). No direct call to 8992, 8990/8991, or the `trm-research` server.
- **Withheld.** The node applies `Withheld.mask_text` / `check_file` before sending. The laptop re-checks before writing the cache, as `store_incoming` does, and puts failures in `quarantine/`.
- **Status words.** The verdict family in the withheld patterns blanks or denies lines that contain registry status words. The board therefore shows stage codes, counts and ages, not hypothesis or experiment status words. Changing this is Open question 1.
- **Event payload reduction.** From `events.jsonl` the board keeps only `ts`, `stage`, `kind`, `track` and an id field, if they exist (field names to be confirmed, §15). Free-text fields are dropped on the laptop before caching.
- **Exposure.** `/board` answers only loopback, like `/rb/pending` after the Task 11 fix (postmortem PM-06).
- **Audit.** `rb board refresh` appends one audit line per source: time, source, bytes, sha256, result. No payload.
- **Public repository.** Paths in this repo use placeholders; the real server home and addresses stay in `private/`.

## 8. Data and ledger

Cache file `D:/raw/research-bridge/board/<source>.json`:

```json
{"source": "node1:events", "fetched_at": "2026-11-02T10:00:00Z", "ok": true, "error": null,
 "cadence_s": 1800, "items": [{"ts": "...", "stage": "S5", "kind": "monitor", "track": "ARG"}]}
```

Sources, phase 1:

| Source id | Origin | Read through | Cadence |
|---|---|---|---|
| `rb:ledger` | `D:/raw/research-bridge/ledger.jsonl` | local file | on refresh |
| `node1:queue` | node queue directory | `queue_status` | 10 min |
| `node1:gpu` | `nvidia-smi` summary | `gpu_status` | 10 min |
| `node1:state` | `STATE.md` frontmatter | `read_doc` (new read root) | 1 h |
| `node1:events` | autoresearch `events.jsonl` | `fetch_file` (new read root) | 30 min |
| `node1:kanban` | server kanban data (path TBD) | `fetch_file` (new read root) | 1 h |
| `vault:portfolio` | `portfolio.json` | local file, read only | on refresh |
| `vault:priorities` | `D:/raw/priorities/live.json` | local file, read only | on refresh |

No new ledger record kinds. The session browser is unchanged.

## 9. Scope of this phase

1. **User:** confirm the current node paths of `STATE.md`, `events.jsonl`, and the kanban data file, read on node1 or in a server session. The 2026-10-19 map lists `lab/11_governance/11_lab-root/STATE.md` and `lab/93_monitoring/…/15_research-dashboard/events.jsonl` (middle directory not recorded). These are unconfirmed.
2. **User (on node1):** add those directories to `read_roots` in `~/.research-bridge/node.json`, and update the old roots to the post-restructuring names. Update `deploy/node.json.example` with placeholders in the same change.
3. `rb_host/board.py` and `rb board refresh|show`, tests against the local subprocess node with fixture files (never node1).
4. Laptop re-check and payload reduction tests: an event line with a withheld pattern in a free-text field must not reach the cache.
5. `vault-export/dashboard/` patch for `GET /board` (loopback only), with a test like `tests/test_rb_pending.py`. The user applies it and restarts 8765.
6. Live check after Task 13 B3.

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_board.py::test_all_sources_rendered` | unit test | passes |
| G2 | `tests/test_board.py::test_waiting_on_user_first` | unit test | passes |
| G3 | `tests/test_board.py::test_node_sources_use_bridge_only` (no socket other than the fake SSH node); `tests/test_rb_board.py::test_page_load_opens_no_connection` | unit test | passes |
| G4 | `tests/test_board.py::test_failed_source_shows_error`, `test_stale_source`, `test_unconfigured_node_source_is_reported` | unit test | passes |
| G5 | `tests/test_board.py::test_sources_unchanged` (sha256 of `portfolio.json`, `live.json`, ledger before and after) | unit test | passes; also checked by hand on the real `portfolio.json` and `live.json` 2026-11-03 |
| Anti-goal: withheld | `tests/test_board.py::test_withheld_event_dropped`, `test_laptop_recheck_drops_what_node_let_through`, `test_audit_has_no_payload` | unit test | passes |
| Anti-goal: LAN | `tests/test_rb_board.py::test_get_non_localhost_is_403`; curl from the LAN address returns 403 | unit test; live check | unit passes; live not run (patch not applied) |
| Anti-goal: tool set | existing tool-set test still passes | unit test | passes today |

## 11. Decided by the user

- 2026-11-02: the goal is a unified board; follow the security rules; English; commits approved; use issues if needed; add a branch convention.

## 12. My calls (user to check)

- The board is laptop-side and reads node data only through research-bridge; no direct link to 8992 or `trm-research`.
- No new MCP tool; a CLI plus an 8765 route instead.
- Stage codes, counts and ages only; no status words (default for Open question 1).
- Refresh is pull-on-demand or a laptop scheduled task; the page never triggers SSH.
- Route name `/board` and cache directory `D:/raw/research-bridge/board/`.
- `analysis_trm` stays out of scope for code changes; the board reads its working tree's documents on node1 only.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | Node source paths have no default in code. They are set per node in `host.json` `nodes.<node>.board` (`state`, `events`, `kanban`); an unset path shows `no_path`. The node's `PathPolicy` still decides (hard rule 4). | A path typo shows as `not_found` until fixed in `host.json`. | `rb_host/board.py` `_node_paths`; `docs/manual/hub-setup.md` §5 |
| 2 | Open question 1 default: no status words. State keeps frontmatter `key: value` pairs after node masking and a laptop re-mask; events keep `ts`, `stage`, `kind`, `track`, `id`; kanban keeps card counts per column only (titles dropped). | If frontmatter carries a status word that no withheld pattern matches, it reaches the page. Narrow `reduce_state` to a key allowlist once the real keys are known. | `rb_host/board.py` reducers |
| 3 | Each node source opens its own SSH session (five per refresh). Per-source timeout is the SSH `ConnectTimeout` only; no per-call read timeout. | A hung node call blocks `rb board refresh`; the page is unaffected because it never connects. | `rb_host/board.py` `refresh` |
| 4 | Waiting-on-user list: pending jobs, then incoming replies with no outgoing message whose `reply_to` is their id, then priorities `now` tier items with `actor` user and status open, then one line per paper with open `user_action` tasks (the full task list stays on `/portfolio`). Node events need no answer. | Long list if many papers carry user tasks; at most one line per paper. | `rb_host/board.py` `load` |
| 5 | Laptop sources (ledger, portfolio, priorities) are read at page load, not cached; node sources are read from the cache only. | None for correctness; a large `portfolio.json` is parsed per page load (about 0.5 MB). | `rb_host/board.py` `load` |
| 6 | `rb board show` without `host.json` shows the laptop sources only (as the 8765 page does); `refresh` without it is an error. | — | `rb_host/cli.py` |

## 14. Left to the builder

Card layout, colour of stale markers, CLI flag names, whether `rb board show` also prints JSON.

## 15. Open questions

1. Should the board show registry status words? This needs either a withheld-policy change on the node or a separate status channel. Default: no; stage codes and counts only.
2. `withheld_source` in `deploy/node.json.example` points at a YAML file (`WITHHELD_RUNS.yaml`). YAML is treated as unparseable, so only the fallback patterns apply. Is a JSON export of that file available on the node? Default: fallback only, as today.
3. Field names in `events.jsonl` and the kanban data file. Default: keep `ts`, `stage`, `kind`, `track`, an id field; drop the rest.
4. Should the server's 8992 and 8990 pages be linked from the board? They are LAN addresses; links would expose nothing new but would not work off the LAN. Default: no links.
5. Which session owns the 8765 patch? The Kanban session edits `portfolio.json` but not `server.py`. Default: this project, through `vault-export/`, after a `ListAgents` check.
6. (found while building, 2026-11-03) The node sends only `.md`, `.txt`, `.csv`, `.json` as masked text (`rb_node/remote.py` `MASK_EXT`) and denies other unknown types (`deny_unscannable`). The autoresearch `events.jsonl` is therefore refused. Options: (a) a node-side `.json` export of recent events inside a read root; (b) add `.jsonl` to the node's masked-text types (changes hard rule 3 behaviour; line masking suits JSON lines well, one record per line). Default: none; the events source shows the node's refusal until the user picks one.
