# research-bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One SSH-key-authenticated channel between the laptop (host) and node1 (node) for laptop↔server Claude-session messages with file attachments, masked reading of server H-/EXP- documents, two-step-approved budgeted job submission, a manual harness-sync channel, and display in the 8765 session browser.

**Architecture:** Two Python packages in one repo. `rb_node` (stdlib only, Python ≥3.8, deployed to node1) runs either as `serve-remote` (SSH forced command; line-delimited JSON protocol) or `serve-local` (stdio MCP for server Claude sessions), both over a mailbox directory `~/.research-bridge/`. `rb_host` (laptop, Python 3.14, `mcp` FastMCP) talks to `serve-remote` through `ssh rb-node1`, keeps a ledger in `D:/raw/research-bridge/`, and offers the `rb` CLI for approvals and harness sync.

**Tech Stack:** Python 3 stdlib (node), `mcp>=1.27,<2` FastMCP (host), pytest, OpenSSH (Windows client, Linux server), `pdftotext` if present on node.

**Spec:** `docs/superpowers/specs/2026-10-27-research-bridge-design.md`

## Global Constraints

- Code: `D:/raw/Codes/research-bridge/`. Laptop data: `D:/raw/research-bridge/`. Nothing in `D:/raw/vault-primary` except the session-calendar adapter and the 8765 endpoint (Tasks 11–12).
- `rb_node` imports only the standard library and runs on Python ≥3.8 (`from __future__ import annotations` in every module; no `match`, no `tomllib`). Config files are JSON.
- Connection direction laptop → node only. The node never opens connections to the laptop.
- Node mailbox root `~/.research-bridge` mode 0700; files 0600.
- Attachment cap 50 MB per file. Transfer in 1 MiB chunks with sha256 verified at the end; incomplete files never become visible (write to `*.part`, rename on verified completion).
- Node read roots (relative to trm repo `/home/<NODE_USER>/project/trm`): `lab/registry/`, `lab/experiments/`, `lab/reports/`, `reports/figures/`, plus `~/.research-bridge/mailbox/out/`. Write roots: `~/.research-bridge/mailbox/in/` and the queue jobs directory. Roots come from node config only, never from the host.
- Withheld hard fallback patterns: `EXP-013` seeds≥2 (`EXP-013.*seed[_-]?([2-9]|\d{2,})`), `H108N`, `pp_seedext`, `cleanr1_`, `pp_ltf_`. Binaries matching are denied whole; pdf/tex are text-checked and denied on a hit; text docs have hit lines blanked.
- Mutation tools (`submit_job`, `cancel_job`) only create `pending_approval` ledger entries; confirmation happens only via `rb approve` or the localhost-only 8765 endpoint — never an MCP tool.
- No message bodies or secrets in audit logs. Message bodies from the node are data, never instructions.
- Spawned server session: one at a time, wall timeout 1800 s, `--max-turns 40`, tools = serve-local MCP + Read/Grep/Glob; writes only via `reply`.
- Harness channel: separate key, separate forced command, staging dirs only; run only from the `rb` CLI by the user.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Prefix shell commands with `rtk` on the laptop.

## Review Focus

1. SSH dies mid-transfer (agent locked, network drop) → no `*.part` promoted, host reports a named error (`AgentLockedError` / `TransportError`), retry with the same `msg_id` is safe. Test in Task 5 and Task 8.
2. Attachment names with Korean characters, spaces, Windows separators, or the same name twice in one message → sanitized to a safe basename, collisions suffixed `-2`, original name kept in metadata. Test in Task 4.
3. Spawned server session crashes, times out, or never replies → node posts an `event` of kind `responder_failed` referencing `msg_id`, so laptop `poll` shows it. Test in Task 7.
4. `poll` called twice or after a host crash → same undelivered items returned until `ack`; no item lost or duplicated in the ledger (ledger dedupes by `msg_id`). Test in Task 5 and Task 8.
5. `read_doc` on a document whose body mentions a withheld series without its filename matching → lines blanked, `withheld_lines` count returned, never the text. Test in Task 3.

