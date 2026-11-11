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

