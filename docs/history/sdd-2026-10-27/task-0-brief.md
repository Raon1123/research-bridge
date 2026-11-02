### Task 0: Server facts (read-only)

**Files:**
- Create: `docs/server-facts.md`

**Interfaces:**
- Produces: facts every later task cites: node Python version; `claude` CLI path and version on node1; queue jobs dir path, job file format and runner behaviour (GPU assignment, timeout); source file behind `get_withheld_patterns`; `pdftotext` availability; laptop LAN address and subnet (`ipconfig`).

- [ ] **Step 1:** Collect using read-only means only: `mcp__trm-research__queue_status`, `mcp__trm-research__get_withheld_patterns`, `mcp__trm-research__repo_overview`, and `ssh node1` with read-only commands (`python3 --version`, `which claude pdftotext`, `ls`/`head` of the queue dir and runner script). Do not request withheld series.
- [ ] **Step 2:** Write `docs/server-facts.md` with one section per fact and the command that produced it. If the runner already honours GPU ids/timeouts, say so; Task 6 keeps the `run-job` wrapper regardless.
- [ ] **Step 3:** Commit `docs: node1 server facts`.