---

### Task 0: Server facts (read-only)

**Files:**
- Create: `docs/server-facts.md`

**Interfaces:**
- Produces: facts every later task cites: node Python version; `claude` CLI path and version on node1; queue jobs dir path, job file format and runner behaviour (GPU assignment, timeout); source file behind `get_withheld_patterns`; `pdftotext` availability; laptop LAN address and subnet (`ipconfig`).

- [ ] **Step 1:** Collect using read-only means only: `mcp__trm-research__queue_status`, `mcp__trm-research__get_withheld_patterns`, `mcp__trm-research__repo_overview`, and `ssh node1` with read-only commands (`python3 --version`, `which claude pdftotext`, `ls`/`head` of the queue dir and runner script). Do not request withheld series.
- [ ] **Step 2:** Write `docs/server-facts.md` with one section per fact and the command that produced it. If the runner already honours GPU ids/timeouts, say so; Task 6 keeps the `run-job` wrapper regardless.
- [ ] **Step 3:** Commit `docs: node1 server facts`.

### Task 1: Scaffold and wire protocol

**Files:**
- Create: `pyproject.toml`, `rb_node/__init__.py`, `rb_node/protocol.py`, `rb_host/__init__.py`, `tests/test_protocol.py`, `.gitignore`

**Interfaces:**
- Produces (`rb_node/protocol.py`):
  - `CHUNK = 1 << 20`, `MAX_FILE = 50 * 1024 * 1024`
  - `class ProtocolError(Exception)` with `code: str`
  - `encode(obj: dict) -> bytes` (one JSON line, UTF-8, `\n`-terminated, `ensure_ascii=False`)
  - `read_message(stream: BinaryIO, max_line: int = 4 * CHUNK) -> dict | None` (None on EOF; `ProtocolError("line_too_long")` past `max_line`)
  - Request `{"id": str, "op": str, "args": dict}`; response `{"id": str, "ok": bool, "result": any}` or `{"id", "ok": false, "error": {"code": str, "message": str}}`
  - `ok(req_id, result) -> dict`, `err(req_id, code, message) -> dict`

