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

