# Shared status page — implementation plan (design §9 steps 3–4)

Spec: `docs/design/2026-11-06-shared-status-page.md` (binding). Design `2026-11-02-unified-board.md` and `rb_host/board.py` are the model for reducers, cache files and audit lines.

Built on a development server without the vault: the session-calendar and run-view output formats are **assumed** (see Global Constraints §A) and must be verified against the laptop later.

## Global Constraints

- `AGENTS.md` hard rules. No MCP tool added; no SSH or MCP call from any share code; node never contacted.
- Python: `from __future__ import annotations`, stdlib only in `rb_host/share.py` and `rb_host/share_serve.py`. Typing comments in the style of `board.py`.
- Public repository: placeholders only (`<HUB_LAN_IP>`, `<SHARE_PORT>`, `<NODE_HOST>`); no withheld content, no real paths, no experiment numbers in code, tests, fixtures or docs.
- Tests use fixture copies under `tmp_path` only; never the vault, never node1.
- Do not touch `rb_host/board.py`, `rb_host/server.py`, `rb_host/jobs.py`, `vault-export/`. Keep edits to `rb_host/config.py` and `rb_host/cli.py` minimal (PR #38 on `claude/linux-hub` also edits them: do not import or reintroduce `DEFAULT_ROOT`/`DEFAULT_WITHHELD`; add the `share` subparser as its own block).
- Run tests with `uv run --extra host pytest -q` (no `rtk` on this machine). Baseline: 294 passed.
- Commit per task with the attribution line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

### A. Assumed input formats (ASSUMPTION — not verified against the laptop)

Reducers must be tolerant: a missing file → `ok:false, error:"missing"`; JSON that fails to parse or has the wrong top-level type → `ok:false, error:"unparseable"`; a record missing a field is skipped, never raises.

1. **Session-calendar sessions** (`share.calendar_sessions`, JSON): a list, or an object with a `"sessions"` list, of session records:
   `{"start": "2026-11-05T09:00:00Z", "end": "2026-11-05T10:30:00Z", "machine": "laptop", "project": "<label>", "kind": "session", "title": "<free text, never copied>"}`.
   `machine` may also appear as `lane`; values other than `laptop` map to `server`. `kind` is `session` or `routine` (missing → `session`). `end` missing → active hours 0 for that record. Day = UTC date of `start`.
2. **Session-calendar status** (`share.calendar_status`, JSON object): `{"generated": "<ISO>", "cost_usd": <number>}` — only `generated` (→ source `fetched_at`) and `cost_usd` (owner tier only) are read.
3. **Run view data** (`share.runs`, JSON): a list, or an object with a `"runs"` list, of run records:
   `{"run_id": "<id>", "project": "<label>", "started": "<ISO>", "ended": "<ISO>|null", "status": "done|failed|running|…", "metrics": {…never copied…}}`.
   Counted per (date, project): `started` by start date; `finished` = ended and status not in {failed, error, crashed}; `failed` = status in {failed, error, crashed}. Status words are used for counting only and never copied.
4. **Board cache** (known format, `rb_host/board.py`): `data_root/board/<node>_<source>.json` = `{"source": "node1:queue", "fetched_at": "<ISO Z>", "ok": bool, "error": code|null, "cadence_s": int, "items": [...]}`. Queue items `{"state","count"}`; gpu items `{"index","name","memory_used","memory_total","utilization"}`; events items `{"ts","stage","kind","track","id"}` newest first.
5. **Ledger** (`rb_host/ledger.py`, `Ledger(path)`, `data_root/ledger.jsonl`): job records with `kind:"job"`, `status`, `gpu_hours`, `created`.
6. **Priorities** `live.json`: as `board.py` (owner tier only; the waiting list comes from `board.load` lazily).

### B. Snapshot schema (`schema_version` 1)

```json
{"schema_version": 1, "tier": "shared", "built_at": "<ISO Z>",
 "period": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
 "sources": [{"id": "calendar:sessions", "fetched_at": "<ISO Z>|null", "ok": true, "error": null, "stale": false}],
 "sessions": {"per_day": [{"date": "YYYY-MM-DD", "lane": "laptop|server", "project": "<label>|other", "count": 0, "active_h": 0.0}],
              "totals": {"sessions": 0, "routines": 0, "active_h": 0.0}},
 "experiments": {"queue": {"queued": 0, "running": 0, "done": 0, "failed": 0, "pending_approvals": 0},
                 "gpu": {"in_use": 0, "total": 0, "gpu_hours_period": 0.0},
                 "runs_per_day": [{"date": "YYYY-MM-DD", "project": "<label>|other", "started": 0, "finished": 0, "failed": 0}],
                 "tracks": [{"track": "<label>|other", "stage": "S5", "last_event_age_s": 0}]},
 "dropped": 0}
```

Source ids: `calendar:sessions`, `calendar:status`, `runs`, `node1:queue`, `node1:gpu`, `node1:events` (one per configured node), `rb:ledger`. Stale rule as `board.py`: `fetched_at` missing or older than the source cadence (`calendar:*` and `runs` 3600 s; node sources their board `cadence_s`; `rb:ledger` never stale).

Owner tier (`tier: "owner"`) adds exactly: `"waiting": [...]` (from `board.load(cfg)["waiting"]`, strings re-checked) and `"cost_usd": <number|null>` under `sessions.totals`. Nothing else differs. Owner files are written to `share/owner/`: under the share directory, but unreachable through `rb share serve`, whose path allowlist names only the two shared files. Never serve `share/` with a generic static server.

Label rule (OQ4 default): `host.json` `share.labels` is a list of allowed project/track labels. A label not on the list (or any label when the list is absent) becomes `other`. Before that mapping, every string is checked with `Withheld._hit`; a hit drops the whole item and increments `dropped`.

Allowed strings in the shared tier: labels after the rule above, `laptop`/`server`, stage codes matching `^S[0-8]$` (anything else → the item is dropped, counted), ISO timestamps, source ids, error codes.

### C. Module interfaces

`rb_host/share.py`:
- `SCHEMA_VERSION = 1`, `SHARED_FILES = ("index.html", "snapshot.json")`
- `share_dir(cfg) -> Path` (= `Path(cfg.data_root)/"share"`), `owner_dir(cfg) -> Path` (= `share_dir/"owner"`)
- `build(cfg: HostConfig, days: int = 7, tier: str = "shared", today: Optional[date] = None) -> dict` — returns `{"snapshot": dict, "paths": [Path, Path], "dropped": int}`; writes `snapshot.json` and `index.html` (via `share_serve.render_html`) with `*.part` + `os.replace`; appends one audit line to `share_dir/audit.jsonl` (`ts, tier, sources, items, dropped, sha256` of the snapshot bytes; no payload); reads every source without writing to it.
- Reducers, one per source, each `(…, wh: Withheld, labels: Optional[set]) -> (items, dropped)`.
- Imports allowed at module level: stdlib, `rb_node.withheld`, `.config`, `.ledger`, `.share_serve`. `rb_host.board` only inside the owner branch (lazy). Never `.server`, `.client`, `.jobs`, `mcp`, `urllib`, `http.client`, `socket`.

`rb_host/share_serve.py`:
- `render_html(snapshot: dict) -> str` — complete HTML document, no `<script>`, no external URL (no `http://`, `https://`, `//` references), every value through `html.escape`; sections: period + built_at; sources table (id, fetched_at, ok/error, stale); sessions per day; totals; queue; gpu; runs per day; tracks (or the error of `node1:events`); owner tier only: waiting list and cost. Unavailable section shows `unavailable (<error>)`.
- `make_server(root: Path, bind: str, port: int) -> http.server.HTTPServer` and `serve(root, bind="127.0.0.1", port=<default 8766>) -> None`. Handler subclasses `BaseHTTPRequestHandler` (not `SimpleHTTPRequestHandler`): GET and HEAD only; raw `self.path` must equal `/`, `/index.html` or `/snapshot.json` exactly (a `?`, `#`, `%`, `..`, `//` or anything else → 404 before any unquote); target must be a regular file and not a symlink (`os.path.islink` → 404); directory listing never; headers `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'`. `serve` refuses to start (raise `ValueError`) if `root/snapshot.json` exists and its `tier` is not `shared`. Logging: one line per request with method, path and status; no body.

`rb_host/config.py`: add `share: Dict[str, Any] = field(default_factory=dict)` next to `board`, and `"share"` in `load_host_config`'s key list. Keys used: `calendar_sessions`, `calendar_status`, `runs` (paths), `labels` (list).

`rb_host/configure.py`: `set_key` accepts `share.calendar_sessions|calendar_status|runs` (strings). `labels` stays a hand-edited list (no CLI setter).

`rb_host/cli.py`: `rb share build [--days N] [--tier shared|owner]` → calls `share.build`; prints the written paths and `dropped N`; prints one hint line when `share.labels` is absent (`labels not configured: all project and track labels shown as "other"`); exit 1 if `dropped > 0`, else 0; a source missing is exit 0. `rb share serve [--port <SHARE_PORT>] [--bind 127.0.0.1]` → `share_serve.serve(share.share_dir(cfg), bind, port)`.

## Tasks

### Task A — builder (`rb_host/share.py`, config, CLI)

Files: create `rb_host/share.py`; edit `rb_host/config.py`, `rb_host/configure.py` (set_key + docstring), `rb_host/cli.py`. Do not create `rb_host/share_serve.py` (Task B owns it; import it lazily inside `build` so the module imports even if B is not there yet) and do not write `tests/test_share.py` (Task C). Write a small smoke test of your own only as a temporary script, not a committed test.

Requirements: Global Constraints A–C in full. Specifics:
- Period: `to = today` (UTC), `from = today - days`. Records outside the period are ignored.
- `active_h` = sum of (end − start) in hours, rounded to 2 decimals; negative or > 24 h durations are skipped.
- `pending_approvals` = number of latest ledger job records with `status == "pending_approval"`; `gpu_hours_period` = sum of `gpu_hours` of job records whose `created` date falls in the period (number, else 0).
- `gpu.in_use` = gpu items with `utilization > 0` or `memory_used > 0`; `gpu.total` = number of items.
- `queue` counts come from the `node1:queue` items `{state,count}`; states map to the four keys by name (`queued|pending → queued`, `running → running`, `done|finished → done`, `failed|error → failed`); unknown states are not copied.
- `tracks`: for each track in `node1:events` items, the newest event's `stage` (must match `^S[0-8]$`) and `last_event_age_s` = now − ts. When the events source is not ok, `tracks` is `[]` and the `node1:events` source entry carries the error code (the page shows the node's refusal).
- Every string that lands in the snapshot passes `wh._hit` (drop + count on hit). Labels then pass the allowlist rule.
- Snapshot bytes: `json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)`.
- `build` must not write to any source path; it opens them read-only.

