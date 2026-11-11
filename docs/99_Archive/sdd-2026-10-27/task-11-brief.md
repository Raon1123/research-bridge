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