- [ ] **Step 1:** Tests: round trip of a dict with Korean text; `read_message` returns None on empty stream; an over-long line raises `ProtocolError` with `code == "line_too_long"`; `err("1","denied","x")["error"]["code"] == "denied"`.
- [ ] **Step 2:** Run `rtk pytest tests/test_protocol.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement. `pyproject.toml`: packages `rb_node`, `rb_host`; scripts `rb-node = rb_node.cli:main`, `rb = rb_host.cli:main`, `rb-host-mcp = rb_host.server:main`; host extra deps `mcp>=1.27,<2`; pytest `pythonpath=["."]`.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** `git init` already done; commit `feat: scaffold and wire protocol`.

### Task 2: Path policy

**Files:**
- Create: `rb_node/paths.py`, `tests/test_paths.py`

**Interfaces:**
- Produces: `class PolicyError(Exception)`; `class PathPolicy(read_roots: list[Path], write_roots: list[Path])` with `resolve_read(rel_or_abs: str) -> Path` and `resolve_write(rel: str) -> Path`. Relative paths resolve against the first root of the respective list unless they start with a root's name prefix (`lab/…` resolves against the trm repo root given as `base`); constructor signature `PathPolicy(base: Path, read_roots: list[str], write_roots: list[str])` where roots are relative to `base` or absolute.

- [ ] **Step 1:** Tests (use `tmp_path`): reading `lab/registry/HYPOTHESES.md` inside root succeeds; `lab/registry/../../etc/passwd` → `PolicyError`; absolute `/etc/passwd` → `PolicyError`; a symlink inside a root pointing outside → `PolicyError` (skip with `pytest.skip` if `os.symlink` raises `OSError` on Windows); write to a read-only root → `PolicyError`; NUL byte in path → `PolicyError`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement with `os.path.realpath` then `commonpath` containment against realpath'd roots.
- [ ] **Step 4:** Run → PASS. Commit `feat(node): path policy`.

### Task 3: Withheld filter

**Files:**
- Create: `rb_node/withheld.py`, `tests/test_withheld.py`

**Interfaces:**
- Consumes: fact "withheld pattern source" from Task 0.
- Produces: `FALLBACK_PATTERNS: list[str]` (Global Constraints values); `class Withheld(patterns: list[str])` with `@classmethod load(source: Path | None) -> Withheld` (union of file patterns and fallback; missing/unparseable file → fallback only, never empty), `name_hit(path: str) -> bool`, `mask_text(text: str) -> tuple[str, int]` (blank each hit line to `""`, return count), `check_file(path: Path) -> str` returning one of `"ok"`, `"deny_name"`, `"deny_content"`, `"deny_unscannable"`. pdf: run `pdftotext -q <file> -` (timeout 30 s); if `pdftotext` missing → `"deny_unscannable"`. `.tex/.md/.txt/.csv/.json` scanned as text; `.png/.jpg/.svg` name-only.

- [ ] **Step 1:** Tests: `name_hit("reports/figures/pp_ltf_a.png")` True; `mask_text("a\nH108N-x result\nb")` → `("a\n\nb", 1)`; a `.tex` file containing `cleanr1_run` → `"deny_content"`; `.pdf` with `shutil.which` monkeypatched to None → `"deny_unscannable"`; `load(Path("missing.json"))` still hits `pp_seedext_1`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. Commit `feat(node): withheld filter`.

### Task 4: Mailbox

**Files:**
- Create: `rb_node/mailbox.py`, `tests/test_mailbox.py`

**Interfaces:**
- Produces: `class Mailbox(root: Path)` (creates `in/`, `out/`, `state/` with 0700/0600 where the OS supports it):
  - `new_message(msg_id: str, meta: dict) -> Path` (`in/<msg_id>/message.json`; existing `msg_id` → returns existing dir, idempotent)
  - `open_part(msg_id: str, box: str, name: str) -> tuple[str, BinaryIO]` returns sanitized name; `commit_part(msg_id, box, name, sha256: str) -> None` verifies and renames `.part`; mismatch → `ProtocolError("checksum")` and deletes part
  - `sanitize(name: str, taken: set[str]) -> str` (basename after `\\`/`/`, strip control chars, keep Unicode, collision → `stem-2.ext`)
  - `post_out(kind: str, body: str, attachments: list[Path], reply_to: str | None) -> str` (new `out/<id>/`, kind ∈ `reply|event`)
  - `undelivered() -> list[dict]` (out items without `state/acked/<id>`), `ack(ids: list[str]) -> None`
  - `inbox(status: str | None = None) -> list[dict]`, `set_status(msg_id, status)` with status ∈ `new|responding|answered|failed`

- [ ] **Step 1:** Tests: `sanitize("C:\\x\\결과 그림.png", set())` == `"결과 그림.png"`; second same name → `"결과 그림-2.png"`; checksum mismatch leaves no file; `undelivered` returns item until `ack`; `new_message` twice same id → one dir.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(node): mailbox`.

### Task 5: serve-remote dispatcher