### Task B — renderer and static server (`rb_host/share_serve.py`)

Files: create `rb_host/share_serve.py` only. Requirements: Global Constraints B–C (`render_html`, `make_server`, `serve`). Use `html.escape(str(v), quote=True)` for every value. Inline CSS only. The HTML must contain the literal marker `<!-- research-bridge share page; schema_version N -->`. Keep the handler's path check as a single explicit comparison against a tuple of allowed raw paths; map `/` to `index.html`. Return 405 for other methods. Smoke-test by rendering the example snapshot from Global Constraints B and by starting `make_server` on port 0 in a temporary script (not committed).

### Task C — tests (`tests/test_share.py`)

Files: create `tests/test_share.py` only. Use the fixture style of `tests/test_board.py` (`tmp_path`, `monkeypatch.setenv("RB_HOST_CONFIG", …)`, `cli.main([...])`). Fixtures: a sessions file, a status file, a runs file (each in the assumed shape, including a free-text `title`, a `metrics` object and an extra unknown field), board cache files for `n1:queue`, `n1:gpu`, `n1:events` (one stale by `fetched_at`, one with `ok:false, error:"denied"`), a ledger with one `pending_approval` job, an empty withheld patterns file (`{"patterns": []}`; the fallback pattern `pp_ltf_` is always active), and `share.labels = ["ARG"]`.

