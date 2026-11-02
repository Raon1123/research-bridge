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