**Files:**
- Create: `rb_node/config.py`, `rb_node/remote.py`, `rb_node/cli.py`, `rb_node/audit.py`, `tests/test_remote.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `NodeConfig` (dataclass) loaded by `load_config(path: Path = ~/.research-bridge/node.json)`: `trm_root`, `read_roots`, `write_roots`, `queue_dir`, `withheld_source`, `claude_bin`, `job_template: list[str]` (argv with `{config}` placeholder), `max_file`.
  - `Audit(path: Path).record(**fields)` (JSONL; drops keys `body`, `content`, `data`).
  - `serve(cfg: NodeConfig, stdin: BinaryIO, stdout: BinaryIO) -> int`. Ops and args:
    - `hello {}` → `{"node": hostname, "version": __version__}`
    - `msg_begin {msg_id, body, from_session, attachments:[{name, bytes, sha256}]}` → `{"names": [sanitized]}`; rejects any `bytes > max_file` with `too_large`
    - `put_chunk {msg_id, name, seq, data_b64}`; `msg_commit {msg_id}` → verifies all parts, sets status `new`, then calls `spawn.trigger(cfg, msg_id)` (Task 7; until then a no-op stub `rb_node/spawn.py: trigger(cfg, msg_id) -> None`)
    - `poll {}` → `undelivered()` metadata (no attachment bytes); `ack {ids}`
    - `get_file {kind: "out"|"doc", ref, seq}` → `{data_b64, eof, sha256 (on eof)}`; `doc` refs pass `PathPolicy.resolve_read` then `Withheld.check_file`; text docs streamed after `mask_text`
    - `read_doc {path | id}` → `{text, withheld_lines}`; `id` like `H-123`/`EXP-015` resolves to `lab/experiments/EXP-015.md` or the matching section of `lab/registry/HYPOTHESES.md` (section = heading line containing the id through next same-level heading)
    - `queue_status {}` → listing of queue dir (name, mtime, state dir); `gpu_status {}` → parsed `nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits` (missing binary → `{"gpus": [], "error": "nvidia-smi not found"}`)
    - unknown op → `err(..., "unknown_op")`; any `PolicyError` → `"denied"`
  - `cli.main()` subcommands: `serve-remote`, `serve-local`, `run-job`, `respond`, `harness-receive`, `harness-send`. `serve-remote` ignores `SSH_ORIGINAL_COMMAND`.

- [ ] **Step 1:** Tests drive `serve` with `io.BytesIO` pairs against a `tmp_path` fake trm tree: full message round trip with a 2.5 MiB attachment (3 chunks) ending in `in/<id>/` with matching sha256; truncated upload (no `msg_commit`) leaves only `.part`; `read_doc {"id":"EXP-015"}` returns text; `read_doc` of a file mentioning `pp_ltf_x` returns `withheld_lines == 1` and no `pp_ltf_x` substring; `get_file` on `../../x` → `denied`; `poll` twice returns same ids, after `ack` returns none; `unknown_op` error; audit file contains no `body` key.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(node): serve-remote`.

### Task 6: Jobs and budget wrapper

**Files:**
- Create: `rb_node/jobs.py`, `rb_node/run_job.py`, `tests/test_jobs.py`
- Modify: `rb_node/remote.py` (add ops)

**Interfaces:**
- Consumes: Task 0 queue format; Task 5 `NodeConfig.job_template`, `queue_dir`.
- Produces:
  - op `job_submit {job_id, idempotency_key, config_name, config_sha256, gpus: list[int], gpu_hours: float, note}` (config uploaded first with `put_chunk` under `msg_id = "job-" + job_id`) → writes a queue job in the Task-0 format whose command is `["rb-node","run-job","--gpus",",".join(gpus),"--gpu-hours",str(h),"--job-id",job_id,"--"] + job_template` with `{config}` replaced by the stored config path; returns `{"queued": path}`. Reused `idempotency_key` → returns the original result, writes nothing. Validation: `gpus` non-empty ints within `nvidia-smi` indices (skip check if unavailable), `0 < gpu_hours <= 168`, config ext ∈ `.yaml .yml .json`.
  - op `job_cancel {job_id, idempotency_key}` → removes a pending queue file or writes `state/cancel/<job_id>` for a running job (`run-job` polls it every 10 s).
  - `run_job(gpus: list[int], gpu_hours: float, job_id: str, argv: list[str], state_dir: Path) -> int`: env `CUDA_VISIBLE_DEVICES`, wall limit `gpu_hours * 3600 / len(gpus)` s, on limit SIGTERM then SIGKILL after 60 s, writes `state/jobs/<job_id>.json` with `status ∈ {done, failed, budget_exceeded, cancelled}`, exit code, start/end; posts a mailbox `event` kind `job_finished`.

