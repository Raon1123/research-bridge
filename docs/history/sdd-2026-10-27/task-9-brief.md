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