Tests (names from design §10, plus the last three):
- `test_all_sections_present` — all top-level keys and sections from schema B; `tier == "shared"`.
- `test_unknown_source_field_not_copied` — the extra field, `title` and `metrics` never appear anywhere in the snapshot or the HTML.
- `test_serve_only_two_files` — against `make_server` on port 0: `/` and `/index.html` and `/snapshot.json` → 200 with the right bodies; `/../snapshot.json`, `/md?x=1`, `/%2e%2e/snapshot.json`, `/snapshot.json?x`, `/owner/snapshot.json`, `/audit.jsonl`, a symlink placed in the root pointing to a file outside → 404; POST → 405; response has `Cache-Control: no-store` and no directory listing.
- `test_stale_and_failed_sources_marked` — the stale source has `stale: true`; the denied one `ok: false, error: "denied"`, and `tracks == []` when `n1:events` is the denied one.
- `test_sources_unchanged` — sha256 of every fixture file before and after `build` is equal.
- `test_shared_tier_has_no_waiting_list_or_pending_details` — shared snapshot has no `waiting`, no `cost_usd`, no `gpu_hours` per job, no config names; `pending_approvals == 1`. Owner tier (`--tier owner`) is written under `share/owner/` and `serve` raises `ValueError` when pointed at a root whose `snapshot.json` has `tier: "owner"`.
- `test_withheld_label_dropped` — a session whose project is `pp_ltf_x` and a track named `pp_ltf_y` are absent; `dropped >= 2`; `cli.main(["share","build"])` returns 1 and stderr carries a count, not the label.
- `test_audit_has_no_payload` — the audit line has `ts, tier, sources, items, dropped, sha256`; the file text contains no label, no title and no timestamp of a session.
- `test_no_network_client_imported` — in a fresh interpreter (`subprocess`, `sys.executable -c`), `import rb_host.share` leaves none of `urllib.request`, `http.client`, `rb_host.server`, `rb_host.client`, `mcp`, `socket` in `sys.modules`.
- `test_labels_not_on_allowlist_become_other` — a project `ZZZ` appears as `other`; `ARG` stays.
- `test_html_has_no_script_or_external_url` — rendered HTML has no `<script`, no `http://`, `https://`, `src=`, `href=`.
- `test_snapshot_written_atomically` — no `*.part` left after build; a build with a failing renderer (monkeypatch `share_serve.render_html` to raise) leaves the previous `index.html` intact.

Expect to run against Tasks A and B; until they land, write the tests to the contract and run only the ones that can pass.

### Task D — integration (controller)

Run the whole suite; a fix round through the implementers for mismatches; whole-branch review; design §13 decision log; `docs/HANDOFF.md` section (separate from the Linux-hub section of PR #38).