- [ ] **Step 1:** Tests: same idempotency key twice → one queue file; `gpu_hours=0` → `invalid`; `run_job` with argv `[sys.executable, "-c", "import time; time.sleep(5)"]` and `gpu_hours=0.0005, gpus=[0]` (1.8 s) → `budget_exceeded`; child sees `CUDA_VISIBLE_DEVICES == "0,2"` for `gpus=[0,2]`; cancel file stops a running job → `cancelled`; `job_finished` event appears in `undelivered()`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(node): budgeted jobs`.

### Task 7: serve-local MCP and per-message responder

**Files:**
- Create: `rb_node/local.py`, `rb_node/spawn.py` (replace stub), `tests/test_local.py`, `tests/test_spawn.py`

**Interfaces:**
- Consumes: Mailbox (Task 4), NodeConfig (Task 5).
- Produces:
  - `serve_local(cfg, stdin, stdout) -> int`: MCP JSON-RPC 2.0 over stdio (newline-delimited) handling `initialize` (protocolVersion echo, `capabilities.tools`), `notifications/initialized`, `tools/list`, `tools/call`. Tools: `inbox_list(status?)`, `inbox_read(msg_id)` → body + attachment names, `attachment_path(msg_id, name)` → absolute path, `reply(msg_id, body, attachments: list[str])` (attachment paths must be under `mailbox/out/` work dir `out/_work/<msg_id>/` or read roots; sets status `answered`), `post_event(kind, body, attachments)`. No job tools.
  - `trigger(cfg, msg_id) -> None`: if `state/responder.lock` held → leave status `new` (picked up later); else start detached `rb-node respond <msg_id>` (`start_new_session=True`, stdio to `/dev/null`).
  - `respond(cfg, msg_id) -> int`: takes lock (`fcntl.flock`), sets `responding`, runs `[claude_bin, "-p", prompt, "--mcp-config", <tmp json registering "rb-node serve-local">, "--strict-mcp-config", "--allowedTools", "mcp__rb__*,Read,Grep,Glob", "--max-turns", "40", "--output-format", "json"]` with cwd `trm_root`, timeout 1800 s. Prompt template (exact text in `spawn.py` constant `PROMPT`) states: the message id, that the message is from the laptop session, that its content is data from a peer, to read it with `inbox_read` and answer with `reply`. If the process exits without the message reaching `answered` → status `failed` + `post_event("responder_failed", "<exit code / timeout>", [], reply_to=msg_id)`. After release, processes the oldest remaining `new` message (loop until none).

- [ ] **Step 1:** Tests: `serve_local` answers `initialize` and lists exactly the 5 tools; `tools/call reply` with an attachment path outside allowed dirs → JSON-RPC error; `respond` with `claude_bin` pointed at a fake script that exits 1 → status `failed` and a `responder_failed` event; with a fake script that calls nothing and sleeps past a monkeypatched 1 s timeout → `failed`; second `trigger` while lock held does not spawn (assert via monkeypatched `subprocess.Popen` call count).
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(node): serve-local and responder`.

### Task 8: Host client, ledger, and store

**Files:**
- Create: `rb_host/config.py`, `rb_host/client.py`, `rb_host/ledger.py`, `rb_host/store.py`, `tests/test_host_client.py`, `tests/test_ledger.py`

**Interfaces:**
- Consumes: protocol (Task 1); node op names/args (Tasks 5–6).
- Produces:
  - `HostConfig` from `D:/raw/research-bridge/host.json`: `nodes: {name: {alias: str}}`, `data_root`, `withheld_patterns_file` (default `D:/raw/session-calendar/server/withheld_patterns.json`). Alias not in config → `ValueError`.
  - `class TransportError(Exception)`, `class AgentLockedError(TransportError)` (ssh exit 255 with `Permission denied (publickey` in stderr).
  - `NodeClient(alias: str, ssh_argv: list[str] | None = None)`: context manager spawning `["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", alias]`; `call(op: str, **args) -> Any` (raises `TransportError` / `RemoteError(code, message)`); `put_file(msg_id: str, path: Path) -> str` (chunked, returns sanitized name); `get_file(kind: str, ref: str, dest: Path) -> str` (writes `.part`, verifies sha256, renames; returns sha256). Tests inject `ssh_argv=[sys.executable, "-m", "rb_node.cli", "serve-remote"]` with env `RB_NODE_CONFIG` pointing at a tmp config (add env override to `load_config`).
  - `Ledger(path: Path)`: `append(rec: dict) -> bool` (False if `(kind, id)` already present), `get(id)`, `thread(msg_id) -> list[dict]`, `pending_jobs() -> list[dict]`, `update(id, **fields)` (appends a new version line; readers take the last line per id).
  - `store_incoming(cfg, node, item, client) -> dict`: saves attachments to `data_root/inbox/<node>/<msg_id>/`, writes `provenance.json` (`node`, `msg_id`, `received_at`, per-file `sha256`, `bytes`), re-checks names and text bodies with the session-calendar patterns; a hit → file moved to `quarantine/` and recorded, never left in `inbox/`.

- [ ] **Step 1:** Tests (local subprocess node): `put_file` + `msg_commit` then node-side file exists; `get_file` kill-mid-transfer (wrap ssh_argv in a script that exits after first chunk) → `TransportError` and no non-`.part` file; fake ssh exiting 255 with publickey stderr → `AgentLockedError`; `Ledger.append` same record twice → second returns False; `store_incoming` with a reply attachment named `pp_ltf_fig.png` → in `quarantine/`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(host): client, ledger, store`.

### Task 9: Host MCP server and `rb` CLI

**Files:**
- Create: `rb_host/server.py`, `rb_host/cli.py`, `rb_host/jobs.py`, `tests/test_host_tools.py`, `README.md`

**Interfaces:**
- Consumes: Task 8.
- Produces:
  - FastMCP `research-bridge` tools: `nodes()`, `send_message(node, body, attachments: list[str] = [], reply_to: str | None = None, from_session: str = "")` → `{msg_id}` (uuid4 hex; ledger kind `message`, direction `out`), `poll(node: str | None = None)` → new items stored + acked + ledgered, `thread(msg_id)`, `read_doc(node, ref)`, `fetch_file(node, path)` → stored path, `queue_status(node)`, `gpu_status(node)`, `submit_job(node, config_path, gpus, gpu_hours, idempotency_key, note="")` → `{job_id, status: "pending_approval"}` (ledger only, no SSH), `cancel_job(node, job_id, idempotency_key)` → pending cancel. `main()` runs stdio.
  - `rb_host/jobs.py`: `approve(ledger, cfg, job_id) -> dict` (uploads config, calls `job_submit`/`job_cancel`, sets `approved`→`queued`), `reject(ledger, job_id)`.
  - `rb` CLI: `rb pending`, `rb approve <job_id>`, `rb reject <job_id>`, `rb harness push|pull --node <n>` (Task 10). `approve` prints the job (node, config, gpus, gpu_hours, note) and asks `y/N` on stdin unless `--yes`.
  - README: install (`pip install -e .[host]`), registering `rb-host-mcp` in `~/.claude.json` user scope, `rb` usage.

- [ ] **Step 1:** Tests: `submit_job` makes no SSH call (client factory monkeypatched to raise) and ledger shows `pending_approval`; `approve` with local node → queue file exists and status `queued`; approve twice → second is a no-op returning the same result; the FastMCP tool list contains no `approve`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(host): mcp server and rb cli`.

### Task 10: Harness sync channel (manual)

**Files:**
- Create: `rb_node/harness.py`, `rb_host/harness.py`, `tests/test_harness.py`
- Read first: `D:/raw/vault-primary/90_Claude/60_Tools/sync/portablize_harness.py`, `D:/raw/vault-primary/90_Claude/60_Tools/harness-sync/deliver.ps1` (allowlist source)

**Interfaces:**
- Produces:
  - `rb harness push --node node1 [--dry-run]`: builds a tar of the allowlisted harness files (same allowlist as `deliver.ps1`, paths portablized by `portablize_harness.py` logic imported or vendored), sends through alias `rb-node1-harness` to `rb-node harness-receive`, which unpacks into `~/.research-bridge/harness-staging/<UTC stamp>/` only (tar members checked with `PathPolicy` — no absolute, no `..`, no links).
  - `rb harness pull --node node1`: `rb-node harness-send` tars the server's allowlisted `~/.claude` subset into the laptop `D:/raw/research-bridge/harness-staging/<stamp>/`.
  - `rb harness diff <stamp>` prints a unified diff against the live harness; applying stays manual (README documents the copy command). No apply command.

- [ ] **Step 1:** Tests: tar with member `../evil` or a symlink → rejected, nothing written; push to local fake node lands under `harness-staging/<stamp>/`; `--dry-run` lists files and sends nothing.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat: manual harness channel`.

### Task 11: 8765 approval endpoint

**Files:**
- Modify: `D:/raw/vault-primary/90_Claude/60_Tools/dashboard/server.py` (GET ~L809-905, POST ~L1223-1274)
- Create: `D:/raw/vault-primary/90_Claude/60_Tools/dashboard/rb_pending.py`

**Interfaces:**
- Consumes: `rb_host.jobs.approve/reject`, `Ledger.pending_jobs` (import via `sys.path` insert of `D:/raw/Codes/research-bridge`).
- Produces: `GET /rb/pending` HTML list (node, config name, gpus, gpu_hours, note, Approve/Reject buttons); `POST /rb/approve` and `/rb/reject` with form `job_id` — rejected with 403 unless `self.client_address[0] == "127.0.0.1"` (server binds 0.0.0.0, so this check is required), and unless the form carries the per-process CSRF token rendered into the page.

- [ ] **Step 1:** Before editing run `ListAgents` and confirm no session is editing `dashboard/server.py`.
- [ ] **Step 2:** Test `rb_pending.py` functions directly (`render_pending(ledger) -> str`, `handle_post(client_ip, form, token) -> (status, body)`): non-localhost → 403; bad token → 403; valid → calls approve (monkeypatched).
- [ ] **Step 3:** Implement, wire routes in `server.py` with minimal surgical edits, restart via `_restart.bat`, `curl http://127.0.0.1:8765/rb/pending` → 200; from LAN IP → POST 403.
- [ ] **Step 4:** Copy test into repo `tests/test_rb_pending.py`; commit in research-bridge `feat: 8765 approval endpoint` (dashboard files are outside the repo; note path in commit body).

### Task 12: Session-browser edges

**Files:**
- Create: `D:/raw/vault-primary/90_Claude/60_Tools/session-calendar/bridge_edges.py`
- Modify: `D:/raw/vault-primary/90_Claude/60_Tools/session-calendar/refresh.py` (add one step after `link`), and the agent-sequence renderer only if a new edge kind needs a label

**Interfaces:**
- Consumes: ledger lines (kind `message`, `reply`, `event`, `job`).
- Produces: `build_edges(ledger_path: Path) -> list[dict]` emitting the same edge shape `agent_graph.py` uses for SendMessage edges (read it; match field names), with `kind = "bridge"`, `peer = "<node>:<to_session or 'responder'>"`, timestamps, attachment count and total bytes. Metadata only: no `body`. Output merged into `cache/agents/<sid>.json` for the laptop `from_session`.

- [ ] **Step 1:** `ListAgents` check as in Task 11. Read `ISSUES.md` and `REPRODUCE.md` first.
- [ ] **Step 2:** Test `build_edges` on a fixture ledger: two edges, no `body` key anywhere in output.
- [ ] **Step 3:** Implement, run `refresh.py`, then `verify.py` → all PASS; open `/agents` for the session that sent a test message and see the bridge edge.
- [ ] **Step 4:** Commit test copy in repo `feat: session browser edges`.

### Task 13: Provisioning and live run on node1 (user-approved steps)

**Files:**
- Create: `docs/provisioning.md`, `deploy/node.json.example`, `deploy/authorized_keys.example`

**Interfaces:**
- Consumes: everything above; Task 0 facts.

- [ ] **Step 1:** Write `docs/provisioning.md` with the exact commands below, then ask the user to run or approve each.
- [ ] **Step 2 (user):** `ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-laptop` (with passphrase) and `…/node1_harness_ed25519 -C research-bridge-harness`; `ssh-add` both into the Windows ssh-agent service.
- [ ] **Step 3 (user):** `~/.ssh/config` entries `rb-node1` and `rb-node1-harness`: `HostName <NODE_HOST>`, `Port <NODE_PORT>`, `User <NODE_USER>`, `IdentityFile` the new key, `IdentitiesOnly yes`, `StrictHostKeyChecking yes`.
- [ ] **Step 4 (user-approved scp via existing `node1` alias):** copy `rb_node/` to `~/.local/share/research-bridge/rb_node/`, install `~/.local/bin/rb-node` wrapper (`exec python3 -m rb_node.cli "$@"` with `PYTHONPATH`), write `~/.research-bridge/node.json` from the example with Task 0 values, `chmod 700 ~/.research-bridge`.
- [ ] **Step 5 (user):** append two lines to `~/.ssh/authorized_keys`:
  `restrict,from="<laptop subnet from Task 0>",command="/home/<NODE_USER>/.local/bin/rb-node serve-remote" ssh-ed25519 … research-bridge-laptop`
  `restrict,from="<same>",command="/home/<NODE_USER>/.local/bin/rb-node harness-receive" ssh-ed25519 … research-bridge-harness` (pull uses `SSH_ORIGINAL_COMMAND == "harness-send"` checked inside `harness-receive`'s entry; any other value → exit 1).
- [ ] **Step 6:** Security checks, each must hold: `ssh rb-node1` gives no shell (output is protocol `hello` only after sending a request); `ssh rb-node1 cat /etc/passwd` returns nothing from cat; `ssh -o IdentityFile=C:/keys/<SHARED_KEY> -o IdentitiesOnly=yes rb-node1` still reaches a normal shell (that key is unchanged) — record that the new keys, not the old, are restricted; `read_doc` of `../../.ssh/authorized_keys` → `denied`.
- [ ] **Step 7:** Register `rb-host-mcp` in `~/.claude.json` user scope; in a new laptop session: `send_message("node1", "EXP-015 그림 해석을 요약해 달라", [<a small pdf>])`, wait, `poll` → reply with attachment stored under `D:/raw/research-bridge/inbox/node1/<msg_id>/` with `provenance.json`; `read_doc("node1","H-001")`; `submit_job` a tiny config with `gpu_hours=0.01` → `rb approve` → `job_finished` event with `budget_exceeded` or `done`.
- [ ] **Step 8:** Write `docs/provisioning.md` results section (what passed); commit `docs: provisioning and live verification`. Write the vault daily log `90_Claude/90_Daily/2026-10-27.md` entry.
